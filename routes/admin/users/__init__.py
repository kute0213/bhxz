"""用户管理路由：用户列表、切换管理员、删除用户。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import jsonify, request

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.db import get_db
from routes.admin import admin_bp
from services.user import admin_delete_user as _svc_delete_user, admin_toggle_admin as _svc_toggle_admin
from core.shared.ip import get_client_ip


PAGE_SIZE = 10


def _fetch_users_page(page, page_size=PAGE_SIZE):
    """分页查询用户列表（ORDER BY id DESC），返回 (users, total)。"""
    page = max(1, int(page or 1))
    offset = (page - 1) * page_size

    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
        rows = conn.execute(
            "SELECT id, username, avatar_key, is_admin, created_at FROM users "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        users = [dict(u) for u in rows]
    finally:
        conn.close()

    return users, total


@admin_bp.route('/admin/users')
@admin_required
def admin_users():
    """用户管理页（首屏 10 条，加载更多走 API）。"""
    users_list, total = _fetch_users_page(1)

    return render_page(
        'admin/users.html',
        users_list=users_list,
        total=total,
        page_size=PAGE_SIZE,
        has_more=total > PAGE_SIZE,
    )


@admin_bp.route('/admin/users/api/list')
@admin_required
def admin_users_api():
    """用户列表 API（JSON，分页，每次 10 条）。"""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    users, total = _fetch_users_page(page)

    return jsonify({
        'success': True,
        'users': users,
        'page': page,
        'page_size': PAGE_SIZE,
        'total': total,
        'has_more': page * PAGE_SIZE < total,
    })


@admin_bp.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(user_id):
    """切换用户管理员权限（JSON API，前端无刷新）。"""
    user = get_current_user()

    success, message = _svc_toggle_admin(user, user_id, get_client_ip())
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """删除用户（JSON API，前端无刷新）。"""
    user = get_current_user()

    success, message = _svc_delete_user(user, user_id, get_client_ip())
    return jsonify({'success': success, 'message': message})
