"""用户管理路由：用户列表、切换管理员、删除用户。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, redirect, url_for, flash, abort, request

from core.auth import admin_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp
from services.user_service import admin_delete_user as _svc_delete_user, admin_toggle_admin as _svc_toggle_admin
from services.ip import get_client_ip


@admin_bp.route('/admin/users')
@admin_required
def admin_users():
    user = get_current_user()

    conn = get_db()
    try:
        users_list = conn.execute(
            "SELECT id, username, avatar_key, is_admin, created_at FROM users ORDER BY id DESC"
        ).fetchall()
        users_list = [dict(u) for u in users_list]
    finally:
        conn.close()

    return render_template('admin/admin_users.html', user=user, users_list=users_list)


@admin_bp.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(user_id):
    user = get_current_user()

    success, message = _svc_toggle_admin(user, user_id, get_client_ip())
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = get_current_user()

    success, message = _svc_delete_user(user, user_id, get_client_ip())
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_users'))
