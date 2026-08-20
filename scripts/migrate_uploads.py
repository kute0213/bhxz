#!/usr/bin/env python3
"""迁移脚本：数据库/文件迁移，构建静态资源。

此脚本在每次一键更新完成后自动运行（通过 scripts/uploads.py 调度）。
如果需要，也会运行 scripts/build/build_static.py 构建静态资源。

功能：
  1. 清理旧数据（投票、征集等）—— 委托给 scripts/uploads.py
  2. 迁移 uploads/ 目录文件分类
  3. 可选的静态资源构建（scripts/build/build_static.py）

用法：
  python scripts/migrate_uploads.py [--build]

参数：
  --build   构建静态资源（运行 scripts/build/build_static.py）
"""

import os
import sys
import subprocess
import argparse

# 确保能找到项目根目录（从 scripts/ 向上翻一层）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, '..'))


def _run_uploads_script():
    """运行 scripts/uploads.py 执行清理与迁移。"""
    script_path = os.path.join(_THIS_DIR, 'uploads.py')
    if not os.path.isfile(script_path):
        print('[migrate] scripts/uploads.py 不存在，跳过清理与迁移')
        return True

    print('[migrate] 正在运行 scripts/uploads.py...')
    result = subprocess.run(
        [sys.executable, script_path],
        cwd=_PROJECT_ROOT,
        capture_output=False,
    )
    if result.returncode == 0:
        print('[migrate] scripts/uploads.py 执行完成')
        return True
    else:
        print(f'[migrate] scripts/uploads.py 执行失败（返回码: {result.returncode}）')
        return False


def _run_build_static():
    """运行 scripts/build/build_static.py 构建静态资源。"""
    build_script = os.path.join(_THIS_DIR, 'build', 'build_static.py')
    if not os.path.isfile(build_script):
        print('[migrate] scripts/build/build_static.py 不存在，跳过构建')
        return True

    print('[migrate] 正在构建静态资源...')
    result = subprocess.run(
        [sys.executable, build_script],
        cwd=_PROJECT_ROOT,
        capture_output=False,
    )
    if result.returncode == 0:
        print('[migrate] 静态资源构建完成')
        return True
    else:
        print(f'[migrate] 静态资源构建失败（返回码: {result.returncode}）')
        return False


def run(build_static=False):
    """执行完整迁移流程。"""
    print('=' * 50)
    print('  scripts/migrate_uploads.py — 迁移脚本')
    print('=' * 50)
    print()

    # 步骤 1: 运行 uploads.py 清理与迁移
    print('[步骤 1/2] 清理旧数据与迁移文件...')
    ok = _run_uploads_script()
    if not ok:
        print('[migrate] 步骤 1 失败，流程中止')
        return False

    # 步骤 2: 可选构建静态资源
    if build_static:
        print()
        print('[步骤 2/2] 构建静态资源...')
        ok = _run_build_static()
        if not ok:
            print('[migrate] 步骤 2 失败')
            return False
    else:
        print()
        print('[步骤 2/2] 跳过（使用 --build 可触发静态资源构建）')

    print()
    print('[migrate] 迁移完成')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='迁移脚本')
    parser.add_argument('--build', action='store_true', help='构建静态资源')
    args = parser.parse_args()
    success = run(build_static=args.build)
    sys.exit(0 if success else 1)