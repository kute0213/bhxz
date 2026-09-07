"""终端控制台页面路由。"""

from core.auth import admin_required
from core.helpers import render_page
from core.db import get_db
from routes.script import script_bp


@script_bp.route('/admin/script')
@admin_required
def script_page():
    conn = get_db()
    try:
        # 从数据库读取 shell 快捷命令，按名称自动排序
        all_commands = conn.execute(
            "SELECT * FROM cmd_commands ORDER BY name ASC, id ASC"
        ).fetchall()
        all_commands = [dict(c) for c in all_commands]
    finally:
        conn.close()

    return render_page(
        'admin/admin_script.html',
        commands=all_commands,
    )


