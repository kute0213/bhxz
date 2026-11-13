#!/usr/bin/env python3
"""指南资源结构迁移：图片并入 assets/，正文资源链接改为相对路径。

本次更新后：
* 图片与视频统一存放在 ``uploads/guides/<ID>/assets/``，不再有 ``assets/images/``；
* 正文章节里的资源链接只写 ``assets/<文件名>``，不再包含指南 ID，
  这样替换稿接管原指南 ID 时无需改写任何链接。

脚本对每个指南执行：
1. 把残留的 ``assets/images/*`` 移入 ``assets/`` 并删除空目录；
2. 把 ``/guides/<该指南ID>/assets/...``（含旧 ``images/`` 段、完整 URL 形式）
   改写为 ``assets/...``。

可重复执行，已迁移的指南不会被重复处理。

用法：
    python scripts/migrate_guide_assets.py            # 直接迁移
    python scripts/migrate_guide_assets.py --dry-run  # 只预览，不写盘
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import UPLOAD_GUIDES_DIR  # noqa: E402

MD_FILENAME = 'guide.md'
ASSETS_DIRNAME = 'assets'
LEGACY_IMAGES_DIRNAME = 'images'


def migrate_legacy_images(guide_dir, dry_run=False):
    """把 assets/images/ 中的文件并入 assets/，返回移动数量。"""
    assets = os.path.join(guide_dir, ASSETS_DIRNAME)
    legacy = os.path.join(assets, LEGACY_IMAGES_DIRNAME)
    if not os.path.isdir(legacy):
        return 0

    moved = 0
    for name in os.listdir(legacy):
        src = os.path.join(legacy, name)
        if not os.path.isfile(src) or name.startswith('.'):
            continue
        dst = os.path.join(assets, name)
        if os.path.exists(dst):
            # 同名文件已在资源根目录，直接删除旧副本（内容一致或已被新链接引用）
            if not dry_run:
                os.remove(src)
        else:
            if not dry_run:
                os.replace(src, dst)
        moved += 1

    if not dry_run:
        leftovers = [n for n in os.listdir(legacy) if not n.startswith('.')]
        if not leftovers:
            os.rmdir(legacy)
    return moved


def relative_asset_links(md, guide_id):
    """把正文中指向该指南的绝对资源链接改写为 assets/<文件名>。"""
    text = str(md or '')
    # 完整 URL（http(s)://域名/guides/<ID>/assets/...）与站内绝对路径一并处理
    pattern = re.compile(
        r'(?:(?:https?:)?//[^/\s)"\']+)?'
        r'/guides/%d/assets/(?:%s/)?' % (int(guide_id), LEGACY_IMAGES_DIRNAME)
        + r'([^)\s"\']+)'
    )
    text = pattern.sub(r'assets/\1', text)
    # 相对路径里可能还残留 assets/images/ 或 ./assets/
    text = re.sub(
        r'(?<![\w/])assets/%s/' % LEGACY_IMAGES_DIRNAME,
        'assets/',
        text,
    )
    text = re.sub(r'(?<![\w/])\./assets/', 'assets/', text)
    return text


def migrate_guide(guide_dir, guide_id, dry_run=False):
    """迁移单个指南，返回 (移动文件数, 是否改写正文)。"""
    moved = migrate_legacy_images(guide_dir, dry_run)
    path = os.path.join(guide_dir, MD_FILENAME)
    changed = False
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
        updated = relative_asset_links(content, guide_id)
        if updated != content:
            changed = True
            if not dry_run:
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as fh:
                    fh.write(updated)
                os.replace(tmp, path)
    return moved, changed


def main():
    parser = argparse.ArgumentParser(description='迁移指南资源目录与正文链接')
    parser.add_argument('--dry-run', action='store_true', help='只输出将要执行的改动，不写盘')
    args = parser.parse_args()

    if not os.path.isdir(UPLOAD_GUIDES_DIR):
        print('未找到指南目录：%s' % UPLOAD_GUIDES_DIR)
        return 0

    total_guides = total_moved = total_changed = 0
    for name in sorted(os.listdir(UPLOAD_GUIDES_DIR)):
        guide_dir = os.path.join(UPLOAD_GUIDES_DIR, name)
        if not name.isdigit() or not os.path.isdir(guide_dir):
            continue
        total_guides += 1
        moved, changed = migrate_guide(guide_dir, int(name), args.dry_run)
        if moved or changed:
            total_moved += moved
            total_changed += 1
            print('指南 %s：移动资源 %d 个，%s正文链接' % (
                name, moved, '改写' if changed else '无需改写'))

    action = '待迁移' if args.dry_run else '已迁移'
    print('\n%s完成：共扫描 %d 个指南，处理 %d 个，移动资源 %d 个。' % (
        action, total_guides, total_changed, total_moved))
    return 0


if __name__ == '__main__':
    sys.exit(main())
