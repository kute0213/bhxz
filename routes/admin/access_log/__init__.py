"""管理后台 - 访问日志抓取。

管理界面控制服务端抓取开关：

* ``POST /admin/api/access-log/start``  开启抓取（创建独立 DuckDB 数据库）
* ``POST /admin/api/access-log/stop``   取消抓取（停止并删除数据库）
* ``GET  /admin/api/access-log/status`` 查询当前状态
* ``GET  /admin/api/access-log/stream`` SSE 实时推送（首帧 history + 后续 data）

抓取状态保存在服务端，页面关闭 / SSE 断开不会停止抓取，只有显式取消才会停止。
"""

import json
import queue

from flask import Response, jsonify, request, stream_with_context

from core.auth import admin_required
from core.helpers import render_page
from routes.admin import admin_bp
from services.access_log import (
    get_status,
    is_capturing,
    query_recent,
    start_capture,
    stop_capture,
    subscribe,
    unsubscribe,
)

DEFAULT_HISTORY_TAIL = 500
MAX_HISTORY_TAIL = 2000
SSE_HEARTBEAT_SECONDS = 15


def _sse(event, payload):
    """构造一条 SSE 事件。"""
    return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'


@admin_bp.route('/admin/access-log')
@admin_required
def admin_access_log_page():
    """访问日志抓取页面。"""
    return render_page('admin/access_log.html')


@admin_bp.route('/admin/api/access-log/status')
@admin_required
def api_access_log_status():
    """返回当前抓取状态。"""
    return jsonify({'success': True, 'status': get_status()})


@admin_bp.route('/admin/api/access-log/start', methods=['POST'])
@admin_required
def api_access_log_start():
    """开启访问日志抓取。"""
    success, message = start_capture()
    return jsonify({'success': success, 'message': message, 'status': get_status()})


@admin_bp.route('/admin/api/access-log/stop', methods=['POST'])
@admin_required
def api_access_log_stop():
    """取消访问日志抓取并删除数据库。"""
    success, message = stop_capture()
    return jsonify({'success': success, 'message': message, 'status': get_status()})


@admin_bp.route('/admin/api/access-log/stream')
@admin_required
def api_access_log_stream():
    """访问日志实时推送（SSE）。

    首帧 ``history`` 携带最近访问记录快照，之后持续推送 ``data`` 事件；
    取消抓取时服务端推送 ``stopped`` 事件并结束连接。空闲时发送心跳保活。
    """
    tail = request.args.get('tail', DEFAULT_HISTORY_TAIL, type=int)
    if tail <= 0:
        tail = DEFAULT_HISTORY_TAIL
    tail = min(tail, MAX_HISTORY_TAIL)

    def generate():
        client_queue = queue.Queue(maxsize=2000)
        subscribe(client_queue)
        try:
            running = is_capturing()
            history = query_recent(tail) if running else []
            yield _sse('history', {
                'entries': history,
                'status': get_status(),
            })
            if not running:
                yield _sse('stopped', {'status': get_status()})
                return

            while True:
                try:
                    item = client_queue.get(timeout=SSE_HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ': heartbeat\n\n'
                    continue
                if item.get('_event') == 'stopped':
                    yield _sse('stopped', {'status': get_status()})
                    return
                # 实时记录必须使用默认 message 事件（不写 event: 行），
                # 前端用 EventSource.onmessage 接收；命名事件不会触发 onmessage。
                yield f'data: {json.dumps(item, ensure_ascii=False)}\n\n'
        finally:
            unsubscribe(client_queue)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            # 不能下发 Connection 等逐跳标头（PEP 3333 禁止，Waitress 会断言失败）
            'X-Accel-Buffering': 'no',
        },
    )
