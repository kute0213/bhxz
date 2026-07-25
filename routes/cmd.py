"""CMD 命令控制台：实时执行 + 一键命令管理。

所有接口仅管理员可用。
"""

import datetime
import json
from flask import (
    Blueprint, render_template, request, jsonify,
    Response, abort, stream_with_context
)
from core.auth import login_required, get_current_user
from core.database import get_db
from services.cmd_runner import run_command_stream, run_command_sync

cmd_bp = Blueprint('cmd', __name__)


def _admin_check():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return user


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

@cmd_bp.route('/admin/cmd')
@login_required
def cmd_page():
    user = _admin_check()
    conn = get_db()
    commands = conn.execute(
        "SELECT * FROM cmd_commands ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    commands = [dict(c) for c in commands]
    conn.close()
    return render_template('admin_cmd.html', user=user, commands=commands)


@cmd_bp.route('/admin/cmd/editor')
@login_required
def cmd_editor_page():
    """独立脚本编辑器页面：支持语法高亮、代码补全、错误诊断、测试运行、保存为快捷命令。"""
    user = _admin_check()
    edit_id = request.args.get('edit', type=int)
    conn = get_db()
    editing_cmd = None
    if edit_id:
        row = conn.execute("SELECT * FROM cmd_commands WHERE id = ?", (edit_id,)).fetchone()
        if row:
            editing_cmd = dict(row)
    conn.close()
    return render_template('admin_cmd_editor.html', user=user, editing_cmd=editing_cmd)


# ---------------------------------------------------------------------------
# 一键命令管理
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 命令执行
# ---------------------------------------------------------------------------

@cmd_bp.route('/admin/cmd/run', methods=['POST'])
@login_required
def run_cmd_sync():
    """同步执行命令，一次性返回全部输出。"""
    _admin_check()
    data = request.get_json() or request.form
    command = (data.get('command') or '').strip()
    timeout = int(data.get('timeout') or 30)

    if not command:
        return jsonify({'success': False, 'message': '命令不能为空'}), 400

    if timeout > 600:
        timeout = 600

    result = run_command_sync(command, timeout=timeout)
    return jsonify(result)


@cmd_bp.route('/admin/cmd/run-stream', methods=['GET', 'POST'])
@login_required
def run_cmd_stream():
    """流式执行命令，通过 SSE 实时返回输出。"""
    _admin_check()

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
