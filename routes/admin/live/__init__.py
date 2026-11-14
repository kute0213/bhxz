"""音频直播管理：查看直播、强制停止、永久封禁 / 解封。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import jsonify, request

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from routes.admin import admin_bp
from services.live import manager, store


def _live_payload(channel, row=None):
    if channel is not None:
        data = channel.state()
    else:
        data = {
            'id': int(row['id']),
            'user_id': int(row['user_id']),
            'username': row.get('username') or '',
            'title': row.get('title') or '',
            'volume': row.get('volume'),
            'speed': row.get('speed'),
            'created_at': row.get('created_at') or '',
            'alive': False,
            'listeners': 0,
            'last_error': '',
        }
    return data


def _active_payloads():
    items = []
    for row in store.get_active_channels():
        channel = manager.get(row['id'])
        items.append(_live_payload(channel, row))
    return items


@admin_bp.route('/admin/live')
@admin_required
def admin_live_page():
    """音频直播管理页：正在直播、封禁名单。"""
    return render_page(
        'admin/live.html',
        active_channels=_active_payloads(),
        bans=store.list_bans(),
        recent_channels=store.get_all_channels(limit=50),
    )


@admin_bp.route('/admin/api/live/list')
@admin_required
def admin_live_api_list():
    """直播列表 JSON（正在直播 + 最近记录 + 封禁名单）。"""
    return jsonify({
        'success': True,
        'active': _active_payloads(),
        'recent': store.get_all_channels(limit=50),
        'bans': store.list_bans(),
    })


@admin_bp.route('/admin/api/live/<int:channel_id>/stop', methods=['POST'])
@admin_required
def admin_live_stop(channel_id):
    """管理员强制停止某个直播。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip() or '管理员强制停止'
    ok, message = manager.stop(
        channel_id, user_id=user['id'], is_admin=True, reason=reason)
    return jsonify({'success': ok, 'message': message}), (200 if ok else 400)


@admin_bp.route('/admin/api/live/ban', methods=['POST'])
@admin_required
def admin_live_ban():
    """永久禁止某用户开播，并强制停止其正在进行的直播。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    reason = (data.get('reason') or '').strip()

    target = store.find_user_by_username(username)
    if not target:
        return jsonify({'success': False, 'message': '未找到该用户'}), 404
    if target['id'] == user['id']:
        return jsonify({'success': False, 'message': '不能封禁自己'}), 400

    store.ban_user(target['id'], target['username'], reason, user['id'])

    row = store.get_user_active_channel(target['id'])
    if row:
        manager.stop(row['id'], user_id=user['id'], is_admin=True,
                     reason='管理员禁止开播')

    return jsonify({
        'success': True,
        'message': f'已禁止 {target["username"]} 开播',
    })


@admin_bp.route('/admin/api/live/unban', methods=['POST'])
@admin_required
def admin_live_unban():
    """解除某用户的直播封禁。"""
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '无效的用户 ID'}), 400

    ok, message = store.unban_user(target_id)
    return jsonify({'success': ok, 'message': message}), (200 if ok else 400)
