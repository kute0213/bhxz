"""讨论页面路由：帖子列表、详情、创建、编辑。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, request, redirect, url_for, flash, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.discussion import discussion_bp
from config import get_config_value
from services.ip import get_client_ip
from services.discussion_service import (
    get_categories, get_category_dict, get_topics_page, get_topic_detail,
    create_topic, edit_topic,
)


@discussion_bp.route('/discussion', endpoint='list')
def list_view():
    user = get_current_user()
    categories = get_categories()
    category_id = request.args.get('category', type=int)
    page = request.args.get('page', 1, type=int)

    topics, total, total_pages = get_topics_page(category_id, page)

    cat_dict = get_category_dict()
    current_category_name = cat_dict.get(category_id, '') if category_id else ''

    return render_template(
        'discussion/list.html', user=user, topics=topics,
        categories=categories, category_id=category_id,
        current_category_name=current_category_name,
        page=page, total_pages=total_pages, total=total,
    )


@discussion_bp.route('/discussion/create', methods=['GET', 'POST'])
@login_required
def create():
    user = get_current_user()
    categories = get_categories()

    if request.method == 'POST':
        success, message = create_topic(
            user_id=user['id'],
            username=user['username'],
            title=request.form.get('title', '').strip(),
            content=request.form.get('content', '').strip(),
            category_id=request.form.get('category_id', type=int),
            tags=request.form.get('tags', '').strip(),
            attachment_files=request.files.getlist('attachments'),
            ip_address=get_client_ip(),
        )
        if success:
            return redirect(url_for('discussion.list'))
        flash(message, 'error')
        return render_template('discussion/create.html', user=user, categories=categories,
                               title=request.form.get('title', ''),
                               content=request.form.get('content', ''),
                               category_id=request.form.get('category_id', type=int),
                               tags=request.form.get('tags', ''))

    return render_template('discussion/create.html', user=user, categories=categories)


@discussion_bp.route('/discussion/<int:topic_id>')
def detail(topic_id):
    user = get_current_user()
    result = get_topic_detail(topic_id)
    if not result:
        abort(404)

    topic, total_replies, last_reply_id = result

    return render_template(
        'discussion/detail.html', user=user, topic=topic,
        total_replies=total_replies, last_reply_id=last_reply_id,
        discussion_refresh_interval=get_config_value('DISCUSSION_REFRESH_INTERVAL', 5),
        replies_per_page=get_config_value('REPLIES_PER_PAGE', 10),
    )


@discussion_bp.route('/discussion/<int:topic_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(topic_id):
    user = get_current_user()
    categories = get_categories()

    conn = get_db()
    try:
        topic = conn.execute(
            "SELECT * FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()

    if not topic:
        abort(404)
    if topic['user_id'] != user['id'] and not user.get('is_admin'):
        abort(403)

    if request.method == 'POST':
        success, message = edit_topic(
            topic_id=topic_id,
            user_id=user['id'],
            username=user['username'],
            title=request.form.get('title', '').strip(),
            content=request.form.get('content', '').strip(),
            category_id=request.form.get('category_id', type=int),
            tags=request.form.get('tags', '').strip(),
            ip_address=get_client_ip(),
        )
        if success:
            return redirect(url_for('discussion.detail', topic_id=topic_id))
        flash(message, 'error')
        return render_template('discussion/create.html', user=user, categories=categories,
                               topic=topic, title=request.form.get('title', ''),
                               content=request.form.get('content', ''),
                               category_id=request.form.get('category_id', type=int),
                               tags=request.form.get('tags', ''), editing=True)

    return render_template('discussion/create.html', user=user, categories=categories,
                           topic=topic, title=topic['title'], content=topic['content'],
                           category_id=topic['category_id'], tags=topic['tags'], editing=True)