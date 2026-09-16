"""管理后台 - 一键更新路由。

提供 SSE 流式更新进度和页面路由。
"""

import json

from flask import render_template, Response, stream_with_context, abort

from core.auth import admin_required, get_current_user
from routes.admin import admin_bp
from services.updater import start_update, pop_events, get_status


@admin_bp.route('/admin/update')
@admin_required
def admin_update_page():
    """一键更新页面。"""
    status = get_status()
    return render_template('admin/admin_update.html', user=get_current_user(), status=status)


@admin_bp.route('/admin/update/start', methods=['POST'])
@admin_required
def admin_update_start():
    """启动一键更新（后台线程）。"""
    from flask import jsonify

    ok = start_update()
    if ok:
        return jsonify({'success': True, 'message': '更新已启动'})
    else:
        return jsonify({'success': False, 'message': '已有更新任务正在运行'})


@admin_bp.route('/admin/update/stream')
@admin_required
def admin_update_stream():
    """SSE 流式输出更新进度。"""
    def generate():
        # 先发送当前状态
        status = get_status()
        yield f"data: {json.dumps({'type': 'status', 'data': status}, ensure_ascii=False)}\n\n"

        # 持续读取事件
        while True:
            events = pop_events()
            for event_type, data in events:
                yield f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"
                if event_type == 'done':
                    yield "data: [DONE]\n\n"
                    return

            # 检查是否已结束（可能事件已在上一轮被取走）
            s = get_status()
            if s['done']:
                yield "data: [DONE]\n\n"
                return

            import time
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )