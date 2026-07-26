"""CMD 页面路由：命令控制台首页、脚本编辑器。"""

from flask import render_template, request

from core.auth import login_required
from core.db import get_db
from routes.cmd import cmd_bp
from routes.cmd.script import _admin_check


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
