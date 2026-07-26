"""独立子进程执行器。

使用 multiprocessing 启动独立 Python 子进程执行脚本：
- 父进程通过 multiprocessing.Pipe 与子进程通信
- 父进程从管道读取事件并 yield 给调用方
- 超时后向子进程发送 terminate() 强制终止
- 支持 abort() 强制终止
"""

import os
import sys
import time
import threading
import multiprocessing

from config import SCRIPT_DEFAULT_TIMEOUT, SCRIPT_MAX_TIMEOUT, SCRIPT_MAX_LOOP_ITER

from services.miniscript.runner import run_script


class ScriptExecutor:
    """脚本执行器，管理子进程执行。"""

    def __init__(self):
        """初始化执行器，维护当前执行的子进程。"""
        self._current_process = None
        self._parent_pipe = None
        self._abort_lock = threading.Lock()
        self._abort_requested = False
        self._start_time = None
        self._timeout = None

    def execute(self, code, interactive=True, timeout=None):
        """执行脚本，返回生成器，yield (event_type, data) 元组。

        Args:
            code: Python 脚本代码字符串
            interactive: True=交互模式，False=定时模式
            timeout: 执行超时秒数，None 用默认值

        Yields:
            (event_type, data) 元组，如 ('output', {'text': 'hello'})

        交互事件处理：
            当 yield 出 ('prompt', {...}) 或 ('confirm', {...}) 事件时，
            调用方可通过 generator.send(response) 将用户响应回传给执行器，
            执行器会将其转发给子进程。若调用方未调用 send()（如使用 for 循环），
            则 response 为 None，脚本会收到 None 作为交互结果。
        """
        # 1. 确定超时
        if timeout is None:
            timeout = SCRIPT_DEFAULT_TIMEOUT
        timeout = min(int(timeout), SCRIPT_MAX_TIMEOUT)
        if timeout <= 0:
            timeout = SCRIPT_DEFAULT_TIMEOUT

        max_loop_iter = SCRIPT_MAX_LOOP_ITER

        # 2. 创建管道与子进程
        parent_conn, child_conn = multiprocessing.Pipe()
        proc = multiprocessing.Process(
            target=run_script,
            args=(code, child_conn, interactive, timeout, max_loop_iter),
            daemon=True,
        )

        with self._abort_lock:
            self._abort_requested = False
            self._current_process = proc
            self._parent_pipe = parent_conn
            self._start_time = time.time()
            self._timeout = timeout

        # 启动子进程
        try:
            proc.start()
        except Exception as e:
            yield ('error', {'message': f'启动子进程失败: {e}'})
            yield ('done', {})
            # 关闭未使用的子进程端管道，再统一清理
            try:
                child_conn.close()
            except Exception:
                pass
            self._cleanup()
            return

        # 父进程不需要子进程端
        try:
            child_conn.close()
        except Exception:
            pass

        # 3. 主事件循环
        try:
            while True:
                # 检查终止请求
                with self._abort_lock:
                    if self._abort_requested:
                        yield ('error', {'message': '脚本执行被强制终止'})
                        break

                # 检查超时
                if self._timeout and self._start_time:
                    elapsed = time.time() - self._start_time
                    if elapsed > self._timeout:
                        self._terminate_process()
                        yield ('error', {
                            'message': f'脚本执行超时（>{self._timeout}秒），已强制终止'
                        })
                        break

                # 等待管道消息（带超时，便于周期性检查 abort/timeout）
                try:
                    if not parent_conn.poll(0.1):
                        continue
                    msg = parent_conn.recv()
                except (EOFError, OSError):
                    # 子进程管道已关闭：可能是正常退出、被 abort 或异常崩溃
                    with self._abort_lock:
                        aborted = self._abort_requested
                    if aborted:
                        yield ('error', {'message': '脚本执行被强制终止'})
                    else:
                        if proc.is_alive():
                            self._terminate_process()
                        yield ('error', {'message': '子进程异常退出'})
                    break
                except Exception as e:
                    yield ('error', {'message': f'读取子进程消息失败: {e}'})
                    break

                # 处理消息
                if not isinstance(msg, dict):
                    continue

                msg_type = msg.get('type')

                if msg_type == 'event':
                    event_type = msg.get('event_type')
                    data = msg.get('data', {})

                    # yield 事件给调用方，并接收可能的响应
                    response = yield (event_type, data)

                    # 交互事件需要将响应转发给子进程
                    if event_type in ('prompt', 'confirm'):
                        try:
                            parent_conn.send({
                                'type': 'response',
                                'value': response,
                            })
                        except Exception:
                            pass

                elif msg_type == 'done':
                    # 子进程执行完成
                    break

                else:
                    # 未知消息类型，忽略
                    continue

        finally:
            self._cleanup()

    def abort(self):
        """强制终止当前执行的脚本子进程。"""
        with self._abort_lock:
            self._abort_requested = True
        self._terminate_process()

    def is_running(self):
        """是否有脚本正在执行。"""
        with self._abort_lock:
            proc = self._current_process
            if proc is None:
                return False
            return proc.is_alive()

    # -----------------------------------------------------------------
    # 内部辅助方法
    # -----------------------------------------------------------------

    def _terminate_process(self):
        """终止当前子进程。

        采用「SIGTERM → 等待 → SIGKILL → 等待」阶梯式策略，
        确保无论子进程是否响应都能被回收，避免僵尸进程。
        """
        with self._abort_lock:
            proc = self._current_process
            pipe = self._parent_pipe

        if proc is not None:
            try:
                if proc.is_alive():
                    # 第一阶段：SIGTERM 优雅终止
                    try:
                        proc.terminate()
                        proc.join(timeout=2)
                    except Exception:
                        pass
                    # 第二阶段：仍在运行则 SIGKILL 强制结束
                    if proc.is_alive():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        try:
                            proc.join(timeout=1)
                        except Exception:
                            pass
                # 确保进程资源被回收（即使已退出也要 join 一次）
                try:
                    proc.join(timeout=0.5)
                except Exception:
                    pass
            except Exception:
                pass

        # 关闭父端管道以解除可能阻塞的 recv()
        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                pass

    def _cleanup(self):
        """清理执行器状态。

        在任何异常路径下都确保：
          1. 子进程被终止并 join（避免僵尸）
          2. 父端管道被关闭（避免 fd 泄漏）
          3. 内部状态被复位（避免影响下一次执行）
        """
        with self._abort_lock:
            proc = self._current_process
            pipe = self._parent_pipe
            self._current_process = None
            self._parent_pipe = None
            self._start_time = None
            self._timeout = None

        if proc is not None:
            try:
                if proc.is_alive():
                    try:
                        proc.terminate()
                        proc.join(timeout=1)
                    except Exception:
                        pass
                    if proc.is_alive():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        try:
                            proc.join(timeout=1)
                        except Exception:
                            pass
                else:
                    # 已退出：仍 join 一次以回收资源
                    try:
                        proc.join(timeout=0.5)
                    except Exception:
                        pass
            except Exception:
                pass

        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                pass
