"""CMD 脚本执行（SSE 流式 + 交互）以及管理员校验辅助函数。

_admin_check 在本模块定义，供 pages / commands / execution 子模块复用。
"""

import json
import uuid

from flask import (
    request, jsonify, Response, abort, stream_with_context, session
)

from core.auth import login_required, get_current_user
from services.miniscript.session import ScriptSessionManager
from routes.script import script_bp


def _admin_check():
    """校验当前用户是否为管理员，否则返回 403。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return user


# 交互响应超时时间（秒）
_RESPONSE_TIMEOUT = 60


def _get_session_id():
    """获取当前 Flask session 的稳定标识。"""
    sid = session.get('script_sid')
    if not sid:
        sid = str(uuid.uuid4())
        session['script_sid'] = sid
    return sid


def _get_session_manager():
    """获取脚本会话管理器单例。"""
    return ScriptSessionManager(response_timeout=_RESPONSE_TIMEOUT)


@script_bp.route('/admin/script/run-script', methods=['POST'])
@login_required
def run_script_sse():
    """MiniScript 脚本执行 SSE 端点。

    接收 JSON body {"code": "..."}，流式返回执行事件。
    事件格式: data: {"type": "output|alert|prompt|confirm|error|done", "data": {...}}\\n\\n
    交互事件 prompt/confirm 通过 /admin/script/script-response 接收前端响应。
    """
    _admin_check()
    data = request.get_json() or request.form
    code = (data.get('code') or '').strip()

    if not code:
        return jsonify({'success': False, 'message': '脚本代码不能为空'}), 400

    sid = _get_session_id()
    manager = _get_session_manager()

    # 同一用户同时只能执行一个脚本
    if manager.is_running(sid):
        return jsonify({
            'success': False,
            'message': '已有脚本正在执行，请先终止',
        }), 409

    executor = manager.get_executor(sid)

    def generate():
        try:
            manager.clear_response(sid)
            gen = executor.execute(code, interactive=True)

            # 启动生成器，获取第一个事件
            try:
                event = next(gen)
            except StopIteration:
                return

            while True:
                event_type, ev_data = event

                # 心跳：仅用于连接保活与失效探测，不转发给前端
                if event_type == 'heartbeat':
                    try:
                        event = next(gen)
                    except StopIteration:
                        break
                    continue

                # 标记连接存活，供监控线程判断页面是否已退出
                manager.touch(sid)

                # 推送事件给前端；客户端断开时 yield 会抛 GeneratorExit
                yield (
                    f"data: {json.dumps({'type': event_type, 'data': ev_data}, ensure_ascii=False)}\n\n"
                )

                if event_type in ('prompt', 'confirm'):
                    # 交互事件：等待前端通过 /admin/script/script-response 发送响应
                    response = manager.wait_response(sid, event_type)
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
            # 客户端断开连接：直接进入 finally 清理
            raise
        except Exception as e:
            try:
                yield (
                    f"data: {json.dumps({'type': 'error', 'data': {'message': f'SSE 流异常: {e}'}}, ensure_ascii=False)}\n\n"
                )
            except Exception:
                # 客户端可能已断开，吞掉写入异常
                pass
        finally:
            # 确保执行器被终止、响应事件被唤醒
            try:
                if executor.is_running():
                    executor.abort()
            except Exception:
                pass
            try:
                manager.set_response(sid, None)
            except Exception:
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


@script_bp.route('/admin/script/abort-script', methods=['POST'])
@login_required
def abort_script():
    """终止正在执行的脚本。"""
    _admin_check()
    sid = _get_session_id()
    manager = _get_session_manager()

    try:
        if manager.abort(sid):
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': '没有正在执行的脚本'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@script_bp.route('/admin/script/script-response', methods=['POST'])
@login_required
def script_response():
    """接收前端对交互事件（prompt/confirm）的响应。

    接收 JSON {"value": "用户输入值"}，将响应值存入当前 session 的交互状态，
    唤醒等待中的 SSE 线程。
    """
    _admin_check()
    data = request.get_json() or request.form
    value = data.get('value')

    sid = _get_session_id()
    manager = _get_session_manager()
    manager.set_response(sid, value)

    return jsonify({'success': True})
