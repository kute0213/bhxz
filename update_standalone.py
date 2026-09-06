#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备用一键更新脚本 —— 双击运行，自动拉取最新代码、安装依赖、重启服务器。

用法：
  Windows: 直接双击 update_standalone.py
  Linux:   python3 update_standalone.py

注意：本脚本会重置本地所有修改，强制与远程仓库同步。
如果本地不是 Git 仓库，会自动从 GitHub 下载最新代码并覆盖。
"""

import os
import sys
import shutil
import zipfile
import subprocess
import time
import tempfile
import urllib.request
import urllib.error
import socket
import ssl

# ═══════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════

# 项目根目录（脚本所在目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 远程仓库
GITHUB_REPO = 'kute0213/bhxz'
GITHUB_URL = f'https://github.com/{GITHUB_REPO}'
GITHUB_ARCHIVE = f'{GITHUB_URL}/archive/refs/heads/main.zip'
REMOTE = 'origin'
BRANCH = 'main'

# 国内镜像代理（按优先级，下载失败时自动切换）
MIRROR_PROXIES = [
    ('ghp.ci', 'https://ghp.ci/https://github.com/'),
    ('ghproxy.com', 'https://ghproxy.com/https://github.com/'),
    ('github.moeyy.xyz', 'https://github.moeyy.xyz/https://github.com/'),
    ('slink.ltd', 'https://slink.ltd/https://github.com/'),
]

# 依赖文件
REQUIREMENTS = os.path.join(PROJECT_ROOT, 'requirements.txt')

# 服务器入口
APP_SCRIPT = os.path.join(PROJECT_ROOT, 'app.py')

# pip 超时（秒）
PIP_TIMEOUT = 120

# 下载超时（秒）
DOWNLOAD_TIMEOUT = 60


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

def log(msg):
    """带时间戳的日志输出。"""
    now = time.strftime('%H:%M:%S')
    print(f'[{now}] {msg}')
    sys.stdout.flush()


def run(cmd, cwd=None, timeout=60, capture=False):
    """执行命令并实时输出。

    Returns:
        (returncode, stdout_str) 如果 capture=True
        returncode 如果 capture=False
    """
    cwd = cwd or PROJECT_ROOT
    log(f'$ {cmd}')
    try:
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            encoding='utf-8',
            errors='replace',
        )
        if capture:
            stdout, _ = p.communicate(timeout=timeout)
            print(stdout, end='')
            return p.returncode, stdout.strip()
        p.wait(timeout=timeout)
        return p.returncode
    except subprocess.TimeoutExpired:
        log(f'  ⚠ 命令超时（{timeout}s）')
        return -1
    except Exception as e:
        log(f'  ✗ 命令执行失败: {e}')
        return -1


def find_python():
    """自动查找可用的 Python 解释器。"""
    candidates = []
    if sys.platform == 'win32':
        candidates = [
            sys.executable,
            'python',
            'python3',
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Python', 'Python313', 'python.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Python', 'Python312', 'python.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Python', 'Python311', 'python.exe'),
            'C:\\Python313\\python.exe',
            'C:\\Python312\\python.exe',
        ]
    else:
        candidates = [
            sys.executable,
            'python3',
            'python',
        ]

    for py in candidates:
        if not py:
            continue
        try:
            code, _ = run(f'"{py}" --version', timeout=10, capture=True)
            if code == 0:
                return py
        except Exception:
            continue
    return sys.executable


def wait_for_exit(pid_file=None, process_name='app.py'):
    """等待旧服务器进程退出。

    优先使用 PID 文件，其次按进程名查找。
    """
    pid = None
    if pid_file and os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            log(f'  等待 PID {pid} 退出...')
        except Exception:
            pid = None

    max_wait = 30
    for i in range(max_wait):
        # 按 PID 检查
        if pid:
            if sys.platform == 'win32':
                code, _ = run(f'tasklist /FI "PID eq {pid}" 2>nul | findstr "{pid}"',
                              capture=True, timeout=5)
                if not code == 0:
                    return True
            else:
                code, _ = run(f'kill -0 {pid} 2>/dev/null', capture=True, timeout=5)
                if code != 0:
                    return True

        # 按进程名检查
        if sys.platform == 'win32':
            code, _ = run(f'tasklist /FI "IMAGENAME eq python.exe" 2>nul | findstr "{process_name}"',
                          capture=True, timeout=5)
            if code != 0:
                return True
        else:
            code, _ = run(f'pgrep -f "{process_name}" 2>/dev/null', capture=True, timeout=5)
            if not code == 0:
                return True

        time.sleep(1)

    log('  ⚠ 等待超时，强制继续')
    return False


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

def is_git_repo(path):
    """检查目录是否是一个 Git 仓库。"""
    git_dir = os.path.join(path, '.git')
    return os.path.isdir(git_dir)


def _test_connection(url, timeout=10):
    """快速测试 URL 是否可达，避免下载时长时间卡死。"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, method='HEAD',
            headers={'User-Agent': 'Mozilla/5.0 bhxz-updater'})
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        log(f'    连接成功（HTTP {resp.status}）')
        return True
    except Exception as e:
        log(f'    ⚠ 连接测试失败: {e}')
        return False


def _download_file(url, dest_path, timeout=30):
    """分块下载文件，实时输出进度日志。

    使用 urllib.request.urlopen 分块读取，每下载 2MB 输出一次进度。
    设置超时避免 Windows 下无响应卡死。

    Args:
        url: 下载地址
        dest_path: 本地保存路径
        timeout: 连接超时（秒）

    Returns:
        True 成功 / False 失败
    """
    try:
        # 创建不验证 SSL 证书的上下文（解决 Windows 上某些代理的证书问题）
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) bhxz-updater',
        })
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)

        total = resp.length
        downloaded = 0
        chunk_size = 64 * 1024  # 64KB
        next_report = 2 * 1024 * 1024  # 每 2MB 汇报一次

        with open(dest_path, 'wb') as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                if downloaded >= next_report:
                    if total:
                        pct = downloaded * 100 // total
                        log(f'    下载进度: {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)')
                    else:
                        log(f'    已下载: {downloaded // 1024 // 1024}MB')
                    next_report += 2 * 1024 * 1024

        if total:
            log(f'    下载完成: {total // 1024 // 1024}MB')
        else:
            log(f'    下载完成: {downloaded // 1024 // 1024}MB')
        return True

    except urllib.error.URLError as e:
        log(f'  ✗ 网络错误: {e.reason}')
        return False
    except socket.timeout:
        log(f'  ✗ 连接超时（{timeout}s）')
        return False
    except Exception as e:
        log(f'  ✗ 下载异常: {e}')
        return False


def download_and_extract(url, dest, name=None):
    """从指定 URL 下载 ZIP 归档并解压到目标目录。

    支持镜像代理自动切换：先尝试直连，失败后依次尝试国内镜像代理。
    使用分块下载 + 实时进度日志，避免 Windows 下无反馈卡死。

    Args:
        url: 原始下载地址
        dest: 目标目录
        name: 显示名称（用于日志）
    """
    name = name or 'GitHub'

    # 构建 URL 列表：直连 + 镜像代理
    urls = [url]
    for proxy_name, proxy_base in MIRROR_PROXIES:
        if url.startswith('https://github.com/'):
            proxy_url = proxy_base + url[len('https://github.com/'):]
            urls.append((proxy_url, proxy_name))

    last_error = None
    for entry in urls:
        if isinstance(entry, tuple):
            current_url, mirror_name = entry
            log(f'  尝试镜像 [{mirror_name}]')
        else:
            current_url = entry
            log(f'  尝试直连')

        # 先快速测试连接
        if not _test_connection(current_url, timeout=DOWNLOAD_TIMEOUT):
            log(f'  ⚠ 跳过不可达源')
            continue

        # 分块下载
        try:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                zip_path = tmp.name
            if not _download_file(current_url, zip_path, timeout=DOWNLOAD_TIMEOUT):
                try:
                    os.unlink(zip_path)
                except Exception:
                    pass
                continue
        except Exception as e:
            log(f'  ✗ 下载失败: {e}')
            try:
                os.unlink(zip_path)
            except Exception:
                pass
            continue

        # 解压
        log(f'  解压中...')
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                extract_dir = tempfile.mkdtemp()
                zf.extractall(extract_dir)

            # 找到解压后的根目录（通常是 bhxz-main 或类似）
            items = [i for i in os.listdir(extract_dir)
                     if os.path.isdir(os.path.join(extract_dir, i))]
            src = os.path.join(extract_dir, items[0]) if items else extract_dir

            # 复制到目标目录
            count = 0
            for item in os.listdir(src):
                s = os.path.join(src, item)
                d = os.path.join(dest, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
                count += 1
            log(f'    已覆盖 {count} 个文件/目录')

            shutil.rmtree(extract_dir, ignore_errors=True)
            os.unlink(zip_path)
            return True
        except Exception as e:
            log(f'  ✗ 解压失败: {e}')
            try:
                os.unlink(zip_path)
            except Exception:
                pass
            continue

    log(f'  ✗ 所有下载方式均失败（共尝试 {len(urls)} 个源）')
    return False


def pull_code():
    """拉取最新代码。

    如果本地是 Git 仓库，使用 git 强制同步。
    否则从 GitHub 下载 ZIP 归档并覆盖本地文件（自动使用国内镜像加速）。
    """
    if is_git_repo(PROJECT_ROOT):
        log('  本地是 Git 仓库，使用 git 同步')
        code = run('git fetch --all', timeout=30)
        if code != 0:
            log('  ⚠ git fetch 失败，尝试通过国内镜像下载覆盖')
            return download_and_extract(GITHUB_ARCHIVE, PROJECT_ROOT)
        run(f'git reset --hard {REMOTE}/{BRANCH}', timeout=30)
        run('git clean -fd', timeout=30)
        return True

    log('  本地不是 Git 仓库，从 GitHub 下载最新代码（自动使用国内镜像加速）')
    return download_and_extract(GITHUB_ARCHIVE, PROJECT_ROOT)


def main():
    # 命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='BHXZ 备用更新脚本')
    parser.add_argument('--timeout', type=int, default=DOWNLOAD_TIMEOUT,
                        help=f'下载超时秒数（默认 {DOWNLOAD_TIMEOUT}s，Windows 网络差可适当增大）')
    args = parser.parse_args()

    # 设置全局 socket 超时，防止任何网络操作无限制卡死
    socket.setdefaulttimeout(args.timeout)
    global DOWNLOAD_TIMEOUT
    DOWNLOAD_TIMEOUT = args.timeout

    log('=' * 50)
    log(' 备用更新脚本启动')
    log(f' 项目路径: {PROJECT_ROOT}')
    log(f' 系统平台: {sys.platform}')
    log(f' Python: {sys.executable}')
    log(f' 下载超时: {DOWNLOAD_TIMEOUT}s')
    log('=' * 50)

    # 1. 切换到项目目录
    os.chdir(PROJECT_ROOT)

    # 2. 拉取最新代码
    log('\n▶ 拉取最新代码...')
    if not pull_code():
        log('  ✗ 代码拉取失败，终止更新')
        input('\n按回车键退出...')
        return 1

    # 3. 安装/更新依赖
    log('\n▶ 安装依赖...')
    python = find_python()
    log(f'  使用 Python: {python}')

    if os.path.exists(REQUIREMENTS):
        code = run(f'"{python}" -m pip install -r "{REQUIREMENTS}" --upgrade',
                   timeout=PIP_TIMEOUT)
        if code != 0:
            log('  ⚠ pip 安装失败，尝试镜像源...')
            code = run(
                f'"{python}" -m pip install -r "{REQUIREMENTS}" --upgrade '
                f'-i https://pypi.tuna.tsinghua.edu.cn/simple',
                timeout=PIP_TIMEOUT,
            )
    else:
        log('  ⚠ requirements.txt 不存在，跳过')

    # 5. 停止旧服务器
    log('\n▶ 停止旧服务器...')
    pid_file = os.path.join(PROJECT_ROOT, 'app.pid')
    wait_for_exit(pid_file)

    # 6. 启动新服务器
    log('\n▶ 启动新服务器...')
    if sys.platform == 'win32':
        # Windows 下使用 start 命令打开新窗口，增加数据库超时
        cmd = f'start "bhxz-server" "{python}" "{APP_SCRIPT}" --db-timeout 60'
        subprocess.Popen(cmd, cwd=PROJECT_ROOT, shell=True)
    else:
        # Linux 下使用 nohup 后台运行
        cmd = f'nohup "{python}" "{APP_SCRIPT}" > /dev/null 2>&1 &'
        run(cmd)

    # 7. 等待服务器启动
    log('\n▶ 等待服务器启动...')
    time.sleep(5)

    # 检查是否启动成功
    health_url = 'http://localhost:5000/health'
    if sys.platform != 'win32':
        code, _ = run(f'curl -s -o /dev/null -w "%{{http_code}}" "{health_url}"',
                      capture=True, timeout=10)
        if code == 200:
            log('  ✓ 服务器启动成功')
        else:
            log('  ⚠ 服务器可能未完全启动，请手动检查')

    log('\n' + '=' * 50)
    log(' ✓ 更新完成！')
    log('=' * 50)

    if sys.platform == 'win32':
        # Windows 下等待用户查看结果
        log('\n服务器已在后台启动，本窗口可安全关闭。')
        input('\n按回车键退出...')

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log('\n 用户中断')
        sys.exit(1)
    except Exception as e:
        log(f'\n  ✗ 脚本异常: {e}')
        import traceback
        traceback.print_exc()
        input('\n按回车键退出...')
        sys.exit(1)