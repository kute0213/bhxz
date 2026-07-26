"""子进程入口。

被 executor.py 通过 multiprocessing 启动。负责在子进程中：
- 创建 output_callback 函数，通过 pipe_conn 发送事件给父进程
- 对于 prompt/confirm 交互事件，发送请求后通过 pipe_conn 等待父进程响应
- 创建 builtins 字典并注入到脚本全局命名空间
- 使用 exec() 执行脚本代码
- 捕获所有异常，发送 ('error', {'message': '...'}) 事件
- 执行完成后发送 ('done', {}) 事件
"""

import os
import sys
import time
import signal
import traceback

# 确保工作目录在 sys.path 中（子进程可能需要重新添加）
_WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _WORKSPACE not in sys.path:
    sys.path.insert(0, _WORKSPACE)

from services.miniscript.builtins import create_builtins


# ---------------------------------------------------------------------------
# 管道通信协议
# ---------------------------------------------------------------------------

# 父 -> 子：{'type': 'response', 'value': ...}      用户对 prompt/confirm 的响应
# 父 -> 子：{'type': 'abort'}                       终止信号
# 子 -> 父：{'type': 'event', 'event_type': '...', 'data': {...}}  事件
# 子 -> 父：{'type': 'done'}                        执行完成


def _send_event(pipe_conn, event_type, data):
    """向父进程发送一个事件。"""
    try:
        pipe_conn.send({'type': 'event', 'event_type': event_type, 'data': data})
    except Exception:
        # 管道可能已关闭（父进程提前断开），忽略
        pass


def _send_done(pipe_conn):
    """通知父进程执行完成。"""
    try:
        pipe_conn.send({'type': 'done'})
    except Exception:
        pass


def _wait_response(pipe_conn):
    """等待父进程对交互请求的响应。

    Returns:
        父进程发送的值；若收到 abort 或管道关闭，返回 None。
    """
    try:
        while True:
            msg = pipe_conn.recv()
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get('type')
            if msg_type == 'response':
                return msg.get('value')
            if msg_type == 'abort':
                # 收到终止信号，抛出异常中断执行
                raise KeyboardInterrupt('脚本被终止')
            # 其他消息忽略
    except (EOFError, OSError):
        # 管道已关闭
        raise KeyboardInterrupt('管道已关闭')


# ---------------------------------------------------------------------------
# 超时监控
# ---------------------------------------------------------------------------

def _setup_timeout_watchdog(timeout):
    """设置 SIGALRM 超时监控（仅 Unix 可用）。

    通过定时信号中断脚本执行，避免长循环阻塞。
    """
    if not hasattr(signal, 'SIGALRM'):
        return  # Windows 无 SIGALRM，跳过

    def _handler(signum, frame):
        raise TimeoutError(f'脚本执行超时（>{timeout}秒）')

    try:
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(int(timeout) if timeout else 0)
    except Exception:
        pass


def _cancel_timeout_watchdog():
    """取消 SIGALRM 超时监控。"""
    if hasattr(signal, 'SIGALRM'):
        try:
            signal.alarm(0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 子进程入口函数
# ---------------------------------------------------------------------------

def run_script(code, pipe_conn, interactive, timeout, max_loop_iter):
    """子进程入口函数。

    Args:
        code: 脚本代码
        pipe_conn: multiprocessing.Pipe 的子进程端
        interactive: 交互模式还是定时模式
        timeout: 执行超时
        max_loop_iter: 最大循环迭代次数
    """
    # 设置超时看门狗
    if timeout and timeout > 0:
        _setup_timeout_watchdog(timeout)

    try:
        # -----------------------------------------------------------------
        # 创建 output_callback
        # -----------------------------------------------------------------

        def output_callback(event_type, data):
            """通信回调：发送事件给父进程，必要时等待响应。"""
            _send_event(pipe_conn, event_type, data)

            # 交互事件需要等待父进程响应
            if event_type in ('prompt', 'confirm'):
                return _wait_response(pipe_conn)

            # 其他事件无返回值
            return None

        # -----------------------------------------------------------------
        # 创建内置函数字典并注入到全局命名空间
        # -----------------------------------------------------------------

        builtins_dict = create_builtins(output_callback, interactive=interactive)

        # 构造 __builtins__：从真实 builtins 出发，移除危险函数
        # 注意：__import__ 和 __build_class__ 必须保留，否则 import 语句
        # 和 class 语句无法工作。AST 沙箱已禁止脚本直接调用 __import__()
        import builtins as _builtins_mod

        # 危险函数黑名单：这些会从 __builtins__ 中移除
        # （沙箱已禁止直接调用，这里做二次防护，避免间接引用绕过）
        _runtime_blacklist = {
            'exec', 'eval', 'compile', 'globals', 'locals', 'vars', 'dir',
            'getattr', 'setattr', 'delattr', 'hasattr', 'breakpoint',
            'exit', 'quit', '__builtins__',
        }

        # 复制真实 builtins 并移除危险函数
        safe_builtins = {}
        for name in dir(_builtins_mod):
            if name in _runtime_blacklist:
                continue
            safe_builtins[name] = getattr(_builtins_mod, name)

        # 用我们的 print 覆盖默认 print（输出走管道而非 stdout）
        safe_builtins['print'] = builtins_dict['print']

        # 构造脚本的全局命名空间
        script_globals = {
            '__name__': '__main__',
            '__builtins__': safe_builtins,
        }

        # 注入自定义内置函数到全局命名空间（优先级高于 __builtins__）
        script_globals.update(builtins_dict)

        # -----------------------------------------------------------------
        # 执行脚本
        # -----------------------------------------------------------------

        try:
            # 编译并执行
            compiled = compile(code, '<miniscript>', 'exec')
            exec(compiled, script_globals)
        except KeyboardInterrupt:
            # 被 abort 或用户终止
            _send_event(pipe_conn, 'error', {'message': '脚本执行被终止'})
        except TimeoutError as e:
            _send_event(pipe_conn, 'error', {'message': str(e)})
        except SystemExit:
            # 脚本调用 exit/quit（已禁用，但防御性处理）
            _send_event(pipe_conn, 'error', {'message': '脚本调用了退出函数'})
        except Exception as e:
            # 捕获所有异常，发送错误事件
            tb = traceback.format_exc()
            _send_event(pipe_conn, 'error', {
                'message': f'{type(e).__name__}: {e}',
                'traceback': tb,
            })

    except Exception as e:
        # 顶层兜底，防止子进程静默崩溃
        try:
            _send_event(pipe_conn, 'error', {
                'message': f'子进程内部错误: {type(e).__name__}: {e}'
            })
        except Exception:
            pass
    finally:
        # 取消超时看门狗
        _cancel_timeout_watchdog()
        # 通知父进程执行完成
        _send_done(pipe_conn)
        # 关闭管道子进程端
        try:
            pipe_conn.close()
        except Exception:
            pass
