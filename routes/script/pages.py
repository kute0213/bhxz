"""终端控制台页面路由。"""

from flask import render_template

from core.auth import login_required
from core.db import get_db
from routes.script import script_bp
from routes.script.terminal import _admin_check


@script_bp.route('/admin/script')
@login_required
def script_page():
    user = _admin_check()
    conn = get_db()
    try:
        # 从数据库读取 shell 快捷命令，按名称自动排序
        all_commands = conn.execute(
            "SELECT * FROM cmd_commands ORDER BY name ASC, id ASC"
        ).fetchall()
        all_commands = [dict(c) for c in all_commands]
    finally:
        conn.close()

    return render_template(
        'admin/admin_script.html',
        user=user,
        commands=all_commands,
    )


@script_bp.route('/admin/script/terminal-page')
@login_required
def terminal_page():
    """独立实时终端页面。"""
    user = _admin_check()
    return render_template('admin/admin_terminal_page.html', user=user)