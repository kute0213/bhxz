"""命令执行服务：实时输出流 + 执行历史。

仅管理员可调用，通过 SSE（Server-Sent Events）流式返回 stdout/stderr。
命令执行结果会记录到 cmd_run_logs 表中。
"""

import os
import subprocess
import threading
import time
import datetime
from typing import Iterator

from core.db import get_db
from config import APP_ROOT
from utils.process import decode_output, make_env


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
        cwd = APP_ROOT

    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=make_env(),
            **({
                'creationflags': subprocess.CREATE_NO_WINDOW
            } if os.name == 'nt' else {}),
        )
    except Exception as e:
        yield {'type': 'error', 'message': f'启动进程失败: {e}'}
        return

    start_time = time.time()
    killed_by_timeout = False

    def _reader():
        buf = bytearray()
        stdout = process.stdout
        while True:
            try:
                chunk = stdout.read(4096)
            except Exception:
                if buf:
                    yield decode_output(bytes(buf)).rstrip('\r\n')
                break
            if not chunk:
                if buf:
                    yield decode_output(bytes(buf)).rstrip('\r\n')
                break
            buf.extend(chunk)
            while True:
                nl_idx = -1
                for i, b in enumerate(buf):
                    if b in (0x0a, 0x0d):
                        nl_idx = i
                        break
                if nl_idx < 0:
                    break
                line_bytes = bytes(buf[:nl_idx])
                del buf[:nl_idx + 1]
                while buf and buf[0] in (0x0a, 0x0d):
                    del buf[0]
                yield decode_output(line_bytes).rstrip('\r\n')

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
        cwd = APP_ROOT

    started_at = time.time()
    started_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            env=make_env(),
            **({
                'creationflags': subprocess.CREATE_NO_WINDOW
            } if os.name == 'nt' else {}),
        )
        stdout_text = decode_output(result.stdout) if result.stdout else ''
        stderr_text = decode_output(result.stderr) if result.stderr else ''
        output = stdout_text + stderr_text
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
