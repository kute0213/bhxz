"""讨论管理路由：帖子列表、编辑、删除、置顶、锁定、分类管理。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, request, redirect, url_for, flash

from core.auth import admin_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp
from services.discussion_service import (
    delete_topic, toggle_pin, toggle_lock,
    create_category, delete_category, get_categories_with_counts,
)
from services.ip import get_client_ip


@admin_bp.route('/admin/discussion')
@admin_required
def admin_discussion():
    user = get_current_user()

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT t.*, u.username,
                      (SELECT COUNT(*) FROM discussion_replies r WHERE r.topic_id = t.id) AS reply_count
               FROM discussion_topics t
               JOIN users u ON t.user_id = u.id
               ORDER BY t.id DESC"""
        ).fetchall()
        topics = [dict(r) for r in rows]

        cats = conn.execute(
            "SELECT id, name FROM discussion_categories ORDER BY sort_order"
        ).fetchall()
        cat_dict = {c['id']: c['name'] for c in cats}
    finally:
        conn.close()

    return render_template('admin/admin_discussion.html', user=user, topics=topics, cat_dict=cat_dict)


@admin_bp.route('/admin/discussion/<int:topic_id>/delete', methods=['POST'])
@admin_required
def admin_delete_topic(topic_id):
    user = get_current_user()

    success, message = delete_topic(topic_id, user['id'], True, get_client_ip())
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_discussion'))


@admin_bp.route('/admin/discussion/<int:topic_id>/toggle-pin', methods=['POST'])
@admin_required
def admin_toggle_pin(topic_id):
    success, message = toggle_pin(topic_id, get_client_ip())
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_discussion'))


@admin_bp.route('/admin/discussion/<int:topic_id>/toggle-lock', methods=['POST'])
@admin_required
def admin_toggle_lock(topic_id):
    success, message = toggle_lock(topic_id, get_client_ip())
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_discussion'))


@admin_bp.route('/admin/discussion/categories', methods=['GET', 'POST'])
@admin_required
def admin_categories():
    user = get_current_user()

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'create':
            success, message = create_category(
                name=request.form.get('name', '').strip(),
                slug=request.form.get('slug', '').strip(),
                admin_user=user,
                ip_address=get_client_ip(),
            )
            flash(message, 'success' if success else 'error')
        elif action == 'delete':
            success, message = delete_category(
                cat_id=request.form.get('category_id', type=int),
                admin_user=user,
                ip_address=get_client_ip(),
            )
            flash(message, 'success' if success else 'error')

    categories = get_categories_with_counts()
    return render_template('admin/admin_discussion_categories.html', user=user, categories=categories)