"""定时任务管理路由。

提供定时任务的 CRUD、启用/禁用、手动触发、执行日志查看等接口。
"""

import datetime
from flask import (
    Blueprint, render_template, request, jsonify, abort,
)
from core.auth import login_required, get_current_user
from core.database import get_db
from services.scheduler import scheduler, TaskScheduler

scheduled_bp = Blueprint('scheduled', __name__)


def _admin_check():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return user


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

@scheduled_bp.route('/admin/cmd/scheduled')
@login_required
def scheduled_page():
    """定时任务管理页面。"""
    user = _admin_check()
    return render_template('admin_cmd_scheduled.html', user=user)


# ---------------------------------------------------------------------------
# 任务 CRUD
# ---------------------------------------------------------------------------

@scheduled_bp.route('/admin/cmd/scheduled/tasks', methods=['GET'])
@login_required
def list_tasks():
    """获取所有定时任务列表。"""
    _admin_check()
    conn = get_db()
    tasks = conn.execute(
        "SELECT * FROM scheduled_tasks ORDER BY id ASC"
    ).fetchall()
    tasks = [dict(t) for t in tasks]
    conn.close()
    return jsonify({'tasks': tasks})


@scheduled_bp.route('/admin/cmd/scheduled/tasks', methods=['POST'])
@login_required
def create_task():
    """创建定时任务。"""
    _admin_check()
    data = request.get_json() or request.form

    name = (data.get('name') or '').strip()
    command = (data.get('command') or '').strip()
    schedule_type = (data.get('schedule_type') or 'interval').strip()
    interval_seconds = int(data.get('interval_seconds') or 3600)
    execute_at = (data.get('execute_at') or '').strip()

    if not name or not command:
        return jsonify({'success': False, 'message': '名称和命令不能为空'}), 400

    if schedule_type not in ('interval', 'daily', 'once'):
        return jsonify({'success': False, 'message': '无效的调度类型'}), 400

    if schedule_type == 'daily' and not execute_at:
        return jsonify({'success': False, 'message': '每日任务需要指定执行时间'}), 400

    if schedule_type == 'once' and not execute_at:
        return jsonify({'success': False, 'message': '一次性任务需要指定执行时间'}), 400

    next_run = TaskScheduler.calc_initial_next_run(
        schedule_type, interval_seconds, execute_at or None
    )

    conn = get_db()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO scheduled_tasks "
        "(name, command, schedule_type, interval_seconds, execute_at, "
        " is_enabled, next_run_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (name, command, schedule_type, interval_seconds,
         execute_at or None, next_run, now),
    )
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()

    return jsonify({
        'success': True, 'id': task_id, 'message': '定时任务已创建',
        'next_run_at': next_run,
    })


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>', methods=['PUT', 'POST'])
@login_required
def update_task(task_id):
    """更新定时任务。"""
    _admin_check()
    data = request.get_json() or request.form

    name = (data.get('name') or '').strip()
    command = (data.get('command') or '').strip()
    schedule_type = (data.get('schedule_type') or 'interval').strip()
    interval_seconds = int(data.get('interval_seconds') or 3600)
    execute_at = (data.get('execute_at') or '').strip()

    if not name or not command:
        return jsonify({'success': False, 'message': '名称和命令不能为空'}), 400

    if schedule_type not in ('interval', 'daily', 'once'):
        return jsonify({'success': False, 'message': '无效的调度类型'}), 400

    conn = get_db()
    existing = conn.execute(
        "SELECT id, is_enabled FROM scheduled_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    # 重新计算下次执行时间
    next_run = TaskScheduler.calc_initial_next_run(
        schedule_type, interval_seconds, execute_at or None
    )

    conn.execute(
        "UPDATE scheduled_tasks SET name = ?, command = ?, schedule_type = ?, "
        "interval_seconds = ?, execute_at = ?, next_run_at = ? WHERE id = ?",
        (name, command, schedule_type, interval_seconds,
         execute_at or None, next_run, task_id),
    )
    conn.commit()
    conn.close()

    return jsonify({
        'success': True, 'message': '任务已更新', 'next_run_at': next_run,
    })


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>/delete',
                    methods=['POST', 'DELETE'])
@login_required
def delete_task(task_id):
    """删除定时任务。"""
    _admin_check()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM scheduled_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': '任务已删除'})


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>/toggle',
                    methods=['POST'])
@login_required
def toggle_task(task_id):
    """启用/禁用定时任务。"""
    _admin_check()
    conn = get_db()
    task = conn.execute(
        "SELECT id, is_enabled, schedule_type, interval_seconds, execute_at "
        "FROM scheduled_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not task:
        conn.close()
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    new_status = 0 if task['is_enabled'] else 1

    # 启用时重新计算下次执行时间
    next_run = None
    if new_status == 1:
        next_run = TaskScheduler.calc_initial_next_run(
            task['schedule_type'], task['interval_seconds'],
            task['execute_at'],
        )

    conn.execute(
        "UPDATE scheduled_tasks SET is_enabled = ?, next_run_at = ? WHERE id = ?",
        (new_status, next_run, task_id),
    )
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'is_enabled': new_status,
        'next_run_at': next_run,
        'message': '任务已启用' if new_status else '任务已禁用',
    })


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>/trigger',
                    methods=['POST'])
@login_required
def trigger_task(task_id):
    """手动触发定时任务立即执行。"""
    _admin_check()
    success = scheduler.trigger_now(task_id)
    if not success:
        return jsonify({
            'success': False,
            'message': '任务不存在或正在执行中',
        }), 400

    return jsonify({'success': True, 'message': '任务已触发'})


# ---------------------------------------------------------------------------
# 执行日志
# ---------------------------------------------------------------------------

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


@scheduled_bp.route('/admin/cmd/scheduled/status')
@login_required
def tasks_status():
    """获取所有任务的最新执行状态（用于前端轮询展示）。

    返回每个任务 id 对应的最近一次执行：success / started_at / duration_seconds。
    """
    _admin_check()
    conn = get_db()

    # 一次性查询所有任务的最新执行日志（按 task_id 分组取最新一条）
    latest_logs = conn.execute("""
        SELECT l.task_id, l.success, l.started_at, l.duration_seconds, l.exit_code
        FROM scheduled_task_logs l
        INNER JOIN (
            SELECT task_id, MAX(id) AS max_id
            FROM scheduled_task_logs
            GROUP BY task_id
        ) m ON l.id = m.max_id
    """).fetchall()

    # 一次性查询最近 10 分钟内的执行数量（用于显示活动状态）
    import datetime as _dt
    since = (_dt.datetime.now() - _dt.timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    recent_counts = conn.execute("""
        SELECT task_id, COUNT(*) AS c
        FROM scheduled_task_logs
        WHERE started_at >= ?
        GROUP BY task_id
    """, (since,)).fetchall()

    conn.close()

    status_map = {}
    for row in latest_logs:
        status_map[row['task_id']] = {
            'last_success': bool(row['success']),
            'last_started_at': row['started_at'],
            'last_duration': row['duration_seconds'],
            'last_exit_code': row['exit_code'],
        }

    recent_map = {row['task_id']: row['c'] for row in recent_counts}

    return jsonify({
        'status': status_map,
        'recent': recent_map,
        'now': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
