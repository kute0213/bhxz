"""定时任务 CRUD 路由：列表、创建、更新、删除、启停、触发、状态查询。"""

import datetime

from flask import render_template, request, jsonify

from core.auth import login_required
from core.db import get_db
from services.scheduler import scheduler, TaskScheduler
from routes.scheduled import scheduled_bp, _admin_check


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
    try:
        tasks = conn.execute(
            "SELECT * FROM scheduled_tasks ORDER BY id ASC"
        ).fetchall()
        tasks = [dict(t) for t in tasks]
    finally:
        conn.close()
    return jsonify({'tasks': tasks})


@scheduled_bp.route('/admin/cmd/scheduled/tasks', methods=['POST'])
@login_required
def create_task():
    """创建定时任务。"""
    _admin_check()
    data = request.get_json() or request.form

    name = (data.get('name') or '').strip()
    schedule_type = (data.get('schedule_type') or 'interval').strip()
    interval_seconds = int(data.get('interval_seconds') or 3600)
    execute_at = (data.get('execute_at') or '').strip()
    command_id = data.get('command_id')
    if command_id is not None:
        try:
            command_id = int(command_id)
        except (ValueError, TypeError):
            command_id = None

    if not name:
        return jsonify({'success': False, 'message': '名称不能为空'}), 400

    # 必须选择一个已保存的快捷命令
    if not command_id:
        return jsonify({'success': False, 'message': '请选择一个快捷命令'}), 400

    # 间隔秒数必须为正整数，避免 0/负值导致任务死循环
    if interval_seconds < 1:
        return jsonify({'success': False, 'message': '间隔秒数必须大于 0'}), 400

    # 从 cmd_commands 表读取快捷命令
    conn = get_db()
    try:
        cmd_row = conn.execute(
            "SELECT id, name, command FROM cmd_commands WHERE id = ?",
            (command_id,),
        ).fetchone()
        if not cmd_row:
            return jsonify({'success': False, 'message': '快捷命令不存在'}), 400
        command = cmd_row['command']
        task_type = 'shell'

        if schedule_type not in ('interval', 'daily', 'once'):
            return jsonify({'success': False, 'message': '无效的调度类型'}), 400

        if schedule_type == 'daily' and not execute_at:
            return jsonify({'success': False, 'message': '每日任务需要指定执行时间'}), 400

        if schedule_type == 'once' and not execute_at:
            return jsonify({'success': False, 'message': '一次性任务需要指定执行时间'}), 400

        # 一次性任务执行时间必须是未来时间，避免创建即过期
        if schedule_type == 'once' and execute_at:
            try:
                target = datetime.datetime.strptime(execute_at, '%Y-%m-%d %H:%M:%S')
                if target <= datetime.datetime.now():
                    return jsonify({'success': False, 'message': '执行时间必须晚于当前时间'}), 400
            except ValueError:
                return jsonify({'success': False, 'message': '执行时间格式无效'}), 400

        next_run = TaskScheduler.calc_initial_next_run(
            schedule_type, interval_seconds, execute_at or None
        )

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO scheduled_tasks "
            "(name, command, schedule_type, interval_seconds, execute_at, "
            " is_enabled, next_run_at, created_at, task_type, command_id) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (name, command, schedule_type, interval_seconds,
             execute_at or None, next_run, now, task_type, command_id),
        )
        conn.commit()
        task_id = cursor.lastrowid
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
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
    schedule_type = (data.get('schedule_type') or 'interval').strip()
    interval_seconds = int(data.get('interval_seconds') or 3600)
    execute_at = (data.get('execute_at') or '').strip()
    command_id = data.get('command_id')
    if command_id is not None:
        try:
            command_id = int(command_id)
            if command_id <= 0:
                command_id = None
        except (ValueError, TypeError):
            command_id = None

    if not name:
        return jsonify({'success': False, 'message': '名称不能为空'}), 400

    # 必须选择一个已保存的快捷命令
    if not command_id:
        return jsonify({'success': False, 'message': '请选择一个快捷命令'}), 400

    # 间隔秒数必须为正整数，避免 0/负值导致任务死循环
    if interval_seconds < 1:
        return jsonify({'success': False, 'message': '间隔秒数必须大于 0'}), 400

    # 从 cmd_commands 表读取快捷命令
    conn = get_db()
    try:
        cmd_row = conn.execute(
            "SELECT id, name, command FROM cmd_commands WHERE id = ?",
            (command_id,),
        ).fetchone()
        if not cmd_row:
            return jsonify({'success': False, 'message': '快捷命令不存在'}), 400
        command = cmd_row['command']
        task_type = 'shell'

        if schedule_type not in ('interval', 'daily', 'once'):
            return jsonify({'success': False, 'message': '无效的调度类型'}), 400

        if schedule_type == 'daily' and not execute_at:
            return jsonify({'success': False, 'message': '每日任务需要指定执行时间'}), 400

        if schedule_type == 'once' and not execute_at:
            return jsonify({'success': False, 'message': '一次性任务需要指定执行时间'}), 400

        # 一次性任务执行时间必须是未来时间，避免更新后立即过期触发
        if schedule_type == 'once' and execute_at:
            try:
                target = datetime.datetime.strptime(execute_at, '%Y-%m-%d %H:%M:%S')
                if target <= datetime.datetime.now():
                    return jsonify({'success': False, 'message': '执行时间必须晚于当前时间'}), 400
            except ValueError:
                return jsonify({'success': False, 'message': '执行时间格式无效'}), 400

        existing = conn.execute(
            "SELECT id, is_enabled FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not existing:
            return jsonify({'success': False, 'message': '任务不存在'}), 404

        # 重新计算下次执行时间
        next_run = TaskScheduler.calc_initial_next_run(
            schedule_type, interval_seconds, execute_at or None
        )

        conn.execute(
            "UPDATE scheduled_tasks SET name = ?, command = ?, schedule_type = ?, "
            "interval_seconds = ?, execute_at = ?, next_run_at = ?, task_type = ?, command_id = ? "
            "WHERE id = ?",
            (name, command, schedule_type, interval_seconds,
             execute_at or None, next_run, task_type, command_id, task_id),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return jsonify({
        'success': True, 'message': '任务已更新', 'next_run_at': next_run,
    })


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>/delete',
                    methods=['POST', 'DELETE'])
@login_required
def delete_task(task_id):
    """删除定时任务。

    同时清理关联的执行日志，避免留下孤儿记录。
    """
    _admin_check()
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not existing:
            return jsonify({'success': False, 'message': '任务不存在'}), 404

        # 先删除关联日志，再删除任务本身
        conn.execute(
            "DELETE FROM scheduled_task_logs WHERE task_id = ?", (task_id,)
        )
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({
            'success': False,
            'message': f'删除失败: {e}',
        }), 500
    finally:
        conn.close()

    return jsonify({'success': True, 'message': '任务已删除'})


@scheduled_bp.route('/admin/cmd/scheduled/tasks/<int:task_id>/toggle',
                    methods=['POST'])
@login_required
def toggle_task(task_id):
    """启用/禁用定时任务。"""
    _admin_check()
    conn = get_db()
    try:
        task = conn.execute(
            "SELECT id, is_enabled, schedule_type, interval_seconds, execute_at "
            "FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not task:
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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
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


@scheduled_bp.route('/admin/cmd/scheduled/status')
@login_required
def tasks_status():
    """获取所有任务的最新执行状态（用于前端轮询展示）。

    返回每个任务 id 对应的最近一次执行：success / started_at / duration_seconds。
    """
    _admin_check()
    conn = get_db()
    try:
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
        since = (datetime.datetime.now() - datetime.timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
        recent_counts = conn.execute("""
            SELECT task_id, COUNT(*) AS c
            FROM scheduled_task_logs
            WHERE started_at >= ?
            GROUP BY task_id
        """, (since,)).fetchall()
    finally:
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
        'now': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
