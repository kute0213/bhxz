#!/usr/bin/env python3
"""打包发布 zip：排除敏感文件、数据库、上传、备份、SSL、日志、Monaco 编辑器等。"""
import os
import zipfile
from datetime import datetime

ROOT = '/workspace'
OUT_DIR = os.path.join(ROOT, 'release')
os.makedirs(OUT_DIR, exist_ok=True)
OUT_ZIP = os.path.join(OUT_DIR, f'bhxz-{datetime.now():%Y%m%d-%H%M%S}.zip')

# 排除的目录/文件（前缀或精确名）
EXCLUDE_DIRS = {
    '.git', '__pycache__', 'node_modules', 'uploads', 'backups', 'ssl',
    'logs', 'release', '.venv', 'venv', 'env', 'dist', 'build',
}
EXCLUDE_FILES = {
    '*.pyc', '*.pyo', '*.zip', '*.duckdb', '*.duckdb.wal', '*.db',
    '*.db-journal', '*.sqlite', '*.log', '.DS_Store', '.env',
}

# 需要跳过其内容的子路径（monaco 大文件）
EXCLUDE_SUBPATH = ('static/lib/monaco',)

count = 0
with zipfile.ZipFile(OUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # 从根裁剪
        rel_dir = os.path.relpath(dirpath, ROOT)
        if rel_dir == '.':
            rel_dir = ''
        # 跳过排除目录（含整棵子树）
        top = rel_dir.split(os.sep)[0] if rel_dir else ''
        if top in EXCLUDE_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        # 跳过 monaco 子路径
        if any(rel_dir == s or rel_dir.startswith(s + os.sep) for s in EXCLUDE_SUBPATH):
            dirnames[:] = []
            continue
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.join(rel_dir, fn) if rel_dir else fn
            # 按扩展名排除
            if any(fn.endswith(p.replace('*', '')) for p in EXCLUDE_FILES if p.startswith('*')):
                continue
            if fn in EXCLUDE_FILES:
                continue
            zf.write(full, rel)
            count += 1

size = os.path.getsize(OUT_ZIP) / 1024 / 1024
print(f'打包完成: {OUT_ZIP}')
print(f'文件数: {count}, 大小: {size:.1f} MB')