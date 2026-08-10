"""征集路由：创建主题、回复、删除主题/回复。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import request, abort

from core.auth import login_required, get_current_user
from routes.community import community_bp
from routes.community.helpers import _respond
from services.board_service import create_topic, reply_to_topic, delete_topic, delete_reply


@community_bp.route('/board/create', methods=['POST'])
@login_required
def create_board_topic():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = create_topic(
        user_id=user['id'],
        username=user['username'],
        title=request.form.get('title', '').strip(),
        description=request.form.get('description', '').strip(),
        ip_address=request.remote_addr,
    )
    return _respond(message, 'success' if success else 'error')


@community_bp.route('/board/<int:topic_id>/reply', methods=['POST'])
@login_required
def reply_board(topic_id):
    user = get_current_user()
    success, message = reply_to_topic(
        user_id=user['id'],
        username=user['username'],
        topic_id=topic_id,
        content=request.form.get('content', '').strip(),
        attachment_files=request.files.getlist('attachments'),
        ip_address=request.remote_addr,
    )
    return _respond(message, 'success' if success else 'error')


@community_bp.route('/board/<int:topic_id>/delete', methods=['POST'])
@login_required
def delete_board_topic(topic_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = delete_topic(topic_id, request.remote_addr)
    return _respond(message, 'success' if success else 'error')


@community_bp.route('/board/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_board_reply(reply_id):
    user = get_current_user()
    success, message = delete_reply(
        reply_id=reply_id,
        user_id=user['id'],
        is_admin=user.get('is_admin', False),
        ip_address=request.remote_addr,
    )
    return _respond(message, 'success' if success else 'error')