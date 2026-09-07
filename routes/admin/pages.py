"""管理后台页面路由：仪表盘。"""

from flask import abort

from core.auth import admin_required
from core.helpers import render_page
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin')
@admin_required
def admin_page():
    conn = get_db()
    try:
        stats = {
            'total_users': conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c'],
            'total_music': conn.execute("SELECT COUNT(*) AS c FROM music").fetchone()['c'],
            'pending_music': conn.execute("SELECT COUNT(*) AS c FROM music WHERE status = 1").fetchone()['c'],
            'total_mod_intros': conn.execute("SELECT COUNT(*) AS c FROM mod_intros").fetchone()['c'],
            'total_guides': conn.execute("SELECT COUNT(*) AS c FROM server_guides").fetchone()['c'],
            'pending_guides': conn.execute("SELECT COUNT(*) AS c FROM server_guides WHERE status = 'pending'").fetchone()['c'],
            'total_discussion_topics': conn.execute("SELECT COUNT(*) AS c FROM discussion_topics").fetchone()['c'],
            'total_discussion_replies': conn.execute("SELECT COUNT(*) AS c FROM discussion_replies").fetchone()['c'],
            'total_discussion_categories': conn.execute("SELECT COUNT(*) AS c FROM discussion_categories").fetchone()['c'],
            'total_backgrounds': conn.execute("SELECT COUNT(*) AS c FROM backgrounds").fetchone()['c'],
            'pending_backgrounds': conn.execute("SELECT COUNT(*) AS c FROM backgrounds WHERE status = 0").fetchone()['c'],
        }
    finally:
        conn.close()

    return render_page('admin/admin.html', stats=stats)
