"""终端 API 路由 - 持久 shell 会话。

安全说明：仅管理员可用，输出通过 SSE 流式返回。
每个用户会话对应一个独立的 shell 子进程，关闭页面后一段时间自动回收。

本模块为薄路由层：会话创建、维护、清理全部委托给 TerminalManager。
"""

import json
import time

from flask import request, Response, stream_with_context, jsonify, session, abort

from core.auth import admin_required
from routes.script import script_bp
from services.terminal import TerminalManager


def _sse_event(event_type, data):
    """构造 SSE 数据行。"""
    return (
        f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"
    )


def _sse_headers():
    """SSE 响应头。"""
    return {
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    }


@script_bp.route('/admin/script/terminal/stream', methods=['GET'])
@admin_required
def terminal_stream():
    """终端输出流（SSE）。"""
    manager = TerminalManager()
    term_session = manager.get_or_create_session(session)

    # shell 启动失败：推送错误信息后关闭
    if term_session.error:
        def error_generate():
            for chunk in term_session.read_pending_output():
                yield _sse_event('output', {'text': chunk})
            yield _sse_event('error', {'message': term_session.error})
            yield _sse_event('closed', {})

        return Response(
            stream_with_context(error_generate()),
            mimetype='text/event-stream',
            headers=_sse_headers(),
        )

    # 新的 SSE 连接独占当前会话输出
    my_generation = term_session.next_generation()

    def generate():
        try:
            yield _sse_event('connected', {})
            last_heartbeat = time.time()
            term_session.touch()

            while not term_session.closed:
                if term_session.generation != my_generation:
                    break

                term_session.wait_output(timeout=2.0)

                if term_session.generation != my_generation:
                    break

                chunks = term_session.read_pending_output(my_generation)
                if chunks:
                    text = ''.join(chunks)
                    yield _sse_event('output', {'text': text})
                    last_heartbeat = time.time()
                    term_session.touch()
                else:
                    now = time.time()
                    if now - last_heartbeat >= 10.0:
                        yield _sse_event('heartbeat', {})
                        last_heartbeat = now
                    term_session.touch()

            yield _sse_event('closed', {})
        except Exception:
            # 客户端断开时 GeneratorExit 会进入此处，静默结束
            pass

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_headers(),
    )


@script_bp.route('/admin/script/terminal/input', methods=['POST'])
@admin_required
def terminal_input():
    data = request.get_json() or {}
    text = data.get('text', '')

    if not isinstance(text, str):
        return jsonify({'success': False, 'message': '输入内容必须是字符串'}), 400
    if not text:
        return jsonify({'success': False, 'message': '输入不能为空'}), 400

    manager = TerminalManager()
    term_session = manager.get_or_create_session(session)

    if term_session.error:
        return jsonify({
            'success': False,
            'message': f'终端不可用: {term_session.error}',
        }), 503

    ok = term_session.send_input(text)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '会话已关闭'}), 400


@script_bp.route('/admin/script/terminal/reset', methods=['POST'])
@admin_required
def terminal_reset():
    """重置终端（重启 shell 进程）。"""
    manager = TerminalManager()
    term_session = manager.reset_session(session)

    if term_session.error:
        return jsonify({
            'success': False,
            'message': f'终端重置失败: {term_session.error}',
        }), 503

    return jsonify({'success': True, 'message': '终端已重置'})


@script_bp.route('/admin/script/terminal/resize', methods=['POST'])
@admin_required
def terminal_resize():
    """调整终端窗口尺寸（PTY 会话生效，用于正确响应清屏与光标控制）。"""
    data = request.get_json() or {}
    try:
        cols = int(data.get('cols', 120))
        rows = int(data.get('rows', 24))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '尺寸格式无效'}), 400
    if cols < 2 or rows < 2:
        return jsonify({'success': False, 'message': '尺寸无效'}), 400

    manager = TerminalManager()
    term_session = manager.get_or_create_session(session)
    if term_session.error:
        return jsonify({
            'success': False,
            'message': f'终端不可用: {term_session.error}',
        }), 503

    term_session.set_size(rows, cols)
    return jsonify({'success': True})