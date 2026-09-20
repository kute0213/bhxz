#!/usr/bin/env python3
"""滨海小镇 - 手动更新脚本（跨平台）

用法:
    python scripts/update.py

从 GitHub 拉取最新代码，支持本地修改暂存与恢复。
"""

import os
import sys
import subprocess
import shutil

# ── 颜色 ────────────────────────────────────────────────────────────────
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
CYAN = '\033[0;36m'
RED = '\033[0;31m'
NC = '\033[0m'

# ── 项目根目录 ──────────────────────────────────────────────────────────
APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))


def c(text, color=NC):
    """带颜色输出。Windows 不支持 ANSI 时自动降级。"""
    if sys.platform == 'win32':
        return text
    return f'{color}{text}{NC}'


def print_header():
    print(c('╔══════════════════════════════════════════════╗', CYAN))
    print(c('║     滨海小镇 - 手动更新脚本                 ║', CYAN))
    print(c('╚══════════════════════════════════════════════╝', CYAN))
    print()


def check_git():
    """检查 git 是否可用。"""
    try:
        subprocess.run(
            ['git', '--version'],
            capture_output=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        return True
    except Exception:
        return False


def has_uncommitted_changes():
    """检查是否有未提交的本地修改。"""
    result = subprocess.run(
        ['git', 'diff', '--quiet', 'HEAD'],
        cwd=APP_ROOT, capture_output=True,
    )
    return result.returncode != 0


def get_commit_log(from_ref, to_ref, count=20):
    """获取两个引用间的提交记录。"""
    result = subprocess.run(
        ['git', 'log', '--oneline', '-n', str(count), f'{from_ref}..{to_ref}'],
        cwd=APP_ROOT, capture_output=True, timeout=15,
        encoding='utf-8', errors='replace',
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]


def run_update():
    """执行更新主流程。"""
    print_header()

    update_msg = f'项目目录: {APP_ROOT}'
    print(c(update_msg, YELLOW))
    print()

    # ── 检查 git ────────────────────────────────────────────────────────
    if not check_git():
        print(c('[错误] 未检测到 git，请先安装 git', RED))
        print(c('提示: 请手动下载 https://github.com/kute0213/bhxz 的代码替换', YELLOW))
        sys.exit(1)

    os.chdir(APP_ROOT)

    # ── 检查 git 仓库 ──────────────────────────────────────────────────
    if not os.path.isdir(os.path.join(APP_ROOT, '.git')):
        print(c('[错误] 当前目录不是 git 仓库，无法使用此方式更新', RED))
        print(c('提示: 请手动下载 https://github.com/kute0213/bhxz 的代码替换', YELLOW))
        sys.exit(1)

    # ── 处理本地修改 ────────────────────────────────────────────────────
    stashed = False
    if has_uncommitted_changes():
        print(c('[警告] 存在未提交的本地修改：', YELLOW))
        status_result = subprocess.run(
            ['git', 'status', '--short'],
            cwd=APP_ROOT, capture_output=True,
            encoding='utf-8', errors='replace',
        )
        print(status_result.stdout)
        print()
        print(c('未提交的修改可能被覆盖。', YELLOW))
        confirm = input('继续更新？(y/N): ').strip().lower()
        if confirm != 'y':
            print(c('已取消更新', RED))
            sys.exit(0)

        print(c('正在暂存本地修改...', YELLOW))
        subprocess.run(
            ['git', 'stash', '--include-untracked'],
            cwd=APP_ROOT, capture_output=True,
        )
        stashed = True
        print(c('本地修改已暂存，更新后可执行 git stash pop 恢复', YELLOW))

    print()
    print(c('[1/3] 正在获取远程更新...', CYAN))

    # ── 获取远程更新 ────────────────────────────────────────────────────
    fetch_result = subprocess.run(
        ['git', 'fetch', '--all', '--tags', '--force'],
        cwd=APP_ROOT, capture_output=True, timeout=60,
        encoding='utf-8', errors='replace',
    )
    if fetch_result.returncode != 0:
        print(c(f'[错误] git fetch 失败: {fetch_result.stderr.strip()}', RED))
        if stashed:
            subprocess.run(['git', 'stash', 'pop'], cwd=APP_ROOT, capture_output=True)
        sys.exit(1)

    print(c('✓ 远程更新获取成功', GREEN))
    print()

    # ── 查看更新内容 ────────────────────────────────────────────────────
    print(c('[2/3] 更新内容预览：', CYAN))

    before_hash = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=APP_ROOT, capture_output=True,
        encoding='utf-8', errors='replace',
    ).stdout.strip()

    after_hash = subprocess.run(
        ['git', 'rev-parse', 'origin/main'],
        cwd=APP_ROOT, capture_output=True,
        encoding='utf-8', errors='replace',
    ).stdout.strip()

    if before_hash == after_hash:
        print(c('✓ 当前已是最新版本，无需更新', GREEN))
        if stashed:
            subprocess.run(['git', 'stash', 'pop'], cwd=APP_ROOT, capture_output=True)
        sys.exit(0)

    print(f'  当前版本: {c(before_hash[:8], YELLOW)}')
    print(f'  最新版本: {c(after_hash[:8], GREEN)}')
    print()
    print(c('--- 最近提交 ---', YELLOW))

    commits = get_commit_log(before_hash, 'origin/main')
    for commit in commits:
        print(f'  {commit}')
    print()

    # ── 确认更新 ────────────────────────────────────────────────────────
    confirm = input('确认应用以上更新？(Y/n): ').strip().lower()
    if confirm == 'n':
        print(c('已取消更新', YELLOW))
        if stashed:
            subprocess.run(['git', 'stash', 'pop'], cwd=APP_ROOT, capture_output=True)
        sys.exit(0)

    # ── 应用更新 ────────────────────────────────────────────────────────
    print()
    print(c('[3/3] 正在应用更新...', CYAN))

    reset_result = subprocess.run(
        ['git', 'reset', '--hard', 'origin/main'],
        cwd=APP_ROOT, capture_output=True, timeout=30,
        encoding='utf-8', errors='replace',
    )
    if reset_result.returncode != 0:
        print(c(f'[错误] 更新失败: {reset_result.stderr.strip()}', RED))
        print(c('请手动解决冲突', YELLOW))
        sys.exit(1)

    print(c('✓ 代码已更新到最新版本', GREEN))
    print()

    # ── 恢复暂存 ────────────────────────────────────────────────────────
    if stashed:
        print(c('正在恢复本地暂存的修改...', YELLOW))
        subprocess.run(['git', 'stash', 'pop'], cwd=APP_ROOT, capture_output=True)

    # ── 完成 ────────────────────────────────────────────────────────────
    print()
    print(c('╔══════════════════════════════════════════════╗', GREEN))
    print(c('║     更新完成！                                ║', GREEN))
    print(c('╚══════════════════════════════════════════════╝', GREEN))
    print(c('提示: 请重启服务器使新代码生效', YELLOW))
    print(c('提示: 如果遇到依赖变化，请执行: pip install -r requirements.txt', YELLOW))
    print()


if __name__ == '__main__':
    try:
        run_update()
    except KeyboardInterrupt:
        print()
        print(c('已取消更新', RED))
        sys.exit(0)
    except subprocess.TimeoutExpired as e:
        print(c(f'[错误] 操作超时: {e}', RED))
        sys.exit(1)
    except Exception as e:
        print(c(f'[错误] {e}', RED))
        sys.exit(1)