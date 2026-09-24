"""讨论管理路由：帖子列表、编辑、删除、置顶、锁定、分类管理。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
管理操作统一返回 JSON（前端无刷新），列表页仍为普通页面。
"""

from flask import request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.db import get_db
from routes.admin import admin_bp
from services.discussion import (
    delete_topic, toggle_pin, toggle_lock,
    create_category, delete_category, get_categories_with_counts,
    get_admin_topics_page, get_category_dict,
)
from services.discussion.topics import PAGE_SIZE as TOPIC_PAGE_SIZE
from core.shared.ip import get_client_ip


@admin_bp.route('/admin/discussion')
@admin_required
def admin_discussion():
    """讨论管理页（每次 10 条，加载更多走 API）。"""
    topics, topics_total = get_admin_topics_page(page=1)
    return render_page(
        'admin/discussion.html',
        topics=topics,
        topics_total=topics_total,
        cat_dict=get_category_dict(),
        page_size=TOPIC_PAGE_SIZE,
    )


@admin_bp.route('/admin/discussion/api/list')
@admin_required
def admin_discussion_api_list():
    """帖子列表 JSON API（分页，每次 10 条）。参数：page（从 1 开始）。"""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    items, total = get_admin_topics_page(page=page, page_size=TOPIC_PAGE_SIZE)
    return jsonify({
        'success': True,
        'topics': items,
        'cat_dict': get_category_dict(),
        'page': page,
        'page_size': TOPIC_PAGE_SIZE,
        'total': total,
        'has_more': page * TOPIC_PAGE_SIZE < total,
    })


@admin_bp.route('/admin/discussion/<int:topic_id>/delete', methods=['POST'])
@admin_required
def admin_delete_topic(topic_id):
    """删除帖子（JSON API，前端无刷新）。"""
    user = get_current_user()

    success, message = delete_topic(topic_id, user['id'], True, get_client_ip())
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/discussion/<int:topic_id>/toggle-pin', methods=['POST'])
@admin_required
def admin_toggle_pin(topic_id):
    """置顶 / 取消置顶（JSON API，前端无刷新）。"""
    success, message = toggle_pin(topic_id, get_client_ip())
    data = {'success': success, 'message': message}
    if success:
        # 返回最新状态，供前端局部更新徽章
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT is_pinned FROM discussion_topics WHERE id = ?", (topic_id,)
            ).fetchone()
            data['is_pinned'] = bool(row['is_pinned']) if row else False
        finally:
            conn.close()
    return jsonify(data)


@admin_bp.route('/admin/discussion/<int:topic_id>/toggle-lock', methods=['POST'])
@admin_required
def admin_toggle_lock(topic_id):
    """锁定 / 解锁（JSON API，前端无刷新）。"""
    success, message = toggle_lock(topic_id, get_client_ip())
    data = {'success': success, 'message': message}
    if success:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT is_locked FROM discussion_topics WHERE id = ?", (topic_id,)
            ).fetchone()
            data['is_locked'] = bool(row['is_locked']) if row else False
        finally:
            conn.close()
    return jsonify(data)


@admin_bp.route('/admin/discussion/categories')
@admin_required
def admin_categories():
    """分类管理页（增删经 JSON API 完成，无刷新）。"""
    categories = get_categories_with_counts()
    return render_page('admin/discussion_categories.html', categories=categories)


@admin_bp.route('/admin/discussion/categories/create', methods=['POST'])
@admin_required
def admin_category_create():
    """新建分类（JSON API，前端无刷新）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or request.form.get('name') or '').strip()
    slug = (data.get('slug') or request.form.get('slug') or '').strip()
    success, message = create_category(
        name=name,
        slug=slug,
        admin_user=user,
        ip_address=get_client_ip(),
    )
    result = {'success': success, 'message': message}
    if success:
        # 回传新建分类信息，供前端插入表格行（无需刷新页面）
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id, name, slug FROM discussion_categories WHERE slug = ?",
                (slug,),
            ).fetchone()
            if row:
                result['category'] = dict(row)
        finally:
            conn.close()
    return jsonify(result)


@admin_bp.route('/admin/discussion/categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def admin_category_delete(cat_id):
    """删除分类（JSON API，前端无刷新）。"""
    user = get_current_user()
    success, message = delete_category(
        cat_id=cat_id,
        admin_user=user,
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})
