"""快捷命令 CRUD 路由：列表、创建、更新、删除、执行预设命令。"""

import datetime

from flask import request, jsonify

from core.auth import login_required
from core.db import get_db
from services.cmd_runner import run_command_sync
from routes.cmd import cmd_bp
from routes.cmd.script import _admin_check


@cmd_bp.route('/admin/cmd/commands', methods=['GET'])
@login_required
def list_commands():
    _admin_check()
    conn = get_db()
    commands = conn.execute(
        "SELECT * FROM cmd_commands ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    commands = [dict(c) for c in commands]
    conn.close()
    return jsonify({'commands': commands})


@cmd_bp.route('/admin/cmd/commands', methods=['POST'])
@login_required
def create_command():
    _admin_check()
    data = request.get_json() or request.form
    name = (data.get('name') or '').strip()
    command = (data.get('command') or '').strip()
    description = (data.get('description') or '').strip()
    sort_order = int(data.get('sort_order') or 0)

    if not name or not command:
        return jsonify({'success': False, 'message': '名称和命令不能为空'}), 400

    conn = get_db()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cmd_commands (name, command, description, sort_order, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, command, description, sort_order, now)
    )
    conn.commit()
    cmd_id = cursor.lastrowid
    conn.close()

    return jsonify({'success': True, 'id': cmd_id, 'message': '命令已添加'})


@cmd_bp.route('/admin/cmd/commands/<int:cmd_id>', methods=['PUT', 'POST'])
@login_required
def update_command(cmd_id):
    _admin_check()
    data = request.get_json() or request.form
    name = (data.get('name') or '').strip()
    command = (data.get('command') or '').strip()
    description = (data.get('description') or '').strip()
    sort_order = int(data.get('sort_order') or 0)

    if not name or not command:
        return jsonify({'success': False, 'message': '名称和命令不能为空'}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM cmd_commands WHERE id = ?", (cmd_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'message': '命令不存在'}), 404

    conn.execute(
        "UPDATE cmd_commands SET name = ?, command = ?, description = ?, sort_order = ? WHERE id = ?",
        (name, command, description, sort_order, cmd_id)
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': '命令已更新'})


@cmd_bp.route('/admin/cmd/commands/<int:cmd_id>/delete', methods=['POST', 'DELETE'])
@login_required
def delete_command(cmd_id):
    _admin_check()
    conn = get_db()
    existing = conn.execute("SELECT id FROM cmd_commands WHERE id = ?", (cmd_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'message': '命令不存在'}), 404

    conn.execute("DELETE FROM cmd_commands WHERE id = ?", (cmd_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': '命令已删除'})


@cmd_bp.route('/admin/cmd/run-preset/<int:cmd_id>', methods=['POST'])
@login_required
def run_preset_command(cmd_id):
    """执行一键命令（同步模式，一次性返回输出）。"""
    _admin_check()
    conn = get_db()
    preset = conn.execute("SELECT * FROM cmd_commands WHERE id = ?", (cmd_id,)).fetchone()
    conn.close()

    if not preset:
        return jsonify({'success': False, 'message': '命令不存在'}), 404

    result = run_command_sync(preset['command'], timeout=60)
    result['name'] = preset['name']
    return jsonify(result)
