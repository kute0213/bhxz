"""跨平台子进程工具：统一处理编码、输出缓冲、环境变量等问题。

本模块从 utils/process.py 迁移到 core/process_utils.py，
作为 core 子进程基础设施的一部分，供 core/process_manager.py、
core/shell.py 及各服务层使用。
"""

import os
import subprocess
import locale


def make_env():
    """构造禁用输出缓冲的环境变量（PYTHONUNBUFFERED、FORCE_COLOR 等）。"""
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['FORCE_COLOR'] = '1'
    return env


def decode_output(data):
    """将 bytes 解码为 str，依次尝试 utf-8 / gbk / cp936 / gb18030 / 系统编码。

    始终包含常见中文编码作为回退，因为即使在 Linux 上，子进程输出也可能
    来自跨平台命令、远程连接输出或 chcp 切换不完全的 cmd.exe 会话。
    """
    if data is None:
        return ''
    if isinstance(data, str):
        return data
    fallbacks = ['utf-8']
    fallbacks.extend(['gbk', 'cp936', 'gb18030'])
    if os.name == 'nt':
        fallbacks.append('mbcs')
    try:
        pref = locale.getpreferredencoding(False)
        if pref and pref.lower() not in ('utf-8', 'utf8') and pref not in fallbacks:
            fallbacks.append(pref)
    except Exception:
        pass
    for enc in fallbacks:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


def popen_kwargs(**overrides):
    """返回跨平台 Popen 通用 kwargs 基础字典（含 env 和 Windows flags）。"""
    kwargs = {'env': make_env()}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    kwargs.update(overrides)
    return kwargs


def run_process(cmd, shell=True, cwd=None, timeout=None):
    """跨平台 subprocess.run 封装，自动处理编码和缓冲。

    Returns:
        dict: {'success': bool, 'stdout': str, 'stderr': str, 'returncode': int}
    """
    if cwd is None:
        from config import APP_ROOT
        cwd = APP_ROOT
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            env=make_env(),
            **({
                'creationflags': subprocess.CREATE_NO_WINDOW
            } if os.name == 'nt' else {}),
        )
        return {
            'success': result.returncode == 0,
            'stdout': decode_output(result.stdout),
            'stderr': decode_output(result.stderr),
            'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'stdout': '', 'stderr': f'执行超时（>{timeout}秒）', 'returncode': -1}
    except Exception as e:
        return {'success': False, 'stdout': '', 'stderr': str(e), 'returncode': -1}
