"""定时任务执行日志路由：单任务日志、全部日志、日志详情。"""

from flask import request, jsonify

from core.auth import login_required
from core.db import get_db
from routes.scheduled import scheduled_bp, _admin_check


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>/logs')
@login_required
def task_logs(task_id):
    """获取某个任务的执行日志。"""
    _admin_check()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page

    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM scheduled_task_logs WHERE task_id = ?",
        (task_id,),
    ).fetchone()['c']
    total_pages = (total + per_page - 1) // per_page

    logs = conn.execute(
        "SELECT * FROM scheduled_task_logs WHERE task_id = ? "
        "ORDER BY id DESC LIMIT ? OFFSET ?",
        (task_id, per_page, offset),
    ).fetchall()
    logs = [dict(l) for l in logs]
    conn.close()

    return jsonify({
        'logs': logs,
        'page': page,
        'total_pages': total_pages,
        'total': total,
    })


@scheduled_bp.route('/admin/cmd/scheduled/logs')
@login_required
def all_task_logs():
    """获取所有任务执行日志。"""
    _admin_check()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page

    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM scheduled_task_logs"
    ).fetchone()['c']
    total_pages = (total + per_page - 1) // per_page

    logs = conn.execute(
        "SELECT * FROM scheduled_task_logs ORDER BY id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    ).fetchall()
    logs = [dict(l) for l in logs]
    conn.close()

    return jsonify({
        'logs': logs,
        'page': page,
        'total_pages': total_pages,
        'total': total,
    })


@scheduled_bp.route('/admin/cmd/scheduled/logs/<int:log_id>')
@login_required
def task_log_detail(log_id):
    """获取单条执行日志详情（含完整输出）。"""
    _admin_check()
    conn = get_db()
    log = conn.execute(
        "SELECT * FROM scheduled_task_logs WHERE id = ?", (log_id,)
    ).fetchone()
    conn.close()

    if not log:
        return jsonify({'success': False, 'message': '日志不存在'}), 404

    return jsonify(dict(log))
