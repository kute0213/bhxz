"""跨平台 shell 检测与环境构造。

为持久终端会话和命令执行提供统一的 shell 入口，屏蔽 Windows 与 Unix
平台在 shell 路径、启动参数、进程组、编码等方面的差异。
"""

import os
import shutil

from core.process_utils import make_env


def detect_shell():
    """检测当前平台可用的 shell。

    Returns:
        tuple: (shell_args, shell_type, init_commands)
            - shell_args: 可直接传给 subprocess.Popen 的参数列表
            - shell_type: 'cmd' | 'powershell' | 'bash' | 'sh'
            - init_commands: 启动后需依次写入 stdin 的初始化命令字符串列表
    """
    if os.name == 'nt':
        return _detect_windows_shell()
    return _detect_unix_shell()


def _detect_windows_shell():
    """Windows 平台 shell 检测。"""
    powershell = _find_powershell()
    use_powershell = (
        powershell is not None
        and os.environ.get('TERMINAL_SHELL', '').lower() == 'powershell'
    )

    if use_powershell:
        return (
            [
                powershell,
                '-NoProfile',
                '-NoLogo',
                '-ExecutionPolicy', 'Bypass',
                '-NoExit',
                '-Command', '-',
            ],
            'powershell',
            [
                '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n',
                '$OutputEncoding = [System.Text.Encoding]::UTF8\n',
                '$Host.UI.RawUI.WindowTitle = "滨海小镇终端"\n',
            ],
        )

    # 默认使用 cmd.exe，并通过 chcp 切换到 UTF-8 代码页
    return (
        ['cmd.exe', '/k'],
        'cmd',
        ['chcp 65001 >nul\n'],
    )


def _detect_unix_shell():
    """Unix/Linux/macOS 平台 shell 检测。"""
    for shell_path in ('/bin/bash', '/usr/bin/bash'):
        if os.path.isfile(shell_path):
            return (
                [shell_path, '--norc', '--noprofile'],
                'bash',
                [
                    'export TERM=xterm-256color\n',
                    'export PS1="\\u@\\h:\\w\\$ "\n',
                    'export LANG=${LANG:-en_US.UTF-8}\n',
                    'stty -echoctl 2>/dev/null\n',
                ],
            )

    for shell_path in ('/bin/sh', '/usr/bin/sh'):
        if os.path.isfile(shell_path):
            return (
                [shell_path],
                'sh',
                [
                    'export TERM=xterm-256color\n',
                    'export PS1="$ "\n',
                ],
            )

    # 最后回退到 PATH 中任意可用的 sh
    sh = shutil.which('sh') or 'sh'
    return (
        [sh],
        'sh',
        ['export TERM=xterm-256color\n'],
    )


def _find_powershell():
    """查找可用的 PowerShell 可执行文件路径。"""
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    candidates = [
        os.path.join(
            system_root,
            'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'
        ),
        os.path.join(
            system_root,
            'SysWOW64', 'WindowsPowerShell', 'v1.0', 'powershell.exe'
        ),
        shutil.which('powershell'),
        shutil.which('pwsh'),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def get_shell_env():
    """构造适合 shell 子进程的环境变量字典。"""
    env = make_env()
    env.update({
        'HOME': os.path.expanduser('~'),
        'TERM': 'xterm-256color',
        'PYTHONIOENCODING': 'utf-8',
    })
    if os.name == 'nt':
        env.update({
            'PROMPT': '$P$G',
        })
    return env


def is_windows():
    """当前平台是否为 Windows。"""
    return os.name == 'nt'
