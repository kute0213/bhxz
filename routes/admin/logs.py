"""管理后台 - 日志在线查看。

使用 core/logger.py 的内存环形缓冲实现实时日志查看，
支持等级筛选、实时 SSE 推送，不依赖数据库访问日志。
"""

import json
import queue
import time

from flask import render_template, request, jsonify, Response, stream_with_context

from core.auth import admin_required, get_current_user
from core.logger import (
    get_log_buffer, get_log_buffer_tail, clear_log_buffer,
    register_monitor_client, unregister_monitor_client,
)
from routes.admin import admin_bp

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


@admin_bp.route('/admin/logs')
@admin_required
def admin_logs_page():
    """日志查看页面。"""
    return render_template('admin/admin_logs.html', user=get_current_user())


@admin_bp.route('/admin/api/logs')
@admin_required
def api_get_logs():
    """获取日志列表（支持等级筛选、增量拉取）。

    Query params:
        level:  筛选等级，如 'ERROR'，空字符串表示不过滤
        after:  只返回索引大于此值的条目（增量拉取）
        tail:   获取最近 N 条（默认 200），与 after 互斥
    """
    level = request.args.get('level', '', type=str)
    after = request.args.get('after', 0, type=int)
    tail = request.args.get('tail', 0, type=int)

    if tail > 0:
        entries = get_log_buffer_tail(tail)
        result = [{'index': i, **e} for i, e in enumerate(entries)]
    else:
        raw = get_log_buffer(level_filter=level, after_index=after)
        result = [{'index': idx, **e} for idx, e in raw]

    return jsonify({
        'success': True,
        'entries': result,
        'total': len(result),
    })


@admin_bp.route('/admin/api/logs/clear', methods=['POST'])
@admin_required
def api_clear_logs():
    """清空内存日志缓冲。"""
    clear_log_buffer()
    return jsonify({'success': True, 'message': '日志已清空'})


@admin_bp.route('/admin/api/logs/stream')
@admin_required
def api_log_stream():
    """SSE 实时日志推送。"""
    def generate():
        q = queue.Queue(maxsize=500)
        register_monitor_client(q)
        try:
            # 发送初始连接成功事件
            yield 'event: connected\ndata: {}\n\n'
            while True:
                try:
                    data = q.get(timeout=30)
                    yield f'data: {data}\n\n'
                except queue.Empty:
                    # 心跳，保持连接
                    yield ': heartbeat\n\n'
        finally:
            unregister_monitor_client(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )