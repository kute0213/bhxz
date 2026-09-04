"""命令执行服务：实时输出流 + 执行历史。

仅管理员可调用，通过 SSE（Server-Sent Events）流式返回 stdout/stderr。
命令执行结果会记录到 cmd_run_logs 表中。

本模块使用 core/process_manager.ProcessManager 统一处理子进程生命周期，
屏蔽 Windows / Unix 在进程组、信号、终止等方面的差异。
"""

import datetime
import shlex
import subprocess
import threading
import time
from typing import Iterator

from config import APP_ROOT
from core.db import get_db
from services.process_manager import ProcessManager
from services.process_utils import decode_output


def run_command_stream(
    command: str, cwd: str = None, timeout: int = 300
) -> Iterator[dict]:
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

    manager = ProcessManager()
    try:
        cmd_list = shlex.split(command)
    except Exception as e:
        yield {'type': 'error', 'message': f'命令解析失败: {e}'}
        return

    try:
        manager.start(
            cmd_list,
            cwd=cwd,
            shell=False,
            use_process_group=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
    except Exception as e:
        yield {'type': 'error', 'message': f'启动进程失败: {e}'}
        return

    start_time = time.time()
    killed_by_timeout = False

    def _reader():
        proc = manager.get_process()
        if proc is None or proc.stdout is None:
            return
        buf = bytearray()
        while True:
            try:
                chunk = proc.stdout.read(4096)
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
                    if b in (0x0A, 0x0D):
                        nl_idx = i
                        break
                if nl_idx < 0:
                    break
                line_bytes = bytes(buf[:nl_idx])
                del buf[:nl_idx + 1]
                while buf and buf[0] in (0x0A, 0x0D):
                    del buf[0]
                yield decode_output(line_bytes).rstrip('\r\n')

    for line in _reader():
        yield {'type': 'output', 'line': line}
        if timeout and (time.time() - start_time) > timeout:
            killed_by_timeout = True
            manager.kill()
            break

    manager.wait(timeout=3)
    proc = manager.get_process()
    code = proc.returncode if proc else -1
    manager.cleanup()

    if killed_by_timeout:
        yield {'type': 'error', 'message': f'命令执行超时（>{timeout}秒），已强制终止'}
    else:
        yield {'type': 'exit', 'code': code}


def run_command_sync(
    command: str,
    cwd: str = None,
    timeout: int = 30,
    triggered_by: str = 'manual',
) -> dict:
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

    manager = ProcessManager()
    try:
        cmd_list = shlex.split(command)
    except Exception as e:
        _log_cmd_execution(
            command, str(e), -1, False, triggered_by, started_str, timeout
        )
        return {'success': False, 'output': '', 'error': f'命令解析失败: {e}'}

    try:
        manager.start(
            cmd_list,
            cwd=cwd,
            shell=False,
            use_process_group=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except Exception as e:
        _log_cmd_execution(
            command, str(e), -1, False, triggered_by, started_str, timeout
        )
        return {'success': False, 'output': '', 'error': str(e)}

    try:
        return_code = manager.wait(timeout=timeout)
        if return_code is None:
            manager.kill()
            _log_cmd_execution(
                command, f'执行超时（>{timeout}秒）', -1, False,
                triggered_by, started_str, timeout,
            )
            return {'success': False, 'output': '', 'error': f'执行超时（>{timeout}秒）'}

        proc = manager.get_process()
        stdout_text = decode_output(proc.stdout.read()) if proc and proc.stdout else ''
        stderr_text = decode_output(proc.stderr.read()) if proc and proc.stderr else ''
        output = stdout_text + stderr_text
        success = return_code == 0

        _log_cmd_execution(
            command, output, return_code, success,
            triggered_by, started_str, timeout,
        )

        return {
            'success': success,
            'output': output,
            'exit_code': return_code,
        }
    except Exception as e:
        manager.kill()
        _log_cmd_execution(
            command, str(e), -1, False, triggered_by, started_str, timeout
        )
        return {'success': False, 'output': '', 'error': str(e)}
    finally:
        manager.cleanup()


def _log_cmd_execution(
    command, output, exit_code, success,
    triggered_by, started_str, timeout
):
    """在后台线程中记录命令执行日志，避免阻塞。"""
    def _write():
        conn = None
        try:
            finished = datetime.datetime.now()
            duration = (
                finished - datetime.datetime.strptime(
                    started_str, '%Y-%m-%d %H:%M:%S'
                )
            ).total_seconds()

            if len(output) > 10000:
                output = output[:10000] + '\n...(输出已截断)'

            conn = get_db()
            conn.execute(
                "INSERT INTO cmd_run_logs "
                "(command, output, exit_code, success, triggered_by, "
                " started_at, finished_at, duration_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    command, output, exit_code, success, triggered_by,
                    started_str, finished.strftime('%Y-%m-%d %H:%M:%S'),
                    duration,
                ),
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
