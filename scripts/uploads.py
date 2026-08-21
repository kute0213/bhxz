#!/usr/bin/env python3
"""一键更新后运行的脚本：清理旧数据 + 迁移文件。

功能：
  1. 删除投票与征集数据（polls、poll_options、poll_votes、board_topics、board_replies）
  2. 删除关联的附件文件（board_replies 中的附件）
  3. 迁移 uploads/ 目录：将旧版根目录散乱的文件按新版功能分类排列

用法：
  python scripts/uploads.py

此脚本在每次一键更新完成后自动运行（若存在），无需手动调用。
"""

import json
import os
import shutil
import sys

# 确保能找到项目根目录（从 scripts/ 向上翻一层）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, '..'))
sys.path.insert(0, _PROJECT_ROOT)

# ---- 目录配置 ----
UPLOADS_DIR = os.path.join(_PROJECT_ROOT, 'uploads')
ATTACHMENTS_DIR = os.path.join(UPLOADS_DIR, 'attachments')
BACKGROUNDS_DIR = os.path.join(UPLOADS_DIR, 'backgrounds')
COMMUNITY_DIR = os.path.join(UPLOADS_DIR, 'community')
SITEMAP_DIR = os.path.join(UPLOADS_DIR, 'sitemap')

# 图片扩展名（用于判断是否可能是背景图片）
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}

# ---- 统计 ----
stats = {
    'polls_deleted': 0,
    'board_topics_deleted': 0,
    'board_replies_deleted': 0,
    'attachments_deleted': 0,
    'moved_attachment': 0,
    'moved_background': 0,
    'moved_community': 0,
    'skipped': 0,
    'errors': 0,
}


# ============================================================================
# 第一部分：清理投票与征集数据
# ============================================================================

def _clean_polls_data():
    """删除所有投票与征集数据。"""
    conn = None
    try:
        from core.db.connection import get_db
        conn = get_db()
        cursor = conn.cursor()

        # 1. 删除征集回复及其附件文件
        reply_rows = cursor.execute(
            "SELECT id, attachment FROM board_replies WHERE attachment IS NOT NULL AND attachment != ''"
        ).fetchall()
        for row in reply_rows:
            _delete_attachment_files(row['attachment'])
            stats['attachments_deleted'] += 1

        stats['board_replies_deleted'] = cursor.execute(
            "SELECT COUNT(*) AS c FROM board_replies"
        ).fetchone()['c']
        cursor.execute("DELETE FROM board_replies")

        stats['board_topics_deleted'] = cursor.execute(
            "SELECT COUNT(*) AS c FROM board_topics"
        ).fetchone()['c']
        cursor.execute("DELETE FROM board_topics")

        # 2. 删除投票数据
        cursor.execute("DELETE FROM poll_votes")
        cursor.execute("DELETE FROM poll_options")
        stats['polls_deleted'] = cursor.execute(
            "SELECT COUNT(*) AS c FROM polls"
        ).fetchone()['c']
        cursor.execute("DELETE FROM polls")

        conn.commit()
        return True
    except Exception as e:
        print(f'[错误] 清理数据失败: {e}')
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _delete_attachment_files(attachment_val):
    """删除 attachment 列中引用的文件。"""
    if not attachment_val:
        return
    filenames = _parse_attachment(attachment_val)
    for fname in filenames:
        if not fname:
            continue
        # 尝试从 attachments、community、uploads 根目录删除
        for base_dir in (ATTACHMENTS_DIR, COMMUNITY_DIR, UPLOADS_DIR):
            fp = os.path.join(base_dir, fname)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
                break


def _parse_attachment(val):
    """解析 attachment 列的值（兼容 JSON 数组和纯字符串）。"""
    if not val:
        return []
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except (json.JSONDecodeError, TypeError):
        return [str(val)]


# ============================================================================
# 第二部分：迁移 uploads/ 目录文件
# ============================================================================

def _ensure_dirs():
    """确保分类子目录存在。"""
    for d in (ATTACHMENTS_DIR, BACKGROUNDS_DIR, COMMUNITY_DIR, SITEMAP_DIR):
        os.makedirs(d, exist_ok=True)


def _collect_db_attachments():
    """从数据库查询所有引用到的附件文件名，返回一个 set。"""
    filenames = set()
    try:
        from core.db.connection import get_db
        conn = get_db()
        cursor = conn.cursor()

        # discussion_topics.attachment
        try:
            rows = cursor.execute(
                "SELECT attachment FROM discussion_topics WHERE attachment IS NOT NULL AND attachment != ''"
            ).fetchall()
            for row in rows:
                filenames.update(_parse_attachment(row[0]))
        except Exception as e:
            print(f'  [WARN] 读取 discussion_topics 失败: {e}')

        # discussion_replies.attachment
        try:
            rows = cursor.execute(
                "SELECT attachment FROM discussion_replies WHERE attachment IS NOT NULL AND attachment != ''"
            ).fetchall()
            for row in rows:
                filenames.update(_parse_attachment(row[0]))
        except Exception as e:
            print(f'  [WARN] 读取 discussion_replies 失败: {e}')

        # server_guides.cover_image
        try:
            rows = cursor.execute(
                "SELECT cover_image FROM server_guides WHERE cover_image IS NOT NULL AND cover_image != ''"
            ).fetchall()
            for row in rows:
                filenames.add(row[0])
        except Exception as e:
            print(f'  [WARN] 读取 server_guides 失败: {e}')

        conn.close()
    except Exception as e:
        print(f'  [WARN] 无法连接数据库，将仅按文件启发式迁移: {e}')

    return filenames


def _is_attachment_filename(name, db_names):
    """判断文件是否是已注册的附件。"""
    return name in db_names


def _is_background_candidate(name):
    """判断文件是否可能是背景图片（以 bg_ 开头且是图片格式）。"""
    base, ext = os.path.splitext(name)
    return base.startswith('bg_') and ext.lower() in _IMAGE_EXTS


def _migrate_file(src, dst):
    """移动文件，跳过已存在的目标。"""
    if os.path.exists(dst):
        print(f'  [跳过] 目标已存在: {os.path.basename(dst)}')
        stats['skipped'] += 1
        return
    try:
        shutil.move(src, dst)
    except Exception as e:
        print(f'  [错误] 移动 {os.path.basename(src)} 失败: {e}')
        stats['errors'] += 1


def _migrate_uploads():
    """迁移 uploads/ 根目录文件到分类子目录。"""
    _ensure_dirs()

    print('[迁移] 正在收集数据库中的附件文件名...')
    db_attachment_names = _collect_db_attachments()
    print(f'  -> 数据库中共引用 {len(db_attachment_names)} 个附件文件')

    # 扫描 uploads/ 根目录下的所有文件（不递归子目录）
    root_entries = []
    try:
        root_entries = os.listdir(UPLOADS_DIR)
    except FileNotFoundError:
        print('[迁移] uploads/ 目录不存在，无需迁移')
        return

    files_to_move = []
    for entry in root_entries:
        full_path = os.path.join(UPLOADS_DIR, entry)
        if not os.path.isfile(full_path):
            continue
        if entry.startswith('.'):
            continue
        files_to_move.append(entry)

    if not files_to_move:
        print('[迁移] uploads/ 根目录没有需要迁移的文件')
        return

    print(f'[迁移] uploads/ 根目录发现 {len(files_to_move)} 个文件，开始分类迁移...')

    for fname in sorted(files_to_move):
        src = os.path.join(UPLOADS_DIR, fname)

        # 1) 数据库引用的附件 → attachments/
        if _is_attachment_filename(fname, db_attachment_names):
            dst = os.path.join(ATTACHMENTS_DIR, fname)
            _migrate_file(src, dst)
            stats['moved_attachment'] += 1
            print(f'  [附件] {fname}')
            continue

        # 2) 背景图片 → backgrounds/
        if _is_background_candidate(fname):
            dst = os.path.join(BACKGROUNDS_DIR, fname)
            _migrate_file(src, dst)
            stats['moved_background'] += 1
            print(f'  [背景] {fname}')
            continue

        # 3) 其他文件 → community/
        dst = os.path.join(COMMUNITY_DIR, fname)
        _migrate_file(src, dst)
        stats['moved_community'] += 1
        print(f'  [其他] {fname}')


# ============================================================================
# 第三部分：提升用户权限 + 创建目录
# ============================================================================

def _promote_kute_mc():
    """将 kute_mc 用户提升为最高权限（is_admin = 1）。"""
    try:
        from core.db.connection import get_db
        conn = get_db()
        cursor = conn.cursor()

        # 查找 kute_mc 用户
        cursor.execute("SELECT id, username, is_admin FROM users WHERE lower(username) = lower('kute_mc')")
        row = cursor.fetchone()
        if row:
            if row['is_admin'] == 1:
                print(f'  -> kute_mc (#{row["id"]}) 已是管理员')
            else:
                cursor.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row['id'],))
                conn.commit()
                print(f'  -> kute_mc (#{row["id"]}) 已提升为管理员')
        else:
            print('  -> kute_mc 用户不存在，跳过')

        conn.close()
    except Exception as e:
        print(f'  [WARN] 提升 kute_mc 失败: {e}')


def _ensure_sitemap_dir():
    """确保 /uploads/sitemap 目录存在。"""
    try:
        os.makedirs(SITEMAP_DIR, exist_ok=True)
        print(f'  -> sitemap 目录已就绪: {SITEMAP_DIR}')
    except Exception as e:
        print(f'  [WARN] 创建 sitemap 目录失败: {e}')


# ============================================================================
# 入口
# ============================================================================

def run():
    """执行清理与迁移。"""
    print('=' * 50)
    print('  scripts/uploads.py — 清理与迁移')
    print('=' * 50)
    print()
    print('[步骤 1/3] 备份当前数据库...')
    try:
        backup_dir = os.path.join(_PROJECT_ROOT, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        db_path = os.path.join(_PROJECT_ROOT, 'site.duckdb')
        if os.path.isfile(db_path):
            import shutil
            import datetime
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(backup_dir, f'site_pre_cleanup_{ts}.duckdb')
            shutil.copy2(db_path, backup_path)
            print(f'  -> 已备份到: {backup_path}')
        else:
            print('  -> 未找到数据库文件')
    except Exception as e:
        print(f'  [WARN] 备份失败: {e}')

    print()
    print('[步骤 2/3] 清理投票与征集数据...')
    if _clean_polls_data():
        print(f'  -> 已删除 {stats["polls_deleted"]} 个投票')
        print(f'  -> 已删除 {stats["board_topics_deleted"]} 个征集主题')
        print(f'  -> 已删除 {stats["board_replies_deleted"]} 条征集回复')
        print(f'  -> 已删除 {stats["attachments_deleted"]} 个附件文件')
    else:
        print('  [WARN] 清理数据失败，请检查数据库连接')

    print()
    print('[步骤 3/3] 迁移 uploads/ 目录文件...')
    _migrate_uploads()

    print()
    print('[步骤 4/4] 提升 kute_mc 为管理员并创建 sitemap 目录...')
    _promote_kute_mc()
    _ensure_sitemap_dir()

    print()
    print('=' * 50)
    print('  清理与迁移完成')
    print(f'  投票:          {stats["polls_deleted"]} 个')
    print(f'  征集主题:      {stats["board_topics_deleted"]} 个')
    print(f'  征集回复:      {stats["board_replies_deleted"]} 条')
    print(f'  附件文件:      {stats["attachments_deleted"]} 个')
    print(f'  文件迁移:      {stats["moved_attachment"]} 附件 + {stats["moved_background"]} 背景 + {stats["moved_community"]} 其他')
    print(f'  跳过:          {stats["skipped"]} 个')
    print(f'  错误:          {stats["errors"]} 个')
    print('=' * 50)


if __name__ == '__main__':
    run()