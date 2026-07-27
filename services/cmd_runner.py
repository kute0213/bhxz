"""命令执行服务：实时输出流 + 执行历史。

仅管理员可调用，通过 SSE（Server-Sent Events）流式返回 stdout/stderr。
命令执行结果会记录到 cmd_run_logs 表中。
"""

import os
import subprocess
import shlex
import threading
import time
import datetime
from typing import Iterator

from core.db import get_db


def run_command_stream(command: str, cwd: str = None, timeout: int = 300) -> Iterator[dict]:
    """以流式方式执行命令，逐行 yield 输出。

    Yields 字典：
        { 'type': 'output', 'line': '...' }
        { 'type': 'exit',   'code': 0 }
        { 'type': 'error',  'message': '...' }
    """
    if not command or not command.strip():
        yield {'type': 'error', 'message': '命令不能为空'}
        return

    if cwd is None:
        cwd = os.getcwd()

    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )
    except Exception as e:
        yield {'type': 'error', 'message': f'启动进程失败: {e}'}
        return

    start_time = time.time()
    killed_by_timeout = False

    def _reader():
        try:
            for line in process.stdout:
                yield line.rstrip('\n')
        except Exception:
            pass

    for line in _reader():
        yield {'type': 'output', 'line': line}
        if timeout and (time.time() - start_time) > timeout:
            killed_by_timeout = True
            try:
                process.kill()
            except Exception:
                pass
            break

    try:
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass

    if killed_by_timeout:
        yield {'type': 'error', 'message': f'命令执行超时（>{timeout}秒），已强制终止'}
    else:
        yield {'type': 'exit', 'code': process.returncode}


def run_command_sync(command: str, cwd: str = None, timeout: int = 30,
                     triggered_by: str = 'manual') -> dict:
    """同步执行命令（阻塞），返回完整输出。

    用于不需要实时查看输出的一键命令场景。
    执行结果会异步记录到 cmd_run_logs 表。
    """
    if not command or not command.strip():
        return {'success': False, 'output': '', 'error': '命令不能为空'}

    if cwd is None:
        cwd = os.getcwd()

    started_at = time.time()
    started_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + (result.stderr if result.stderr else '')
        success = result.returncode == 0

        _log_cmd_execution(
            command, output, result.returncode, success,
            triggered_by, started_str, timeout,
        )

        return {
            'success': success,
            'output': output,
            'exit_code': result.returncode,
        }
    except subprocess.TimeoutExpired:
        _log_cmd_execution(
            command, f'执行超时（>{timeout}秒）', -1, False,
            triggered_by, started_str, timeout,
        )
        return {'success': False, 'output': '', 'error': f'执行超时（>{timeout}秒）'}
    except Exception as e:
        _log_cmd_execution(
            command, str(e), -1, False,
            triggered_by, started_str, timeout,
        )
        return {'success': False, 'output': '', 'error': str(e)}


def _log_cmd_execution(command, output, exit_code, success,
                       triggered_by, started_str, timeout):
    """在后台线程中记录命令执行日志，避免阻塞。"""
    def _write():
        conn = None
        try:
            finished = datetime.datetime.now()
            duration = (finished - datetime.datetime.strptime(
                started_str, '%Y-%m-%d %H:%M:%S'
            )).total_seconds()

            if len(output) > 10000:
                output = output[:10000] + '\n...(输出已截断)'

            conn = get_db()
            conn.execute(
                "INSERT INTO cmd_run_logs "
                "(command, output, exit_code, success, triggered_by, "
                " started_at, finished_at, duration_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (command, output, exit_code, success, triggered_by,
                 started_str, finished.strftime('%Y-%m-%d %H:%M:%S'), duration),
            )
            conn.commit()
        except Exception:
            # 仅记录到 stderr，不静默吞掉异常（便于调试连接/SQL 问题）
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    threading.Thread(target=_write, daemon=True).start()
