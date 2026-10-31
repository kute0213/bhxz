"""服务器指南文件存储服务。

指南不再把正文存在数据库，而是以「每个指南一个文件夹」的方式存放在
``uploads/guides/`` 下：

    uploads/guides/<指南ID>/
        guide.md        # 指南 Markdown 源文件（唯一内容来源）
        assets/         # 指南资源（视频等），合计不超过 50MB

指南在「新建」时即获得 ID 与目录，因此编辑页上传的资源直接写入
``assets/``，不再需要临时草稿目录。

本模块为纯 Python（不依赖 Flask / 数据库），供路由与迁移脚本复用。
"""

import os
import re
import shutil
from datetime import datetime, timedelta

from config import (
    UPLOAD_GUIDES_DIR,
    GUIDE_RESOURCE_MAX_BYTES,
    GUIDE_VIDEO_EXTENSIONS,
    GUIDE_DRAFT_KEEP_HOURS,
)

MD_FILENAME = 'guide.md'
ASSETS_DIRNAME = 'assets'
DRAFT_DIRNAME = '_drafts'  # 旧版草稿目录，仅用于清理历史残留


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def guide_dir(guide_id):
    """指南文件夹：uploads/guides/<指南ID>。"""
    return os.path.join(UPLOAD_GUIDES_DIR, str(int(guide_id)))


def guide_md_path(guide_id):
    """指南 Markdown 源文件路径。"""
    return os.path.join(guide_dir(guide_id), MD_FILENAME)


def assets_dir_for(guide_id):
    """指南资源目录（视频等）。"""
    return os.path.join(guide_dir(guide_id), ASSETS_DIRNAME)


def draft_dir(token):
    """旧版草稿根目录：uploads/guides/_drafts/<token>（仅用于清理残留）。"""
    return os.path.join(UPLOAD_GUIDES_DIR, DRAFT_DIRNAME, str(token))


def ensure_guide_dir(guide_id):
    """确保指南目录与 assets 目录存在。"""
    os.makedirs(assets_dir_for(guide_id), exist_ok=True)


# ---------------------------------------------------------------------------
# 正文（guide.md）
# ---------------------------------------------------------------------------

def read_guide_content(guide_id, fallback=''):
    """读取指南 Markdown 正文。

    文件存在时以文件为准；文件缺失时回退到数据库旧内容（迁移前的数据），
    保证迁移脚本尚未执行时站点仍可正常显示。
    """
    path = guide_md_path(guide_id)
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                return fh.read()
        except OSError:
            return fallback or ''
    return fallback or ''


def write_guide_content(guide_id, content):
    """写入指南 Markdown 正文（先写临时文件再原子替换）。"""
    ensure_guide_dir(guide_id)
    path = guide_md_path(guide_id)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(str(content or ''))
    os.replace(tmp, path)
    return path


def delete_guide_dir(guide_id):
    """删除整个指南文件夹（正文 + 资源）。目录不存在时静默。"""
    shutil.rmtree(guide_dir(guide_id), ignore_errors=True)


# ---------------------------------------------------------------------------
# 资源文件名 / 大小
# ---------------------------------------------------------------------------

def safe_asset_name(filename):
    """把上传文件名转换为安全的资源文件名（保留中文，去掉路径与危险字符）。"""
    raw = os.path.basename(str(filename or '').replace('\\', '/')).strip()
    if not raw:
        return 'asset'
    stem, ext = os.path.splitext(raw)
    stem = re.sub(r'[^\w\- .()]+', '_', stem).strip(' ._')[:80] or 'asset'
    ext = re.sub(r'[^A-Za-z0-9]', '', ext.lstrip('.')).lower()
    return f'{stem}.{ext}' if ext else stem


def _unique_name(directory, name):
    """在目录内生成不冲突的文件名。"""
    base, ext = os.path.splitext(name)
    candidate = name
    i = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f'{base}-{i}{ext}'
        i += 1
    return candidate


def is_video_name(filename):
    """文件名扩展名是否为允许的视频格式。"""
    ext = str(filename or '').rsplit('.', 1)[-1].lower() if '.' in str(filename or '') else ''
    return ext in GUIDE_VIDEO_EXTENSIONS


def format_size(size):
    """字节数转可读文本（如 12.3 MB）。"""
    n = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            if unit == 'B':
                return f'{int(n)} B'
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} GB'


# ---------------------------------------------------------------------------
# 资源列表 / 配额 / 保存 / 删除
# ---------------------------------------------------------------------------

def _iter_files(directory):
    """遍历目录内的普通文件（忽略子目录与隐藏临时文件）。"""
    if not os.path.isdir(directory):
        return
    with os.scandir(directory) as entries:
        for entry in entries:
            try:
                if entry.is_file() and not entry.name.startswith('.'):
                    yield entry.name, entry.stat().st_size
            except OSError:
                continue


def list_assets(directory):
    """列出目录内的资源：``[{'name': ..., 'size': ..., 'size_label': ...}]``。"""
    items = []
    for name, size in sorted(_iter_files(directory), key=lambda x: x[0].lower()):
        items.append({'name': name, 'size': size, 'size_label': format_size(size)})
    return items


def directory_total(directory):
    """目录内所有资源文件的总字节数。"""
    return sum(size for _, size in _iter_files(directory))


def guide_total(guide_id):
    """指南资源占用字节数。"""
    return directory_total(assets_dir_for(guide_id))


def _quota_error(total, size):
    limit = GUIDE_RESOURCE_MAX_BYTES
    if (total or 0) + (size or 0) > limit:
        return (
            f'资源超出上限：每个指南最多 {format_size(limit)}，'
            f'当前已用 {format_size(total)}'
        )
    return ''


def _save_upload(directory, upload):
    """把上传文件保存到目录（自动重名），返回 (文件名, 字节数)。"""
    os.makedirs(directory, exist_ok=True)
    name = _unique_name(directory, safe_asset_name(upload.filename))
    path = os.path.join(directory, name)
    upload.save(path)
    return name, os.path.getsize(path)


def save_guide_asset(guide_id, upload):
    """保存指南资源，返回 ``(ok, message, item)``。

    item 为 ``{'name', 'size', 'size_label'}``；配额按整个 assets 目录累计。
    """
    directory = assets_dir_for(guide_id)
    os.makedirs(directory, exist_ok=True)
    total = directory_total(directory)
    # 先估算大小，超配额时不落盘
    try:
        stream = getattr(upload, 'stream', None)
        if stream is not None:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
        else:
            size = 0
    except (AttributeError, OSError):
        size = 0
    msg = _quota_error(total, size)
    if msg:
        return False, msg, None
    name, size = _save_upload(directory, upload)
    return True, '', {'name': name, 'size': size, 'size_label': format_size(size)}


def delete_asset(directory, filename):
    """删除目录内的单个资源文件。返回是否实际删除。"""
    name = os.path.basename(str(filename or ''))
    path = os.path.join(directory, name)
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False


# ---------------------------------------------------------------------------
# 旧版草稿目录清理
# ---------------------------------------------------------------------------

def cleanup_stale_drafts(keep_hours=GUIDE_DRAFT_KEEP_HOURS):
    """删除超过保留时长的草稿目录，返回删除数量。"""
    root = os.path.join(UPLOAD_GUIDES_DIR, DRAFT_DIRNAME)
    if not os.path.isdir(root):
        return 0
    deadline = datetime.now() - timedelta(hours=keep_hours)
    removed = 0
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            continue
        if mtime < deadline:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
