"""CMD 脚本执行（SSE 流式 + 交互）以及管理员校验辅助函数。

_admin_check 在本模块定义，供 pages / commands / execution 子模块复用。
"""

import json
import threading
import time

from flask import (
    request, jsonify, Response, abort, stream_with_context
)

from core.auth import login_required, get_current_user
from services.miniscript import ScriptExecutor
from routes.cmd import cmd_bp


def _admin_check():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return user


# ---------------------------------------------------------------------------
# MiniScript 脚本执行（SSE 流式 + 交互）
# ---------------------------------------------------------------------------

# 全局单例脚本执行器（模块级别，懒加载）
_script_executor = None
_executor_lock = threading.Lock()

# 交互响应通信：SSE 线程等待 -> 响应线程唤醒
# 由于 SSE 是单向的（服务端→客户端），前端对 prompt/confirm 的响应
# 需通过单独的 POST /admin/cmd/script-response 接口回传
_response_event = threading.Event()
_response_value = None
_response_lock = threading.Lock()

# 脚本执行互斥锁（同时只允许一个脚本执行）
_running_lock = threading.Lock()

# 等待前端交互响应的超时时间（秒）
_RESPONSE_TIMEOUT = 60
# 单次轮询响应事件的间隔（秒）：用短轮询代替长阻塞，
# 便于在客户端断开 / 执行器被终止时及时退出等待。
_RESPONSE_POLL_INTERVAL = 2.0


def _get_script_executor():
    """获取全局单例 ScriptExecutor（双重检查锁定懒加载）。"""
    global _script_executor
    if _script_executor is None:
        with _executor_lock:
            if _script_executor is None:
                _script_executor = ScriptExecutor()
    return _script_executor


def _wait_for_response(event_type, executor):
    """轮询等待前端对交互事件（prompt/confirm）的响应。

    用短轮询代替单次长 wait()，使得：
      - 执行器被外部 abort() 终止后能立即返回，避免空等
      - 客户端断开后下一次 yield 能尽快触发 GeneratorExit

    Args:
        event_type: 'prompt' 或 'confirm'
        executor:   当前脚本执行器，用于检测是否仍在运行

    Returns:
        前端响应值；超时或执行器已终止时返回 None(prompt) / False(confirm)
    """
    global _response_value
    deadline = time.time() + _RESPONSE_TIMEOUT
    while time.time() < deadline:
        if _response_event.wait(timeout=_RESPONSE_POLL_INTERVAL):
            with _response_lock:
                response = _response_value
                _response_value = None
            return response
        # 执行器已终止（如客户端断开 / 主动 abort）：无需继续等待
        try:
            if not executor.is_running():
                return None if event_type == 'prompt' else False
        except Exception:
            return None if event_type == 'prompt' else False
    # 超时
    return None if event_type == 'prompt' else False


@cmd_bp.route('/admin/cmd/run-script', methods=['POST'])
@login_required
def run_script_sse():
    """MiniScript 脚本执行 SSE 端点。

    接收 JSON body {"code": "..."}，流式返回执行事件。
    事件格式: data: {"type": "output|alert|prompt|confirm|error|done", "data": {...}}\\n\\n
    交互事件 prompt/confirm 通过 /admin/cmd/script-response 接收前端响应。
    """
    _admin_check()
    data = request.get_json() or request.form
    code = (data.get('code') or '').strip()
    timeout = int(data.get('timeout') or 30)

    if not code:
        return jsonify({'success': False, 'message': '脚本代码不能为空'}), 400

    if timeout > 600:
        timeout = 600

    # 同时只允许一个脚本执行，避免子进程并发冲突
    if not _running_lock.acquire(blocking=False):
        return jsonify({'success': False, 'message': '已有脚本正在执行，请先终止'}), 409

    executor = _get_script_executor()

    def generate():
        global _response_value
        try:
            # 清理上一次的响应状态
            _response_event.clear()
            with _response_lock:
                _response_value = None

            gen = executor.execute(code, interactive=True, timeout=timeout)
            # 启动生成器，获取第一个事件（首次必须用 next() 触发执行）
            try:
                event = next(gen)
            except StopIteration:
                return

            while True:
                event_type, ev_data = event
                # 推送事件给前端：
                # 客户端断开时此 yield 会抛 GeneratorExit，进入 finally 清理执行器
                yield f"data: {json.dumps({'type': event_type, 'data': ev_data}, ensure_ascii=False)}\n\n"

                if event_type in ('prompt', 'confirm'):
                    # 交互事件：等待前端通过 /admin/cmd/script-response 发送响应
                    response = _wait_for_response(event_type, executor)
                    # 回传响应给执行器，并获取下一个事件
                    try:
                        event = gen.send(response)
                    except StopIteration:
                        break
                else:
                    # 普通事件（output/alert/error/done），直接获取下一个
                    try:
                        event = next(gen)
                    except StopIteration:
                        break
        except GeneratorExit:
            # 客户端断开连接：不再尝试 yield 错误信息，直接进入 finally 清理
            raise
        except Exception as e:
            try:
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': f'SSE 流异常: {e}'}}, ensure_ascii=False)}\n\n"
            except Exception:
                # 客户端可能已断开，吞掉写入异常
                pass
        finally:
            # 确保执行器被终止、互斥锁被释放（任何路径都必须执行）
            try:
                if executor.is_running():
                    executor.abort()
            except Exception:
                pass
            # 唤醒可能正在等待响应的 abort 线程，避免死锁
            try:
                _response_event.set()
            except Exception:
                pass
            try:
                _running_lock.release()
            except Exception:
                # 锁可能已被释放（防御性）：吞掉以避免 finally 抛出
                pass

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@cmd_bp.route('/admin/cmd/abort-script', methods=['POST'])
@login_required
def abort_script():
    """终止正在执行的脚本。"""
    _admin_check()
    try:
        executor = _get_script_executor()
        if executor.is_running():
            executor.abort()
            # 唤醒可能正在等待响应的 SSE 线程，避免死锁
            _response_event.set()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '没有正在执行的脚本'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@cmd_bp.route('/admin/cmd/script-response', methods=['POST'])
@login_required
def script_response():
    """接收前端对交互事件（prompt/confirm）的响应。

    接收 JSON {"value": "用户输入值"}，将响应值存入全局变量，
    唤醒等待中的 SSE 线程。
    """
    _admin_check()
    global _response_value
    data = request.get_json() or request.form
    value = data.get('value')

    with _response_lock:
        _response_value = value
    _response_event.set()

    return jsonify({'success': True})
