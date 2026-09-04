"""Shell 命令执行路由：同步执行、SSE 流式执行。"""

import json

from flask import request, jsonify, Response, stream_with_context

from core.auth import admin_required
from services.cmd_runner import run_command_stream, run_command_sync
from routes.script import script_bp


@script_bp.route('/admin/script/run', methods=['POST'])
@admin_required
def run_cmd_sync():
    """同步执行命令，一次性返回全部输出。"""
    data = request.get_json() or request.form
    command = (data.get('command') or '').strip()
    timeout = int(data.get('timeout') or 30)

    if not command:
        return jsonify({'success': False, 'message': '命令不能为空'}), 400

    if timeout > 600:
        timeout = 600

    result = run_command_sync(command, timeout=timeout)
    return jsonify(result)


@script_bp.route('/admin/script/run-stream', methods=['GET', 'POST'])
@admin_required
def run_cmd_stream():
    """流式执行命令，通过 SSE 实时返回输出。"""
    if request.method == 'POST':
        data = request.get_json() or request.form
    else:
        data = request.args

    command = (data.get('command') or '').strip()
    timeout = int(data.get('timeout') or 300)

    if not command:
        return jsonify({'success': False, 'message': '命令不能为空'}), 400

    if timeout > 600:
        timeout = 600

    def generate():
        for event in run_command_stream(command, timeout=timeout):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
