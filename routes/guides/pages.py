"""服务器指南公开页面：列表、详情。"""

from flask import render_template, abort

from core.auth import get_current_user
from core.db import get_db
from routes.guides import guides_bp


@guides_bp.route('/guides')
def guide_list():
    """公开指南列表页（默认展示已审核通过的；?my=1 展示当前用户的）。"""
    from flask import request
    user = get_current_user()
    conn = get_db()
    try:
        if user and request.args.get('my'):
            rows = conn.execute(
                """
                SELECT g.*, u.username as author_name
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.author_id = ?
                ORDER BY g.updated_at DESC
                """,
                (user['id'],),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT g.*, u.username as author_name
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.status = 'approved'
                ORDER BY g.is_pinned DESC, g.sort_order ASC, g.published_at DESC
                """
            ).fetchall()
        guides = [dict(r) for r in rows]
    finally:
        conn.close()

    return render_template('guides/index.html', user=user, guides=guides, my_mode=bool(user and request.args.get('my')))


@guides_bp.route('/guides/<slug>')
def guide_detail(slug):
    """公开指南详情页（仅展示已审核通过的）。"""
    user = get_current_user()
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT g.*, u.username as author_name
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            WHERE g.slug = ? AND g.status = 'approved'
            """,
            (slug,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    guide = dict(row)
    return render_template('guides/detail.html', user=user, guide=guide)
