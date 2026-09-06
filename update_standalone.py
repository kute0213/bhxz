#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备用一键更新脚本 —— 双击运行，自动拉取最新代码、安装依赖、重启服务器。

用法：
  Windows: 直接双击 update_standalone.py
  Linux:   python3 update_standalone.py

注意：本脚本会重置本地所有修改，强制与远程仓库同步。
"""

import os
import sys
import subprocess
import time

# ═══════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════

# 项目根目录（脚本所在目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 远程仓库
REMOTE = 'origin'
BRANCH = 'main'

# 依赖文件
REQUIREMENTS = os.path.join(PROJECT_ROOT, 'requirements.txt')

# 服务器入口
APP_SCRIPT = os.path.join(PROJECT_ROOT, 'app.py')

# pip 超时（秒）
PIP_TIMEOUT = 120


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

def main():
    log('=' * 50)
    log(' 备用更新脚本启动')
    log(f' 项目路径: {PROJECT_ROOT}')
    log(f' 系统平台: {sys.platform}')
    log(f' Python: {sys.executable}')
    log('=' * 50)

    # 1. 切换到项目目录
    os.chdir(PROJECT_ROOT)

    # 2. 检查 Git 是否可用
    log('\n▶ 检查 Git...')
    code, git_version = run('git --version', capture=True, timeout=10)
    if code != 0:
        log('  ✗ Git 不可用，请先安装 Git')
        input('\n按回车键退出...')
        return 1

    # 3. 拉取最新代码（强制覆盖本地修改）
    log('\n▶ 拉取最新代码...')
    run('git fetch --all', timeout=30)
    run(f'git reset --hard {REMOTE}/{BRANCH}', timeout=30)
    run('git clean -fd', timeout=30)

    # 4. 安装/更新依赖
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
        # Windows 下使用 start 命令打开新窗口
        cmd = f'start "bhxz-server" "{python}" "{APP_SCRIPT}"'
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