"""终端控制台页面路由。"""

from flask import render_template

from core.auth import admin_required, get_current_user
from core.db import get_db
from routes.script import script_bp


@script_bp.route('/admin/script')
@admin_required
def script_page():
    user = get_current_user()
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
@admin_required
def terminal_page():
    """独立实时终端页面。"""
    return render_template('admin/admin_terminal_page.html', user=get_current_user())