"""访问日志路由：分页查看、清空。"""

from flask import render_template, redirect, url_for, flash, abort, request

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin/logs')
@login_required
def admin_logs():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page

        total = conn.execute("SELECT COUNT(*) AS c FROM access_logs").fetchone()['c']
        total_pages = (total + per_page - 1) // per_page

        logs = conn.execute("""
            SELECT * FROM access_logs
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        logs = [dict(log) for log in logs]
    finally:
        conn.close()

    return render_template(
        'admin/admin_logs.html',
        user=user,
        logs=logs,
        page=page,
        total_pages=total_pages,
        total=total
    )


@admin_bp.route('/admin/logs/clear', methods=['POST'])
@login_required
def admin_logs_clear():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        try:
            conn.execute("DELETE FROM access_logs")
            conn.commit()
        except:
            conn.rollback()
    finally:
        conn.close()
    flash('访问日志已清空', 'success')
    return redirect(url_for('admin.admin_logs'))
