"""投票管理路由：创建、投票、删除、启停。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import request, abort

from core.auth import login_required, get_current_user
from routes.community import community_bp
from routes.community.helpers import _respond
from services.poll_service import create_poll, vote_poll, delete_poll, toggle_poll


@community_bp.route('/poll/create', methods=['POST'])
@login_required
def create_poll_view():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = create_poll(
        user_id=user['id'],
        username=user['username'],
        title=request.form.get('title', '').strip(),
        description=request.form.get('description', '').strip(),
        options_text=request.form.get('options', '').strip(),
        is_multiple=1 if request.form.get('is_multiple') == '1' else 0,
        ip_address=request.remote_addr,
    )
    return _respond(message, 'success' if success else 'error')


@community_bp.route('/poll/<int:poll_id>/vote', methods=['POST'])
@login_required
def vote_poll_view(poll_id):
    user = get_current_user()
    success, message = vote_poll(
        poll_id=poll_id,
        user_id=user['id'],
        username=user['username'],
        option_ids=request.form.getlist('option_id'),
        ip_address=request.remote_addr,
    )
    return _respond(message, 'success' if success else 'error')


@community_bp.route('/poll/<int:poll_id>/delete', methods=['POST'])
@login_required
def delete_poll_view(poll_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = delete_poll(poll_id, request.remote_addr)
    return _respond(message, 'success' if success else 'error')


@community_bp.route('/poll/<int:poll_id>/toggle', methods=['POST'])
@login_required
def toggle_poll_view(poll_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = toggle_poll(poll_id, request.remote_addr)
    return _respond(message, 'success' if success else 'error')