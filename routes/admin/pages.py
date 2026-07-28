"""管理后台页面路由：仪表盘。"""

from flask import render_template, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin')
@login_required
def admin_page():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        stats = {
            'total_users': conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c'],
            'total_polls': conn.execute("SELECT COUNT(*) AS c FROM polls").fetchone()['c'],
            'total_votes': conn.execute("SELECT COUNT(*) AS c FROM poll_votes").fetchone()['c'],
            'total_board_topics': conn.execute("SELECT COUNT(*) AS c FROM board_topics").fetchone()['c'],
            'total_board_replies': conn.execute("SELECT COUNT(*) AS c FROM board_replies").fetchone()['c'],
            'total_mod_intros': conn.execute("SELECT COUNT(*) AS c FROM mod_intros").fetchone()['c'],
            'total_guides': conn.execute("SELECT COUNT(*) AS c FROM server_guides").fetchone()['c'],
            'pending_guides': conn.execute("SELECT COUNT(*) AS c FROM server_guides WHERE status = 'pending'").fetchone()['c'],
        }
    finally:
        conn.close()

    return render_template('admin.html', user=user, stats=stats)
