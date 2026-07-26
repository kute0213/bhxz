"""CMD 页面路由：命令控制台首页、脚本编辑器。"""

from flask import render_template, request

from core.auth import login_required
from core.db import get_db
from services.script_manager import get_script, list_scripts
from routes.cmd import cmd_bp
from routes.cmd.script import _admin_check


@cmd_bp.route('/admin/cmd')
@login_required
def cmd_page():
    user = _admin_check()
    conn = get_db()
    # 从数据库读取 shell 快捷命令（非脚本类型）
    all_commands = conn.execute(
        "SELECT * FROM cmd_commands ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    all_commands = [dict(c) for c in all_commands]
    conn.close()

    # 筛选出 shell 命令（描述不以 [脚本] 开头的）
    shell_commands = [
        c for c in all_commands
        if not (c.get('description') or '').startswith('[脚本]')
    ]

    # 从文件系统读取脚本列表
    scripts = list_scripts()

    return render_template(
        'admin_cmd.html',
        user=user,
        commands=shell_commands,
        scripts=scripts,
    )


@cmd_bp.route('/admin/cmd/editor')
@login_required
def cmd_editor_page():
    """独立脚本编辑器页面：支持语法高亮、代码补全、错误诊断、测试运行、保存为快捷命令。

    支持两种加载方式：
    - ?file=xxx.py 从文件系统加载脚本
    - ?edit=N 从数据库加载（兼容旧链接）
    """
    user = _admin_check()
    filename = request.args.get('file', '').strip()
    edit_id = request.args.get('edit', type=int)
    conn = get_db()

    editing_script = None
    editing_cmd = None

    # 优先从文件系统加载
    if filename:
        script_info = get_script(filename)
        if script_info:
            editing_script = script_info
    # 兼容旧的 edit 参数（从数据库加载）
    elif edit_id:
        row = conn.execute("SELECT * FROM cmd_commands WHERE id = ?", (edit_id,)).fetchone()
        if row:
            editing_cmd = dict(row)

    conn.close()
    return render_template(
        'admin_cmd_editor.html',
        user=user,
        editing_cmd=editing_cmd,
        editing_script=editing_script,
    )
