"""快捷命令 CRUD 路由：列表、创建、更新、删除、执行预设命令。"""

import datetime

from flask import request, jsonify

from core.auth import admin_required
from core.db import get_db
from services.cmd_runner import run_command_sync
from routes.script import script_bp


@script_bp.route('/admin/script/commands', methods=['GET'])
@admin_required
def list_commands():
    conn = get_db()
    try:
        # 按名称自动排序（用户要求自动排列快捷命令顺序）
        commands = conn.execute(
            "SELECT * FROM cmd_commands ORDER BY name ASC, id ASC"
        ).fetchall()
        commands = [dict(c) for c in commands]
    finally:
        conn.close()
    return jsonify({'commands': commands})


@script_bp.route('/admin/script/commands', methods=['POST'])
@admin_required
def create_command():
    data = request.get_json() or request.form
    name = (data.get('name') or '').strip()
    command = (data.get('command') or '').strip()
    description = (data.get('description') or '').strip()
    sort_order = int(data.get('sort_order') or 0)

    if not name or not command:
        return jsonify({'success': False, 'message': '名称和命令不能为空'}), 400

    conn = get_db()
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cmd_commands (name, command, description, sort_order, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, command, description, sort_order, now)
        )
        conn.commit()
        cmd_id = cursor.lastrowid
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return jsonify({'success': True, 'id': cmd_id, 'message': '命令已添加'})


@script_bp.route('/admin/script/commands/<int:cmd_id>', methods=['PUT', 'POST'])
@admin_required
def update_command(cmd_id):
    data = request.get_json() or request.form
    name = (data.get('name') or '').strip()
    command = (data.get('command') or '').strip()
    description = (data.get('description') or '').strip()
    sort_order = int(data.get('sort_order') or 0)

    if not name or not command:
        return jsonify({'success': False, 'message': '名称和命令不能为空'}), 400

    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM cmd_commands WHERE id = ?", (cmd_id,)).fetchone()
        if not existing:
            return jsonify({'success': False, 'message': '命令不存在'}), 404

        conn.execute(
            "UPDATE cmd_commands SET name = ?, command = ?, description = ?, sort_order = ? WHERE id = ?",
            (name, command, description, sort_order, cmd_id)
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

    return jsonify({'success': True, 'message': '命令已更新'})


@script_bp.route('/admin/script/commands/<int:cmd_id>/delete', methods=['POST', 'DELETE'])
@admin_required
def delete_command(cmd_id):
    """删除快捷命令。"""
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM cmd_commands WHERE id = ?", (cmd_id,)).fetchone()
        if not existing:
            return jsonify({'success': False, 'message': '命令不存在'}), 404

        # 检查是否有定时任务引用此快捷命令（command_id 列可能不存在于旧库中）
        referencing_tasks = []
        try:
            referencing_tasks = conn.execute(
                "SELECT id, name FROM scheduled_tasks WHERE command_id = ?",
                (cmd_id,),
            ).fetchall()
        except Exception:
            pass
        if referencing_tasks:
            task_names = ', '.join(
                f"#{t['id']} {t['name']}" for t in referencing_tasks
            )
            return jsonify({
                'success': False,
                'message': f'该快捷命令被 {len(referencing_tasks)} 个定时任务引用'
                           f'（{task_names}），请先删除或修改这些任务后再删除命令',
            }), 400

        conn.execute("DELETE FROM cmd_commands WHERE id = ?", (cmd_id,))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return jsonify({'success': True, 'message': '命令已删除'})


@script_bp.route('/admin/script/run-preset/<int:cmd_id>', methods=['POST'])
@admin_required
def run_preset_command(cmd_id):
    """执行一键命令（同步模式，一次性返回输出）。"""
    conn = get_db()
    try:
        preset = conn.execute("SELECT * FROM cmd_commands WHERE id = ?", (cmd_id,)).fetchone()
    finally:
        conn.close()

    if not preset:
        return jsonify({'success': False, 'message': '命令不存在'}), 404

    result = run_command_sync(preset['command'], timeout=60)
    result['name'] = preset['name']
    return jsonify(result)
