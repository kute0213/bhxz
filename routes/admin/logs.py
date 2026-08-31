"""访问日志路由：分页查看、清空 + 系统日志实时查看（SSE）。"""

import queue
import json
import time
from flask import render_template, redirect, url_for, flash, abort, request, Response, stream_with_context

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp
from services.logger import (
    log, get_log_buffer_tail, register_monitor_client, unregister_monitor_client,
)


@admin_bp.route('/admin/logs')
@login_required
def admin_logs():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page

        total = conn.execute("SELECT COUNT(*) AS c FROM access_logs").fetchone()['c']
        total_pages = (total + per_page - 1) // per_page

        logs = conn.execute("""
            SELECT * FROM access_logs
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        logs = [dict(log) for log in logs]
    finally:
        conn.close()

    return render_template(
        'admin/admin_logs.html',
        user=user,
        logs=logs,
        page=page,
        total_pages=total_pages,
        total=total
    )


@admin_bp.route('/admin/logs/clear', methods=['POST'])
@login_required
def admin_logs_clear():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        try:
            conn.execute("DELETE FROM access_logs")
            conn.commit()
        except:
            conn.rollback()
    finally:
        conn.close()
    flash('访问日志已清空', 'success')
    return redirect(url_for('admin.admin_logs'))


# ---------------------------------------------------------------------------
# 系统日志实时查看（SSE + 内存缓冲）
# ---------------------------------------------------------------------------


@admin_bp.route('/admin/system-logs')
@login_required
def admin_system_logs_page():
    """系统日志查看页面（实时，SSE 推送）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return render_template('admin/admin_system_logs.html', user=user)


@admin_bp.route('/admin/api/system-logs/stream')
@login_required
def admin_system_logs_sse():
    """SSE 端点：实时推送系统日志。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    def event_stream():
        # 每个客户端独享一个队列
        q = queue.Queue(maxsize=500)
        register_monitor_client(q)
        try:
            # 先推送历史缓冲
            history = get_log_buffer_tail(200)
            yield f'event: history\ndata: {json.dumps(history, ensure_ascii=False)}\n\n'

            # 持续接收新日志
            while True:
                try:
                    payload = q.get(timeout=30)
                    yield f'data: {payload}\n\n'
                except queue.Empty:
                    # 30 秒无日志，发心跳保持连接
                    yield ': heartbeat\n\n'
        except GeneratorExit:
            pass
        finally:
            unregister_monitor_client(q)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@admin_bp.route('/admin/api/system-logs/history')
@login_required
def admin_system_logs_history():
    """获取系统日志历史（不含 SSE）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    from flask import jsonify
    level = request.args.get('level', '')
    logs = get_log_buffer_tail(500)
    if level:
        logs = [e for e in logs if e['level'] == level.upper()]
    return jsonify({'logs': logs})
