"""音频直播 JSON API：列表、状态、开播、停止、参数调整、WebRTC 推流。"""

from flask import jsonify, request

from core.auth import get_current_user, login_required
from core.shared.ip import get_client_ip
from routes.live import live_bp
from services.live import (
    MODE_LOOP,
    MODE_REC,
    manager,
    store,
    webrtc,
)
from services.live.constants import M3U8_PATH, MP3_PATH, PLAY_PAGE_PATH


def _links(channel_id):
    """直播的三种访问地址（绝对地址，便于前端复制分享）。"""
    base = request.host_url.rstrip('/')
    return {
        'm3u8': base + M3U8_PATH.format(channel_id=channel_id),
        'mp3': base + MP3_PATH.format(channel_id=channel_id),
        'page': base + PLAY_PAGE_PATH.format(channel_id=channel_id),
    }


def _payload(channel, row=None):
    if channel is not None:
        data = channel.state()
    else:
        data = {
            'id': int(row['id']),
            'user_id': int(row['user_id']),
            'username': row.get('username') or '',
            'title': row.get('title') or '',
            'mode': row.get('mode') or MODE_LOOP,
            'volume': row.get('volume'),
            'speed': row.get('speed'),
            'created_at': row.get('created_at') or '',
            'alive': False,
            'listeners': 0,
            'last_error': '',
        }
    data['links'] = _links(data['id'])
    return data


def _json_body():
    return request.get_json(silent=True) or {}


@live_bp.route('/api/live/list')
def api_live_list():
    """正在直播的公开列表。"""
    items = []
    for row in store.get_active_channels():
        channel = manager.get(row['id'])
        if channel is None or not channel.is_live():
            continue
        items.append(_payload(channel, row))
    return jsonify({'success': True, 'channels': items})


@live_bp.route('/api/live/<int:channel_id>')
def api_live_status(channel_id):
    """单个直播状态（播放页轮询使用）。"""
    channel = manager.get(channel_id)
    if channel is not None:
        return jsonify({'success': True, 'channel': _payload(channel)})

    row = store.get_channel(channel_id)
    if not row:
        return jsonify({'success': False, 'message': '直播不存在'}), 404
    return jsonify({
        'success': True,
        'channel': _payload(None, row),
    })


@live_bp.route('/api/live/me')
@login_required
def api_live_me():
    """当前用户的开播状态：封禁信息、正在进行的直播、可选音频。"""
    user = get_current_user()
    ban = store.get_ban(user['id'])
    row = store.get_user_active_channel(user['id'])
    channel = manager.get(row['id']) if row else None
    payload = None
    if row:
        payload = _payload(channel, row) if channel and channel.is_live() \
            else _payload(None, row)

    my_musics = [] if ban else store.get_user_public_musics(user['id'])
    return jsonify({
        'success': True,
        'banned': bool(ban),
        'ban': ban,
        'channel': payload,
        'my_musics': my_musics,
    })


@live_bp.route('/api/live/start', methods=['POST'])
@login_required
def api_live_start():
    """开始直播：循环播放音频或 WebRTC 实时录音。"""
    user = get_current_user()
    data = _json_body()

    title = (data.get('title') or '').strip()
    mode = (data.get('mode') or '').strip()
    if not title:
        return jsonify({'success': False, 'message': '请填写直播标题'}), 400
    if mode not in (MODE_LOOP, MODE_REC):
        return jsonify({'success': False, 'message': '无效的直播模式'}), 400

    # 标题内容注入检测（与音频上传保持一致）
    from services.firewall.protection.content_filter import check_content_injection
    injection = check_content_injection(
        user_id=user['id'], content=title, content_type='live',
        ip_address=get_client_ip(), username=user['username'],
    )
    if injection['blocked']:
        return jsonify({'success': False, 'message': '直播标题包含违规内容'}), 400

    if store.is_banned(user['id']):
        return jsonify({'success': False, 'message': '你已被管理员禁止开播'}), 403

    if mode == MODE_LOOP:
        ok, result = manager.start_loop(
            user['id'], user['username'], title,
            data.get('music_id'),
            volume=data.get('volume'),
            speed=data.get('speed'),
        )
    else:
        ok, result = manager.start_rec(
            user['id'], user['username'], title)

    if not ok:
        return jsonify({'success': False, 'message': result}), 400
    return jsonify({'success': True, 'channel': _payload(
        manager.get(result['id']), result)})


@live_bp.route('/api/live/<int:channel_id>/stop', methods=['POST'])
@login_required
def api_live_stop(channel_id):
    """停止自己（或管理员停止任意）的直播。"""
    user = get_current_user()
    reason = (_json_body().get('reason') or '').strip() or '用户停止直播'
    ok, message = manager.stop(
        channel_id, user_id=user['id'],
        is_admin=bool(user.get('is_admin')), reason=reason)
    return jsonify({'success': ok, 'message': message}), (200 if ok else 400)


@live_bp.route('/api/live/<int:channel_id>/settings', methods=['POST'])
@login_required
def api_live_settings(channel_id):
    """调整循环直播的音量 / 播放速度（实时生效）。"""
    user = get_current_user()
    data = _json_body()
    ok, result = manager.adjust(
        channel_id, user_id=user['id'],
        volume=data.get('volume'),
        speed=data.get('speed'),
        is_admin=bool(user.get('is_admin')),
    )
    if not ok:
        return jsonify({'success': False, 'message': result}), 400
    return jsonify({'success': True, 'channel': _payload(manager.get(channel_id), result)})


@live_bp.route('/api/live/<int:channel_id>/webrtc/offer', methods=['POST'])
@login_required
def api_live_webrtc_offer(channel_id):
    """接收浏览器 SDP offer，返回 answer（实时录音推流）。"""
    user = get_current_user()
    channel = manager.get(channel_id)
    if channel is None:
        return jsonify({'success': False, 'message': '直播不存在或已结束'}), 404
    if channel.user_id != int(user['id']):
        return jsonify({'success': False, 'message': '无权向该直播推流'}), 403
    if channel.mode != MODE_REC:
        return jsonify({'success': False, 'message': '该直播不是实时录音模式'}), 400

    data = _json_body()
    ok, result = webrtc.submit_offer(
        channel, data.get('sdp'), data.get('type'))
    if not ok:
        return jsonify({'success': False, 'message': result}), 400
    return jsonify({'success': True, 'answer': result})
