"""讨论 API 路由：回复、删除、置顶、锁定、分页获取回复。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import request, abort, url_for, jsonify

from core.auth import login_required, get_current_user
from routes.discussion import discussion_bp
from routes.community.helpers import _respond
from core.shared.ip import get_client_ip
from services.discussion import (
    reply_to_topic,
    delete_reply as svc_delete_reply,
    toggle_pin as svc_toggle_pin,
    toggle_lock as svc_toggle_lock,
    delete_topic as svc_delete_topic,
    get_replies_page, get_new_replies,
)


@discussion_bp.route('/discussion/<int:topic_id>/reply', methods=['POST'])
@login_required
def reply(topic_id):
    user = get_current_user()
    from routes.firewall.spam import check_spam, record_activity
    from routes.firewall.content_filter import check_content_injection
    content = request.form.get('content', '').strip()
    # 内容注入检测
    inj_result = check_content_injection(
        user_id=user['id'], content=content,
        content_type='discussion_reply', ip_address=get_client_ip(),
        username=user['username'],
    )
    if inj_result['blocked']:
        return _respond(inj_result['message'], 'error',
                        redirect_to=url_for('discussion.detail', topic_id=topic_id))
    if check_spam(user_id=user['id'], content_type='discussion_reply', content=content):
        return _respond('发布过于频繁，请稍后再试', 'error',
                        redirect_to=url_for('discussion.detail', topic_id=topic_id))
    success, message = reply_to_topic(
        user_id=user['id'],
        username=user['username'],
        topic_id=topic_id,
        content=content,
        attachment_files=request.files.getlist('attachments'),
        ip_address=get_client_ip(),
    )
    if success:
        record_activity(user_id=user['id'], content_type='discussion_reply', content=content)
    return _respond(message, 'success' if success else 'error',
                    redirect_to=url_for('discussion.detail', topic_id=topic_id))


@discussion_bp.route('/discussion/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_reply(reply_id):
    user = get_current_user()
    success, message = svc_delete_reply(
        reply_id=reply_id,
        user_id=user['id'],
        is_admin=user.get('is_admin', False),
        ip_address=get_client_ip(),
    )
    return _respond(message, 'success' if success else 'error')


@discussion_bp.route('/discussion/<int:topic_id>/pin', methods=['POST'])
@login_required
def toggle_pin(topic_id):
    user = get_current_user()
    if not user.get('is_admin'):
        abort(403)
    success, message = svc_toggle_pin(topic_id, get_client_ip())
    return _respond(message, 'success' if success else 'error',
                    redirect_to=url_for('discussion.detail', topic_id=topic_id))


@discussion_bp.route('/discussion/<int:topic_id>/lock', methods=['POST'])
@login_required
def toggle_lock(topic_id):
    user = get_current_user()
    if not user.get('is_admin'):
        abort(403)
    success, message = svc_toggle_lock(topic_id, get_client_ip())
    return _respond(message, 'success' if success else 'error',
                    redirect_to=url_for('discussion.detail', topic_id=topic_id))


@discussion_bp.route('/discussion/<int:topic_id>/delete', methods=['POST'])
@login_required
def delete_topic(topic_id):
    user = get_current_user()
    success, message = svc_delete_topic(
        topic_id=topic_id,
        caller_user_id=user['id'],
        is_admin=user.get('is_admin', False),
        ip_address=get_client_ip(),
    )
    return _respond(message, 'success' if success else 'error',
                    redirect_to=url_for('discussion.list'))


@discussion_bp.route('/discussion/<int:topic_id>/api/replies')
def api_get_replies(topic_id):
    page = request.args.get('page', 1, type=int)
    data = get_replies_page(topic_id, page)
    return jsonify({'success': True, **data})


@discussion_bp.route('/discussion/<int:topic_id>/api/new-replies')
def api_get_new_replies(topic_id):
    last_id = request.args.get('last_id', 0, type=int)
    replies = get_new_replies(topic_id, last_id)
    return jsonify({'success': True, 'replies': replies})