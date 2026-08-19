#!/usr/bin/env python3
"""迁移 uploads/ 目录：将旧版根目录散乱的文件按新版功能分类排列。

新版分类：
  uploads/attachments/   — 留言板/讨论区附件（来自 board_replies / discussion_topics / discussion_replies）
  uploads/backgrounds/   — 全站背景图片
  uploads/community/     — 其他社区资源（兜底）

用法：
  python scripts/migrate_uploads.py

工作流程：
  1. 从数据库读取所有附件文件名
  2. 将 uploads/ 根目录中匹配的文件移到 uploads/attachments/
  3. 将根目录中剩余的文件（按扩展名启发式）移入 backgrounds/ 或 community/
  4. 删除空目录/空文件
"""

import json
import os
import shutil
import sys

# 确保能找到项目根目录（从 scripts/ 向上翻一层）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, '..'))
sys.path.insert(0, _PROJECT_ROOT)

UPLOADS_DIR = os.path.join(_PROJECT_ROOT, 'uploads')
ATTACHMENTS_DIR = os.path.join(UPLOADS_DIR, 'attachments')
BACKGROUNDS_DIR = os.path.join(UPLOADS_DIR, 'backgrounds')
COMMUNITY_DIR = os.path.join(UPLOADS_DIR, 'community')

# 图片扩展名（用于判断是否可能是背景图片）
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}

# ---- 统计 ----
stats = {'moved_attachment': 0, 'moved_background': 0, 'moved_community': 0, 'skipped': 0, 'errors': 0}


def ensure_dirs():
    """确保分类子目录存在。"""
    for d in (ATTACHMENTS_DIR, BACKGROUNDS_DIR, COMMUNITY_DIR):
        os.makedirs(d, exist_ok=True)


def collect_db_attachments():
    """从数据库查询所有引用到的附件文件名，返回一个 set。"""
    filenames = set()
    try:
        from core.db.connection import get_db
        conn = get_db()
        cursor = conn.cursor()

        # board_replies.attachment — 存 JSON 数组或单字符串
        try:
            rows = cursor.execute("SELECT attachment FROM board_replies WHERE attachment IS NOT NULL AND attachment != ''").fetchall()
            for row in rows:
                filenames.update(_parse_attachment(row[0]))
        except Exception as e:
            print(f'  [WARN] 读取 board_replies 失败: {e}')

        # discussion_topics.attachment
        try:
            rows = cursor.execute("SELECT attachment FROM discussion_topics WHERE attachment IS NOT NULL AND attachment != ''").fetchall()
            for row in rows:
                filenames.update(_parse_attachment(row[0]))
        except Exception as e:
            print(f'  [WARN] 读取 discussion_topics 失败: {e}')

        # discussion_replies.attachment
        try:
            rows = cursor.execute("SELECT attachment FROM discussion_replies WHERE attachment IS NOT NULL AND attachment != ''").fetchall()
            for row in rows:
                filenames.update(_parse_attachment(row[0]))
        except Exception as e:
            print(f'  [WARN] 读取 discussion_replies 失败: {e}')

        # server_guides.cover_image
        try:
            rows = cursor.execute("SELECT cover_image FROM server_guides WHERE cover_image IS NOT NULL AND cover_image != ''").fetchall()
            for row in rows:
                filenames.add(row[0])
        except Exception as e:
            print(f'  [WARN] 读取 server_guides 失败: {e}')

        conn.close()
    except Exception as e:
        print(f'  [WARN] 无法连接数据库，将仅按文件启发式迁移: {e}')

    return filenames


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


def is_attachment_filename(name, db_names):
    """判断文件是否是已注册的附件。"""
    return name in db_names


def is_background_candidate(name):
    """判断文件是否可能是背景图片（以 bg_ 开头且是图片格式）。"""
    base, ext = os.path.splitext(name)
    return base.startswith('bg_') and ext.lower() in _IMAGE_EXTS


def migrate():
    """执行迁移。"""
    ensure_dirs()

    print('[迁移] 正在收集数据库中的附件文件名...')
    db_attachment_names = collect_db_attachments()
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
            continue  # 跳过子目录
        if entry.startswith('.'):
            continue  # 跳过隐藏文件
        files_to_move.append(entry)

    if not files_to_move:
        print('[迁移] uploads/ 根目录没有需要迁移的文件')
        return

    print(f'[迁移] uploads/ 根目录发现 {len(files_to_move)} 个文件，开始分类迁移...')

    for fname in sorted(files_to_move):
        src = os.path.join(UPLOADS_DIR, fname)

        # 1) 数据库引用的附件 → attachments/
        if is_attachment_filename(fname, db_attachment_names):
            dst = os.path.join(ATTACHMENTS_DIR, fname)
            _move(src, dst)
            stats['moved_attachment'] += 1
            print(f'  [附件] {fname}')
            continue

        # 2) 背景图片 → backgrounds/
        if is_background_candidate(fname):
            dst = os.path.join(BACKGROUNDS_DIR, fname)
            _move(src, dst)
            stats['moved_background'] += 1
            print(f'  [背景] {fname}')
            continue

        # 3) 其他文件 → community/
        dst = os.path.join(COMMUNITY_DIR, fname)
        _move(src, dst)
        stats['moved_community'] += 1
        print(f'  [社区] {fname}')

    # 打印统计
    print()
    print('=' * 40)
    print('  迁移完成')
    print(f'  附件 → uploads/attachments/:  {stats["moved_attachment"]} 个')
    print(f'  背景 → uploads/backgrounds/:  {stats["moved_background"]} 个')
    print(f'  其他 → uploads/community/:    {stats["moved_community"]} 个')
    print(f'  跳过:                        {stats["skipped"]} 个')
    print(f'  错误:                        {stats["errors"]} 个')
    print('=' * 40)


def _move(src, dst):
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


if __name__ == '__main__':
    migrate()