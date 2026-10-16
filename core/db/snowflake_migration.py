"""雪花 ID 迁移 —— 把历史自增 ID 统一迁移为雪花 ID（服务器自检时触发）。

背景：全站所有非用户表主键改为雪花算法统一生成（见 core/shared/snowflake.py）。
历史数据里已经确定的（自增）ID 需在「服务器自检」阶段一次性改为雪花 ID，
且要满足：

* **等同于当前时刻同时发布**：迁移按原记录顺序逐条调用 next_id()，
  时间戳为迁移当时的毫秒、序列号递增，迁移完成后这些 ID 看起来就像
  「刚刚同一时刻按顺序发布」的雪花 ID；
* **顺序不变**：按旧 ID 升序重分配，新 ID 单调递增，ORDER BY id 的语义不变；
* **关联关系不变**：父子表外键（如评论 → 建筑、收藏 → 音频）随父表 ID 同步重映射；
* **幂等**：通过比对是否存在历史 ID 判断是否已完成；迁移在单事务内完成，
  要么整体成功要么整体回滚，不会出现半迁移状态。

注意：用户表（users）保持自增 ID 不变，其它表引用用户的那一列（user_id /
author_id / sender_id 等）无需改动。本模块只处理「非用户表主键」。
"""

import os
import shutil
import sqlite3

from core.db.connection import get_db
from core.shared.snowflake import is_snowflake_id, next_id
from core.system.logger import log

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


def _rename_music_dirs(mapping):
    """把磁盘上的音频目录名从旧 ID 重命名为雪花 ID（与 music.id / file_path 对齐）。

    music 表迁移只改了主键与 file_path，磁盘目录仍以旧 ID 命名，需同步重命名，
    否则播放地址（/music/<新ID>/...）会 404。
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
    # 迁移在一个事务内完成：先改父表 ID，再同步重映射子表外键，
    # 保证关联关系不变；要么整体成功、要么整体回滚，不会出现半迁移状态。
    # 迁移期间关闭外键约束（中间态会短暂不一致，若开启外键会报错），
    # PRAGMA foreign_keys 只能在事务外切换，故先关、迁移完再恢复。
    conn = get_db()
    try:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('BEGIN')
        try:
            mappings = {}
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

            # music 的 file_path 内嵌音频 ID（music/<id>/index.m3u8），随主键同步改写
            music_map = mappings.get('music') or {}
            if music_map:
                conn.executemany(
                    'UPDATE music SET file_path = ? WHERE id = ?',
                    [(f'music/{new}/index.m3u8', new) for new in music_map.values()],
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

    # 事务提交后重命名磁盘音频目录（文件系统操作无法回滚，放在最后执行）
    _rename_music_dirs(music_map)

    log('INFO', 'DB', f'雪花 ID 迁移完成：共重分配 {migrated} 条记录')
    return migrated
