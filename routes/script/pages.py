"""CMD 页面路由：命令控制台首页、脚本编辑器。"""

from flask import render_template, request

from core.auth import login_required
from core.db import get_db
from routes.script import script_bp
from routes.script.common import _admin_check


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

    # 筛选出 shell 命令（描述不以 [脚本] 开头的）
    shell_commands = [
        c for c in all_commands
        if not (c.get('description') or '').startswith('[脚本]')
    ]

    return render_template(
        'admin/admin_script.html',
        user=user,
        commands=shell_commands,
    )


@script_bp.route('/admin/script/terminal-page')
@login_required
def terminal_page():
    """独立实时终端页面。"""
    user = _admin_check()
    return render_template('admin/admin_terminal_page.html', user=user)


@script_bp.route('/admin/script/editor')
@login_required
def script_editor_page():
    """独立脚本编辑器页面。

    支持加载方式：
    - ?id=N 从统一脚本系统加载（scripts 表）
    - ?edit=N 从数据库 cmd_commands 加载（兼容旧链接）
    """
    user = _admin_check()
    script_id = request.args.get('id', type=int)
    edit_id = request.args.get('edit', type=int)

    editing_script = None
    editing_cmd = None

    # 1. 从统一脚本系统加载
    if script_id:
        from services.script_store import get_script as get_script_from_store
        script_info = get_script_from_store(script_id)
        if script_info:
            editing_script = script_info
    # 2. 兼容旧的 edit 参数（从 cmd_commands 加载）
    elif edit_id:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM cmd_commands WHERE id = ?", (edit_id,)).fetchone()
            if row:
                editing_cmd = dict(row)
        finally:
            conn.close()

    return render_template(
        'admin/admin_script_editor.html',
        user=user,
        editing_cmd=editing_cmd,
        editing_script=editing_script,
    )
