"""雪花 ID 迁移 —— 把历史自增 ID 统一迁移为雪花 ID（服务器自检时触发）。

背景：全站所有非用户表主键改为雪花算法统一生成（见 core/shared/snowflake.py）。
历史数据里已经确定的（自增）ID 需在「服务器自检」阶段一次性改为雪花 ID，
且要满足：

* **等同于当前时刻同时发布**：迁移按原记录顺序逐条调用 next_id()，
  时间戳为迁移当时的毫秒、序列号递增，迁移完成后这些 ID 看起来就像
  「刚刚同一时刻按顺序发布」的雪花 ID；
* **顺序不变**：按旧 ID 升序重分配，新 ID 单调递增，ORDER BY id 的语义不变；
* **关联关系不变**：父子表外键（如评论 → 建筑、收藏 → 音频）随父表 ID 同步重映射；
* **磁盘文件名同步**：文件名 / 目录名内嵌旧 ID 的记录（音频目录 `music/<id>/`、
  背景图片 `bg_<id>_<hash>.webp` 及其各档响应式变体）在迁移后一并重命名，
  并同步改写库里的 `file_path` / `filename`，避免「库换了 ID、盘上还是旧名」导致 404；
* **播放列表内容同步**：HLS 播放列表 `music/<id>/index.m3u8` 内的分片绝对路径
  （`/music/<id>/<分片>.ts`）内嵌上传当时的 ID，目录改名后内容必须一并改写，
  否则播放器请求分片时仍命中旧 ID 而 404；
* **磁盘对账兜底**：见 `reconcile_media_files()`——数据库改动是事务性的，
  但磁盘改名 / 改内容不是；一旦中途失败或旧版本漏改（如只处理了音频、未处理背景），
  会留下「库里新 ID、盘上旧名」的残留。该函数在每次启动自检时幂等运行，
  把磁盘重新对齐到库里认定的 ID；
* **幂等**：通过比对是否存在历史 ID 判断是否已完成；迁移在单事务内完成，
  要么整体成功要么整体回滚，不会出现半迁移状态。

注意：用户表（users）保持自增 ID 不变，其它表引用用户的那一列（user_id /
author_id / sender_id 等）无需改动。本模块只处理「非用户表主键」。
"""

import os
import re
import shutil
import sqlite3

from core.db.connection import get_db, checkpoint
from core.shared.snowflake import is_snowflake_id, next_id
from core.system.logger import log

# 播放列表内嵌的音频 ID 绝对路径前缀：/music/<数字>/（上传时按当时的 ID 写死）
_PLAYLIST_ID_RE = re.compile(r'/music/\d+/')

# 背景图片响应式变体档位（与 services/background_service.RESPONSIVE_SIZES 一致）：
# 库里只记主文件名 `bg_<id>_<hash>.webp`，各档变体由其推导为 `bg_<id>_<hash>_<size>.webp`
_BG_VARIANT_SIZES = (768, 1280, 1920)

# 需要迁移「自身主键」的非用户表（按父子依赖顺序排列，父表在前）
_OWN_ID_TABLES = (
    'public_buildings',
    'server_guides',
    'music',
    'backgrounds',
    'mod_intros',
    'db_backups',
    'settings',
    'public_paths',
    'guide_edit_bans',
    'broadcast_logs',
    'game_account_registrations',
    'game_account_bans',
    'game_server_ban_applications',
    'building_comments',
    'building_reports',
    'building_favorites',
    'guide_favorites',
)

# 引用「其它非用户表」主键的外键列： (子表, 外键列, 父表)
# 用户相关列（user_id / author_id / ...）不在其中——users 保持自增不变。
_FK_REMAPS = (
    ('music_favorites', 'music_id', 'music'),
    ('building_comments', 'building_id', 'public_buildings'),
    ('building_reports', 'building_id', 'public_buildings'),
    ('building_favorites', 'building_id', 'public_buildings'),
    ('guide_favorites', 'guide_id', 'server_guides'),
)


def _min_id(conn, table):
    """返回表内最小主键；表不存在或无数据返回 None。"""
    try:
        row = conn.execute(f'SELECT MIN(id) AS m FROM {table}').fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return row['m']


def _has_legacy_ids(conn, table):
    """判断表中是否存在历史自增 ID（存在即需迁移）。"""
    m = _min_id(conn, table)
    return m is not None and not is_snowflake_id(m)


def _rewrite_playlist_ids(playlist_path, music_id):
    """把 m3u8 里内嵌的音频 ID 绝对路径改写成指定的 ID，返回是否发生改写。

    分片路径由上传时按当时的 ID 写死（`/music/<ID>/<分片>.ts`）。ID 迁移后
    目录名变成雪花 ID，播放列表内容若不同步改写，播放器请求分片时会命中旧 ID
    （该 ID 在库里已不存在）而 404——即「数据库改了、文件没改」。
    """
    try:
        with open(playlist_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return False

    fixed = _PLAYLIST_ID_RE.sub(f'/music/{music_id}/', content)
    if fixed == content:
        return False
    try:
        with open(playlist_path, 'w', encoding='utf-8') as f:
            f.write(fixed)
    except OSError as e:
        log('WARNING', 'DB', f'播放列表 ID 改写失败 {playlist_path}: {e}')
        return False
    return True


def _rename_music_dirs(mapping):
    """把磁盘上的音频目录名从旧 ID 重命名为雪花 ID（与 music.id / file_path 对齐）。

    music 表迁移只改了主键与 file_path，磁盘目录仍以旧 ID 命名，需同步重命名，
    否则播放地址（/music/<新ID>/...）会 404；目录内的播放列表内容同理需要改写
    （见 _rewrite_playlist_ids）。
    """
    if not mapping:
        return
    from config import UPLOAD_MUSIC_DIR
    for old, new in mapping.items():
        old_dir = os.path.join(UPLOAD_MUSIC_DIR, str(old))
        new_dir = os.path.join(UPLOAD_MUSIC_DIR, str(new))
        if not os.path.isdir(old_dir):
            continue
        try:
            if os.path.isdir(new_dir):
                shutil.rmtree(new_dir, ignore_errors=True)
            os.rename(old_dir, new_dir)
            log('INFO', 'DB', f'音频目录已重命名 {old} → {new}')
        except OSError as e:
            log('WARNING', 'DB', f'音频目录重命名失败 {old} → {new}: {e}')
            continue
        _rewrite_playlist_ids(os.path.join(new_dir, 'index.m3u8'), new)


def _replace_bg_id(filename, old_id, new_id):
    """把背景图片文件名中内嵌的旧 ID 替换为新 ID（保持其余部分不变）。

    背景主图为 `bg_<id>_<hash>.webp`，各档响应式变体为 `bg_<id>_<hash>_<size>.webp`，
    都以内嵌的 `<id>` 区分归属。文件名中解析出的 ID 与 old_id 不一致（或不符合
    命名规则）时原样返回，避免误改无关文件。
    """
    if not filename or not filename.startswith('bg_'):
        return filename
    rest = filename[len('bg_'):]
    idx = rest.find('_')
    head = rest[:idx] if idx > 0 else rest.split('.', 1)[0]
    if not head.isdigit() or head != str(old_id):
        return filename
    return f'bg_{new_id}{filename[len("bg_") + len(head):]}'


def _parse_background_id(filename):
    """从 `bg_<id>...` 文件名解析出 <id>；不符合命名规则返回 None。"""
    if not filename or not filename.startswith('bg_'):
        return None
    rest = filename[len('bg_'):]
    idx = rest.find('_')
    head = rest[:idx] if idx > 0 else rest.split('.', 1)[0]
    return int(head) if head.isdigit() else None


def _rename_background_files(mapping):
    """把磁盘上的背景图片文件名从旧 ID 重命名为雪花 ID（含主图与全部响应式变体）。

    仅改文件名中内嵌的 ID，`_<hash>` / `_<size>` 等其余部分保持不变；
    目录内所有以 `bg_<旧ID>...` 命名的文件会被一次性改写，因此主图与各档变体
    始终与库里的 `filename` / `file_path` 保持一致。
    """
    if not mapping:
        return
    from config import UPLOAD_BACKGROUNDS_DIR
    if not os.path.isdir(UPLOAD_BACKGROUNDS_DIR):
        return
    renamed = 0
    for fname in os.listdir(UPLOAD_BACKGROUNDS_DIR):
        old_id = _parse_background_id(fname)
        if old_id is None:
            continue
        new_id = mapping.get(old_id)
        if new_id is None:
            continue
        new_name = _replace_bg_id(fname, old_id, new_id)
        if new_name == fname:
            continue
        src = os.path.join(UPLOAD_BACKGROUNDS_DIR, fname)
        dst = os.path.join(UPLOAD_BACKGROUNDS_DIR, new_name)
        try:
            if os.path.exists(dst):
                os.remove(dst)
            os.rename(src, dst)
            renamed += 1
        except OSError as e:
            log('WARNING', 'DB', f'背景图片重命名失败 {fname} → {new_name}: {e}')
    if renamed:
        log('INFO', 'DB', f'背景图片文件已重命名 {renamed} 个')


def migrate_legacy_ids():
    """执行雪花 ID 迁移（幂等）。返回实际迁移的记录数。"""
    check = get_db()
    try:
        legacy_tables = [t for t in _OWN_ID_TABLES if _has_legacy_ids(check, t)]
    finally:
        check.close()

    if not legacy_tables:
        log('INFO', 'DB', '雪花 ID 自检：无历史自增 ID 需要迁移')
        return 0

    log('INFO', 'DB', f'雪花 ID 自检：检测到 {len(legacy_tables)} 张表含历史 ID，开始迁移')

    migrated = 0
    music_map = {}
    bg_map = {}
    # 迁移在一个事务内完成：先改父表 ID，再同步重映射子表外键，
    # 保证关联关系不变；要么整体成功、要么整体回滚，不会出现半迁移状态。
    # 迁移期间关闭外键约束（中间态会短暂不一致，若开启外键会报错），
    # PRAGMA foreign_keys 只能在事务外切换，故先关、迁移完再恢复。
    conn = get_db()
    try:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('BEGIN IMMEDIATE')
        try:
            mappings = {}
            # 改主键之前先记下 music 各记录的 file_path 是否非空（改完按旧 ID 就查不到了）
            music_had_file = {}
            if 'music' in legacy_tables:
                music_had_file = {
                    r['id']: bool((r['file_path'] or '').strip())
                    for r in conn.execute('SELECT id, file_path FROM music').fetchall()
                }
            for table in _OWN_ID_TABLES:
                rows = conn.execute(f'SELECT id FROM {table} ORDER BY id').fetchall()
                if not rows or table not in legacy_tables:
                    mappings[table] = {}
                    continue
                updates = []
                mapping = {}
                for r in rows:
                    old = r['id']
                    new = next_id()
                    mapping[old] = new
                    updates.append((new, old))
                conn.executemany(f'UPDATE {table} SET id = ? WHERE id = ?', updates)
                mappings[table] = mapping
                migrated += len(updates)

            # music 的 file_path 内嵌音频 ID（music/<id>/index.m3u8），随主键同步改写。
            # 只改写原本就指向文件的记录：file_path 为空的记录（上传中途失败的残留）
            # 目录从来不存在，不能凭空编造一个指向不存在目录的 file_path。
            music_map = mappings.get('music') or {}
            if music_map:
                conn.executemany(
                    'UPDATE music SET file_path = ? WHERE id = ?',
                    [(f'music/{new}/index.m3u8', new) for old, new in music_map.items()
                     if music_had_file.get(old)],
                )

            # backgrounds 的 filename / file_path 内嵌背景 ID（bg_<id>_<hash>.webp），
            # 随主键同步改写；磁盘文件在事务提交后统一重命名（见下）
            bg_map = mappings.get('backgrounds') or {}
            if bg_map:
                for old, new in bg_map.items():
                    row = conn.execute(
                        'SELECT filename, file_path FROM backgrounds WHERE id = ?', (new,)
                    ).fetchone()
                    if not row:
                        continue
                    old_name = row['filename'] or ''
                    new_name = _replace_bg_id(old_name, old, new)
                    if new_name == old_name:
                        continue
                    base_dir = os.path.dirname(row['file_path'] or '')
                    new_path = os.path.join(base_dir, new_name) if base_dir else new_name
                    conn.execute(
                        'UPDATE backgrounds SET filename = ?, file_path = ? WHERE id = ?',
                        (new_name, new_path, new),
                    )

            # 父表 ID 已重分配后，同步重映射子表外键，保证关联关系不变
            for child, col, parent in _FK_REMAPS:
                mapping = mappings.get(parent) or {}
                if not mapping:
                    continue
                updates = [(new, old) for old, new in mapping.items()]
                if updates:
                    conn.executemany(
                        f'UPDATE {child} SET {col} = ? WHERE {col} = ?', updates
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.close()

    # 事务提交后重命名磁盘文件 / 目录（文件系统操作无法回滚，放在最后执行）
    _rename_music_dirs(music_map)
    _rename_background_files(bg_map)
    # 大批量改写完成后合并 WAL，确保数据进入主库单文件
    checkpoint()

    log('INFO', 'DB', f'雪花 ID 迁移完成：共重分配 {migrated} 条记录')
    return migrated


# ---------------------------------------------------------------------------
# 磁盘对账 —— 把磁盘上的文件名 / 目录名 / 播放列表内容重新对齐到库里的 ID
#
# 为什么需要：数据库改动是事务性的（要么全成要么全回滚），但磁盘改名与
# 播放列表改内容是文件系统操作，无法回滚。一旦中途失败、进程被杀，或旧版本
# 漏改（例如只处理了音频目录、没有处理背景图片文件名），就会留下
# 「库里已经是新 ID、盘上还是旧名 / 旧内容」的残留，表现为播放或取图 404。
# 迁移只在「检测到历史 ID」时运行一次，这类残留它不会再碰，因此需要一层
# 每次启动都幂等运行的兜底对账。
# ---------------------------------------------------------------------------

def _bg_tail(filename):
    """返回背景文件名中「`bg_<id>` 之后」的部分（如 `_<hash>.webp`、`_<hash>_768.webp`）。

    `bg_` 与 `<id>` 前缀在 ID 迁移后会变，而其后的 `<hash>`（及档位后缀）稳定不变，
    可作为「同一张图片」的指纹：不掌握旧→新 ID 映射也能把磁盘文件对齐到库里的新名字。
    不符合命名规则（不含 `bg_<id>_`）时返回 None。
    """
    if not filename or not filename.startswith('bg_'):
        return None
    rest = filename[len('bg_'):]
    idx = rest.find('_')
    if idx <= 0 or not rest[:idx].isdigit():
        return None
    return rest[idx:]


def _apply_background_renames(targets):
    """按 `tail → 目标文件名` 对照表把磁盘文件重命名为目标名（主图与各档变体一并覆盖）。

    仅改「tail 命中且名字不符」的文件；目标名已存在时不动源文件（避免误删），
    无关文件原样保留。返回实际改名数量。
    """
    if not targets:
        return 0
    from config import UPLOAD_BACKGROUNDS_DIR
    if not os.path.isdir(UPLOAD_BACKGROUNDS_DIR):
        return 0
    renamed = 0
    for fname in os.listdir(UPLOAD_BACKGROUNDS_DIR):
        tail = _bg_tail(fname)
        target = targets.get(tail) if tail else None
        if not target or target == fname:
            continue
        src = os.path.join(UPLOAD_BACKGROUNDS_DIR, fname)
        dst = os.path.join(UPLOAD_BACKGROUNDS_DIR, target)
        if os.path.exists(dst):
            continue
        try:
            os.rename(src, dst)
            renamed += 1
        except OSError as e:
            log('WARNING', 'DB', f'背景图片对账重命名失败 {fname} → {target}: {e}')
    return renamed


def _reconcile_background_files():
    """按库里 `filename` 认定的名字修复磁盘上的背景图片文件名。"""
    conn = get_db()
    try:
        rows = conn.execute('SELECT filename, file_path FROM backgrounds').fetchall()
    finally:
        conn.close()

    targets = {}
    ambiguous = set()
    for row in rows:
        name = (row['filename'] or '').strip() or os.path.basename(row['file_path'] or '')
        if not _bg_tail(name):
            continue
        # 主图与全部响应式变体都要登记：库里只存主文件名，变体名由其推导
        stem = name[:-len('.webp')] if name.endswith('.webp') else name
        for cand in [name] + [f'{stem}_{size}.webp' for size in _BG_VARIANT_SIZES]:
            tail = _bg_tail(cand)
            if not tail:
                continue
            existing = targets.get(tail)
            if existing is not None and existing != cand:
                # 同一指纹对应两个不同目标名（理论上不会发生）：放弃该指纹，避免误改
                ambiguous.add(tail)
                continue
            targets[tail] = cand
    for tail in ambiguous:
        targets.pop(tail, None)

    # 数据行先建指纹表，再统一改名，避免边改名边查库
    renamed = _apply_background_renames(targets)
    if renamed:
        log('INFO', 'DB', f'背景图片文件名对账：{renamed} 个文件已对齐到库里的 ID')
    return renamed


def _plan_music_renames(missing, orphans):
    """把「遗留目录（旧 ID 升序）」与「目录缺失的记录（新 ID 升序）」按顺序一一配对。

    迁移时新 ID 是**按旧 ID 升序**逐条分配的（见 migrate_legacy_ids），因此
    「还没改名的遗留目录」与「磁盘目录缺失的记录」在集合相同时顺序一一对应。
    两侧数量不一致说明另有异常（例如记录已被删但目录残留），此时返回 None
    不猜——宁可让用户看到告警，也不能把音频目录挂到错误的记录上。
    """
    if not missing or not orphans or len(missing) != len(orphans):
        return None
    return list(zip(orphans, missing))


def _apply_music_renames(pairs):
    """把磁盘音频目录由旧 ID 重命名为新 ID；返回实际改名数量。

    改名后同步改写目录内播放列表（分片绝对路径内嵌的旧 ID）。
    """
    if not pairs:
        return 0
    from config import UPLOAD_MUSIC_DIR
    renamed = 0
    for old, new in pairs:
        src = os.path.join(UPLOAD_MUSIC_DIR, str(old))
        dst = os.path.join(UPLOAD_MUSIC_DIR, str(new))
        if not os.path.isdir(src) or os.path.exists(dst):
            continue
        try:
            os.rename(src, dst)
            renamed += 1
        except OSError as e:
            log('WARNING', 'DB', f'音频目录对账重命名失败 {old} → {new}: {e}')
            continue
        _rewrite_playlist_ids(os.path.join(dst, 'index.m3u8'), new)
    return renamed


def _reconcile_music_layout():
    """对账音频目录名与播放列表内容，返回 (改名的目录数, 改写的播放列表数)。

    目录名：库里的音频路径由 ID 推导（`music/<id>/index.m3u8`），盘上目录名不是
    当前 ID 就会 404，故按 `_plan_music_renames` 的配对修复。
    播放列表：目录名正确但 m3u8 内嵌旧 ID 的（迁移只改了库、没改文件内容），
    按库里的 ID 逐个改写。
    """
    from config import UPLOAD_MUSIC_DIR
    if not os.path.isdir(UPLOAD_MUSIC_DIR):
        return 0, 0

    conn = get_db()
    try:
        # file_path 为空的记录是上传中途失败的残留（目录从来不存在），不参与对账
        rows = conn.execute("SELECT id FROM music WHERE file_path != ''").fetchall()
    finally:
        conn.close()
    known = [r['id'] for r in rows]
    known_set = set(known)

    missing = sorted(i for i in known
                     if not os.path.isdir(os.path.join(UPLOAD_MUSIC_DIR, str(i))))
    orphans = []
    for name in os.listdir(UPLOAD_MUSIC_DIR):
        path = os.path.join(UPLOAD_MUSIC_DIR, name)
        if not name.isdigit() or not os.path.isdir(path):
            continue
        if int(name) in known_set:
            continue
        if not os.path.isfile(os.path.join(path, 'index.m3u8')):
            continue        # 不是完整的音频目录，不参与对账
        orphans.append(int(name))
    orphans.sort()

    pairs = _plan_music_renames(missing, orphans)
    if missing and orphans and len(missing) != len(orphans):
        log('WARNING', 'DB',
            f'音频目录对账跳过：目录缺失的记录 {len(missing)} 个、遗留目录 {len(orphans)} 个，'
            f'数量不一致，未做任何改动，请人工确认')
    renamed = _apply_music_renames(pairs or [])

    # 目录名已对齐后，再统一改写各目录内播放列表里内嵌的旧 ID
    rewritten = 0
    for mid in known:
        playlist = os.path.join(UPLOAD_MUSIC_DIR, str(mid), 'index.m3u8')
        if os.path.isfile(playlist) and _rewrite_playlist_ids(playlist, mid):
            rewritten += 1
    if rewritten:
        log('INFO', 'DB', f'播放列表 ID 对账：{rewritten} 个 m3u8 已改写为新 ID')
    return renamed, rewritten


def reconcile_media_files():
    """对账磁盘文件与数据库 ID（幂等，每次启动自检调用）。返回修复项数量。

    修复「库里已改成新 ID、盘上还是旧 ID」的不一致：
      * 背景图片：以文件名里稳定的 `<hash>[_<档位>]` 后缀为指纹改名；
      * 音频目录：按迁移时「新 ID 随旧 ID 升序分配」的顺序关系配对改名；
      * 播放列表：按库里的 ID 逐个改写 m3u8 内嵌的分片绝对路径。
    """
    fixed_bg = _reconcile_background_files()
    fixed_music, fixed_playlist = _reconcile_music_layout()
    total = fixed_bg + fixed_music + fixed_playlist
    if total:
        log('INFO', 'DB',
            f'磁盘对账完成：背景图片 {fixed_bg} 个、音频目录 {fixed_music} 个、'
            f'播放列表 {fixed_playlist} 个')
    return total
