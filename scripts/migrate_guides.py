#!/usr/bin/env python3
"""指南存储迁移脚本：数据库正文 → 每个指南独立文件夹。

迁移目标结构（见 services/guides）：

    uploads/guides/<指南ID>/
        guide.md        # 指南 Markdown 源文件（唯一内容来源）
        assets/         # 指南资源（视频等，合计不超过 50MB）

脚本会把 ``server_guides.content`` 写入对应文件夹的 ``guide.md``，
然后清空数据库中的正文（正文改由文件维护）。

用法：
    python scripts/migrate_guides.py             # 执行迁移（幂等）
    python scripts/migrate_guides.py --dry-run   # 只统计，不写文件 / 不改数据库
    python scripts/migrate_guides.py --overwrite # 已存在 guide.md 时用数据库正文覆盖

说明：
- 幂等：数据库正文为空且 guide.md 已存在的指南会被跳过。
- 文件优先：guide.md 已存在且未加 --overwrite 时保留文件，仍会清空数据库正文。
"""

import argparse
import os
import sqlite3
import sys

# 项目根目录（scripts/ 上一级），保证直接运行脚本也能导入项目模块
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import DB_PATH, UPLOAD_GUIDES_DIR  # noqa: E402
from services import guides as guide_store  # noqa: E402


def fetch_guides(conn):
    """读取所有指南的 ID / 标题 / 数据库正文。"""
    rows = conn.execute(
        "SELECT id, title, content FROM server_guides ORDER BY id"
    ).fetchall()
    return [
        {'id': row[0], 'title': row[1] or '', 'content': row[2] or ''}
        for row in rows
    ]


def migrate(dry_run=False, overwrite=False):
    """执行迁移，返回统计字典。"""
    if not os.path.isfile(DB_PATH):
        print(f'[!] 数据库不存在：{DB_PATH}')
        return None

    stats = {
        'total': 0, 'written': 0, 'overwritten': 0,
        'kept': 0, 'cleared': 0, 'bytes': 0, 'skipped': 0,
    }

    conn = sqlite3.connect(DB_PATH)
    try:
        guides = fetch_guides(conn)
        stats['total'] = len(guides)
        print(f'共 {len(guides)} 条指南，数据库：{DB_PATH}')
        print(f'指南目录：{UPLOAD_GUIDES_DIR}')
        print('')

        for guide in guides:
            gid = guide['id']
            content = guide['content']
            md_path = guide_store.guide_md_path(gid)
            exists = os.path.isfile(md_path)

            if exists and not (overwrite and content.strip()):
                # 文件已存在：视为已迁移，补齐 config.json 并清理数据库正文
                stats['kept'] += 1
                label = '保留文件'
                if not dry_run:
                    guide_store.ensure_guide_dir(gid)
                if content.strip():
                    stats['cleared'] += 1
                    if not dry_run:
                        conn.execute(
                            "UPDATE server_guides SET content = '' WHERE id = ?", (gid,)
                        )
                print(f'  [{gid}] {guide["title"][:36]} → {label}'
                      f'{"，清空数据库正文" if content.strip() else "，无需处理"}')
                if not content.strip():
                    stats['skipped'] += 1
                continue

            if not content.strip():
                # 无正文且没有文件：不创建空目录
                stats['skipped'] += 1
                print(f'  [{gid}] {guide["title"][:36]} → 无正文，跳过')
                continue

            if exists:
                stats['overwritten'] += 1
                label = '覆盖'
            else:
                stats['written'] += 1
                label = '写入'

            stats['bytes'] += len(content.encode('utf-8'))
            if not dry_run:
                guide_store.write_guide_content(gid, content)
                conn.execute(
                    "UPDATE server_guides SET content = '' WHERE id = ?", (gid,)
                )
            stats['cleared'] += 1
            print(f'  [{gid}] {guide["title"][:36]} → {label} guide.md，清空数据库正文')

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()

    return stats


def print_summary(stats, dry_run=False):
    """打印迁移结果。"""
    if stats is None:
        return
    print('')
    print('迁移结果' + ('（演练，未写入）' if dry_run else '') + '：')
    print(f'  指南总数：{stats["total"]}')
    print(f'  新写入 guide.md：{stats["written"]}')
    print(f'  覆盖 guide.md：{stats["overwritten"]}')
    print(f'  保留已有文件：{stats["kept"]}')
    print(f'  清空数据库正文：{stats["cleared"]}')
    print(f'  跳过（无正文）：{stats["skipped"]}')
    print(f'  迁移正文字节：{stats["bytes"]} ({guide_store.format_size(stats["bytes"])})')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='把数据库中的指南正文迁移到 uploads/guides/<ID>/guide.md 并清空数据库正文'
    )
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件也不改数据库')
    parser.add_argument('--overwrite', action='store_true',
                        help='guide.md 已存在时，用数据库正文覆盖')
    args = parser.parse_args(argv)

    stats = migrate(dry_run=args.dry_run, overwrite=args.overwrite)
    print_summary(stats, dry_run=args.dry_run)
    return 0 if stats is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
