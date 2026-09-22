#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滨海小镇 - 一键更新脚本（跨平台）

放置于项目根目录，双击或 `python update.py` 即可使用。
自动检测最佳 GitHub 源，一键拉取最新代码。
不会自动重启服务器，更新完成后需手动重启。

用法:
    python update.py          # 普通模式
    python update.py --yes    # 静默模式，跳过确认
"""

import os
import sys
import json
import time
import shutil
import signal
import zipfile
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'kute0213/bhxz'
GITHUB_BRANCH = 'main'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/branches/{GITHUB_BRANCH}'
GITHUB_ARCHIVE = f'https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip'

# 镜像源列表（按优先级排列）
MIRRORS = [
    ('github.com', 'https://github.com/'),
    ('ghp.ci', 'https://ghp.ci/https://github.com/'),
    ('ghproxy.net', 'https://ghproxy.net/https://github.com/'),
    ('mirror.ghproxy.com', 'https://mirror.ghproxy.com/https://github.com/'),
    ('ghfast.top', 'https://ghfast.top/https://github.com/'),
    ('github.moeyy.xyz', 'https://github.moeyy.xyz/https://github.com/'),
    ('slink.ltd', 'https://slink.ltd/https://github.com/'),
    ('gh.ddlc.top', 'https://gh.ddlc.top/https://github.com/'),
    ('gh.h233.eu.org', 'https://gh.h233.eu.org/https://github.com/'),
    ('ghproxy.1888866.xyz', 'https://ghproxy.1888866.xyz/https://github.com/'),
    ('hub.gitmirror.com', 'https://hub.gitmirror.com/https://github.com/'),
    ('gh-proxy.net', 'https://gh-proxy.net/https://github.com/'),
    ('github.boki.moe', 'https://github.boki.moe/https://github.com/'),
    ('gh.llkk.cc', 'https://gh.llkk.cc/https://github.com/'),
    ('kkgithub.com', 'https://kkgithub.com/https://github.com/'),
]
REQUIREMENTS_FILE = os.path.join(PROJECT_ROOT, 'requirements.txt')

# ── 颜色（Windows 兼容） ──────────────────────────────────────────────
if sys.platform == 'win32':
    # Windows 10+ 支持 ANSI，但旧版 cmd 不支持
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
CYAN = '\033[0;36m'
RED = '\033[0;31m'
NC = '\033[0m'


# ── 工具函数 ─────────────────────────────────────────────────────────

def log(msg, color=NC):
    """带颜色和时间的日志输出。"""
    now = datetime.now().strftime('%H:%M:%S')
    text = f'[{now}] {msg}'
    if color and sys.platform != 'win32':
        text = f'{color}{text}{NC}'
    print(text)
    sys.stdout.flush()


def run_cmd(cmd, cwd=None, timeout=60, capture=False):
    """执行系统命令。

    Returns:
        capture=False: returncode
        capture=True: (returncode, stdout)
    """
    cwd = cwd or PROJECT_ROOT
    try:
        p = subprocess.Popen(
            cmd if isinstance(cmd, list) else cmd,
            cwd=cwd, shell=isinstance(cmd, str),
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            encoding='utf-8', errors='replace',
        )
        if capture:
            out, _ = p.communicate(timeout=timeout)
            return p.returncode, (out or '').strip()
        p.wait(timeout=timeout)
        return p.returncode
    except subprocess.TimeoutExpired:
        return -1
    except Exception:
        return -1


def urlopen_with_timeout(url, timeout=15):
    """带超时的 URL 打开。"""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; BHXZ-Updater/1.0)',
    })
    return urllib.request.urlopen(req, timeout=timeout)


def check_proxy(mirror_name, mirror_url, results, index):
    """并发检测镜像是否可用，记录延迟（毫秒）。"""
    test_url = f'{mirror_url}{GITHUB_REPO}'
    try:
        start = time.time()
        resp = urlopen_with_timeout(test_url, timeout=8)
        elapsed = int((time.time() - start) * 1000)
        results[index] = (elapsed, mirror_name, mirror_url)
        resp.close()
    except Exception:
        results[index] = None


def find_best_mirror():
    """并发检测所有镜像，返回延迟最低的可用源。"""
    log('正在检测 GitHub 镜像源连通性...', CYAN)
    results = [None] * len(MIRRORS)
    threads = []

    for i, (name, url) in enumerate(MIRRORS):
        t = threading.Thread(target=check_proxy, args=(name, url, results, i))
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=10)

    # 过滤可用镜像，按延迟排序
    available = [r for r in results if r is not None]
    available.sort(key=lambda x: x[0])

    if not available:
        log('所有镜像源均不可用！', RED)
        return []

    best = available[0]
    log(f'最佳源: {best[1]} ({best[0]}ms)', GREEN)
    if len(available) > 1:
        log(f'备用源: {", ".join(a[1] for a in available[1:4])} ({", ".join(f"{a[0]}ms" for a in available[1:4])})', YELLOW)
    # 返回全部可用镜像列表（按延迟升序），供下载失败时回退
    return available


def get_git_head():
    """获取当前 git HEAD。"""
    code, out = run_cmd('git rev-parse HEAD', capture=True)
    if code != 0:
        return None
    return out.strip()


def get_git_remote_head():
    """获取远程最新 HEAD。"""
    code, out = run_cmd(f'git ls-remote origin HEAD', capture=True, timeout=30)
    if code != 0:
        return None
    return out.split()[0] if out else None


def has_git_changes():
    """检查是否有未提交修改。"""
    code = run_cmd('git diff --quiet HEAD')
    return code != 0


def has_stashed_changes():
    """检查是否有暂存修改。"""
    code, out = run_cmd('git stash list', capture=True)
    return bool(out.strip())


def get_recent_commits(count=20):
    """获取 recent commits 的简短日志。"""
    code, out = run_cmd(f'git log --oneline -{count} origin/main', capture=True)
    if code != 0:
        return []
    return [line for line in out.split('\n') if line.strip()]


def install_requirements():
    """安装/更新 Python 依赖。"""
    if not os.path.isfile(REQUIREMENTS_FILE):
        return
    log('正在检查 Python 依赖...', CYAN)
    code = run_cmd(
        f'"{sys.executable}" -m pip install -r "{REQUIREMENTS_FILE}" --quiet',
        timeout=120,
    )
    if code == 0:
        log('依赖检查完成', GREEN)
    else:
        log('依赖安装可能有警告（不影响核心功能）', YELLOW)


def update_via_git(skip_confirm=False):
    """通过 git 从 GitHub 更新。"""
    log(f'项目目录: {PROJECT_ROOT}')
    log(f'仓库: {GITHUB_REPO}')

    before_hash = get_git_head()
    log(f'当前版本: {before_hash[:8] if before_hash else "未知"}', YELLOW)

    # 1. 暂存本地修改
    stashed = False
    if has_git_changes():
        log('检测到本地未提交修改:', YELLOW)
        code, out = run_cmd('git status --short', capture=True)
        for line in out.split('\n')[:20]:
            if line.strip():
                print(f'  {line}')
        log('将暂存这些修改，更新后恢复', YELLOW)
        run_cmd('git stash --include-untracked', timeout=30)
        stashed = True

    # 2. 获取远程更新
    log('正在获取远程更新...', CYAN)
    code = run_cmd('git fetch --all --tags --force', timeout=60)
    if code != 0:
        log('git fetch 失败，请检查网络连接', RED)
        if stashed:
            run_cmd('git stash pop')
        return False

    # 3. 检查是否有更新
    after_hash = get_git_head()  # fetch 不会改变 HEAD
    remote_hash = get_git_remote_head()
    if remote_hash and remote_hash == before_hash:
        log('当前已是最新版本，无需更新', GREEN)
        if stashed:
            run_cmd('git stash pop')
        return True

    # 4. 预览提交
    log('更新内容预览:', CYAN)
    log(f'最新版本: {remote_hash[:8] if remote_hash else "未知"}', GREEN)
    print()
    if before_hash:
        code, out = run_cmd(f'git log --oneline {before_hash}..origin/main', capture=True)
        if out:
            for line in out.split('\n')[:30]:
                print(f'  {line}')
            print()

    # 5. 确认
    if not skip_confirm:
        print()
        confirm = input('确认应用以上更新？(Y/n): ').strip().lower()
        if confirm == 'n':
            log('已取消更新', YELLOW)
            if stashed:
                run_cmd('git stash pop')
            return True

    # 6. 应用更新
    log('正在应用更新...', CYAN)
    code = run_cmd('git reset --hard origin/main', timeout=30)
    if code != 0:
        log('更新失败！', RED)
        return False

    log('代码已更新到最新版本', GREEN)

    # 7. 恢复暂存
    if stashed:
        log('正在恢复本地暂存的修改...', YELLOW)
        run_cmd('git stash pop')

    return True


def _build_archive_urls(base_url, repo, branch):
    """为一个镜像构造所有可能的归档下载 URL 列表。

    不同镜像对归档 URL 格式的支持不同，全部尝试一遍。
    codeload.github.com 是 GitHub 官方归档下载端点，通过代理成功率最高。
    """
    urls = []
    # 格式 1：标准 archive URL（github.com 直连 + 部分代理支持）
    urls.append(f'{base_url}{repo}/archive/refs/heads/{branch}.zip')

    if base_url == 'https://github.com/':
        # 官方直连：直接使用 codeload 端点
        urls.append(f'https://codeload.github.com/{repo}/zip/refs/heads/{branch}')
    else:
        # 代理镜像：base_url 形如 'https://gh-proxy.net/https://github.com/'
        # 提取代理域名前缀（第一个 https:// 到第二个 https:// 之间的部分）
        parts = base_url.split('https://', 2)
        if len(parts) >= 3:
            proxy_domain = parts[1]  # e.g. 'gh-proxy.net/'
            # 格式 2：通过代理访问 codeload.github.com 归档端点
            urls.append(f'https://{proxy_domain}https://codeload.github.com/{repo}/zip/refs/heads/{branch}')
    return urls


def _try_download_zip(archive_url, zip_path):
    """尝试下载 ZIP 压缩包并校验内容合法性。

    校验项：HTTP 状态码 200、文件非空、ZIP 魔数为 PK。
    Content-Type 不严格校验（部分代理对 zip 返回 text/html），以魔数为准。
    返回 (success: bool, error_msg: str)。
    """
    try:
        resp = urlopen_with_timeout(archive_url, timeout=120)
    except Exception as e:
        return False, f'连接失败: {e}'

    try:
        code = resp.getcode()
        if code != 200:
            return False, f'HTTP {code}'

        total_size = int(resp.headers.get('Content-Length', 0))
        downloaded = 0
        chunk_size = 8192

        with open(zip_path, 'wb') as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = min(100, int(downloaded * 100 / total_size))
                    bar = '█' * (pct // 4) + '░' * (25 - pct // 4)
                    print(f'\r  下载中: |{bar}| {pct}% ({downloaded // 1024}KB / {total_size // 1024}KB)', end='')
                else:
                    print(f'\r  下载中: {downloaded // 1024}KB', end='')
                sys.stdout.flush()
        print()
    finally:
        resp.close()

    if not os.path.isfile(zip_path) or os.path.getsize(zip_path) == 0:
        return False, '下载文件为空'

    # 校验 ZIP 魔数（前 4 字节应为 PK\x03\x04 或空档案 PK\x05\x06）
    with open(zip_path, 'rb') as f:
        magic = f.read(4)
    if magic[:2] != b'PK':
        # 可能是 HTML 错误页，读取前 100 字节用于调试
        with open(zip_path, 'rb') as f:
            preview = f.read(100)
        return False, f'非 ZIP 内容（前4字节: {magic!r}，镜像返回错误页）'

    return True, ''


def update_via_download(mirrors, skip_confirm=False):
    """通过下载 zip 压缩包更新（非 git 仓库时使用）。

    mirrors: 镜像列表 [(ms, name, base_url), ...]，按延迟升序排列。
    对每个镜像尝试多种归档 URL 格式（archive / codeload），全部失败再换下一个镜像。
    所有镜像都失败才返回 False。
    """
    if not skip_confirm:
        print()
        confirm = input('当前不是 git 仓库，将通过下载覆盖方式更新。确认？(Y/n): ').strip().lower()
        if confirm == 'n':
            log('已取消更新', YELLOW)
            return True

    if not mirrors:
        log('无可用镜像源', RED)
        return False

    log('正在从 GitHub 下载最新代码...', CYAN)
    tmp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
    zip_path = os.path.join(tmp_dir, 'update.zip')

    # 分支回退列表：先尝试配置的分支，再尝试常见分支名
    branches = [GITHUB_BRANCH]
    for b in ('main', 'master'):
        if b not in branches:
            branches.append(b)

    try:
        # 逐个镜像 × 逐个分支 × 逐个 URL 格式 尝试
        success = False
        for i, (ms, name, base_url) in enumerate(mirrors):
            log(f'尝试镜像 [{i+1}/{len(mirrors)}]: {name} ({ms}ms)', CYAN)

            mirror_ok = False
            for branch in branches:
                urls = _build_archive_urls(base_url, GITHUB_REPO, branch)
                for j, url in enumerate(urls):
                    ok, err = _try_download_zip(url, zip_path)
                    if not ok:
                        log(f'  [{branch} / 格式{j+1}] 失败: {err}', YELLOW)
                        continue

                    # 完整性校验：zipfile 能否正常打开 + CRC 校验
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            bad_file = zf.testzip()
                        if bad_file is not None:
                            log(f'  [{branch} / 格式{j+1}] ZIP 完整性校验失败: {bad_file}', YELLOW)
                            continue
                    except zipfile.BadZipFile as e:
                        log(f'  [{branch} / 格式{j+1}] ZIP 损坏: {e}', YELLOW)
                        continue

                    mirror_ok = True
                    success = True
                    log(f'  下载成功，使用镜像: {name} (分支: {branch})', GREEN)
                    break
                if mirror_ok:
                    break

            if success:
                break

        if not success:
            log('所有镜像源与 URL 格式均失败，请检查网络后重试', RED)
            return False

        # 解压
        log('正在解压...', CYAN)
        extract_dir = os.path.join(tmp_dir, 'extracted')
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # zip 内容在 "bhxz-{branch}/" 目录下（分支名可能不同）
        src_dirs = [d for d in os.listdir(extract_dir) if d.startswith('bhxz-')]
        if not src_dirs:
            # 部分镜像解压后直接是项目根目录，没有外层文件夹
            if 'app.py' in os.listdir(extract_dir):
                src_dir = extract_dir
            else:
                raise Exception('解压后未找到项目目录')
        else:
            src_dir = os.path.join(extract_dir, src_dirs[0])

        # 排除文件列表
        exclude = {
            'db', 'backups', 'uploads', 'ssl', '.env',
            '.git', '__pycache__', '*.pyc', '.DS_Store',
        }

        # 复制文件
        log('正在覆盖文件...', CYAN)
        for item in os.listdir(src_dir):
            if item in exclude:
                continue
            src_path = os.path.join(src_dir, item)
            dst_path = os.path.join(PROJECT_ROOT, item)
            if os.path.isdir(src_path):
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path, ignore_errors=True)
                shutil.copytree(src_path, dst_path, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                shutil.copy2(src_path, dst_path)

        log('代码文件已覆盖完成', GREEN)
        return True

    except Exception as e:
        log(f'下载更新失败: {e}', RED)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_update():
    """执行更新主流程。"""
    print()
    log('╔══════════════════════════════════════════════╗', CYAN)
    log('║     滨海小镇 - 一键更新脚本                   ║', CYAN)
    log('╚══════════════════════════════════════════════╝', CYAN)
    print()

    # 解析参数
    skip_confirm = '--yes' in sys.argv or '-y' in sys.argv

    # 检测可用镜像（返回全部可用镜像列表，按延迟升序）
    mirrors = find_best_mirror()
    if not mirrors:
        log('无法连接到 GitHub，请检查网络后重试', RED)
        return False

    # 统一使用 ZIP 下载方式（即使有 Git 也更稳定）
    success = update_via_download(mirrors, skip_confirm)

    if not success:
        log('更新失败！请检查后重试', RED)
        return False

    # 安装依赖
    print()
    install_requirements()

    # 完成
    print()
    log('╔══════════════════════════════════════════════╗', GREEN)
    log('║     更新完成！                               ║', GREEN)
    log('╚══════════════════════════════════════════════╝', GREEN)
    log('提示: 请手动重启服务器使新代码生效', YELLOW)
    log('提示: 如果遇到依赖变化，请执行: pip install -r requirements.txt', YELLOW)
    print()

    return True


if __name__ == '__main__':
    try:
        success = run_update()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print()
        log('已取消更新', YELLOW)
        sys.exit(0)
    except Exception as e:
        log(f'更新失败: {e}', RED)
        import traceback
        traceback.print_exc()
        sys.exit(1)