"""音频直播页面路由：直播台与独立播放页。

播放页地址格式：/live/play.html?channelId=<直播ID>
"""

from flask import abort, request

from config import (
    LIVE_STUN_SERVERS,
    LIVE_TURN_PASSWORD,
    LIVE_TURN_URL,
    LIVE_TURN_USERNAME,
)
from core.auth import get_current_user
from core.helpers import render_page
from routes.live import live_bp
from services.live import manager, store


def _client_ice_servers():
    """下发到浏览器的 ICE 服务器配置（TURN 凭据本就由浏览器持有）。"""
    servers = [{'urls': url} for url in LIVE_STUN_SERVERS]
    if LIVE_TURN_URL:
        servers.append({
            'urls': LIVE_TURN_URL,
            'username': LIVE_TURN_USERNAME,
            'credential': LIVE_TURN_PASSWORD,
        })
    return servers


@live_bp.route('/live')
def live_page():
    """音频直播台：正在直播列表 + 我的开播控制台。"""
    user = get_current_user()
    is_banned = bool(user and store.is_banned(user['id']))
    my_musics = []
    if user and not is_banned:
        my_musics = store.get_user_public_musics(user['id'])
    return render_page(
        'live/index.html',
        is_banned=is_banned,
        my_musics=my_musics,
        ice_servers=_client_ice_servers(),
    )


@live_bp.route('/live/play.html')
def live_play_page():
    """独立播放页：通过 channelId 收听指定直播。"""
    channel_id = request.args.get('channelId', type=int)
    if not channel_id:
        abort(404)

    channel = manager.get(channel_id)
    info = channel.state() if channel else None
    if info is None:
        row = store.get_channel(channel_id)
        if row and row['status'] == 'live':
            info = {
                'id': row['id'],
                'user_id': row['user_id'],
                'username': row['username'],
                'title': row['title'],
                'mode': row['mode'],
                'volume': row['volume'],
                'speed': row['speed'],
                'created_at': row['created_at'],
                'alive': False,
                'listeners': 0,
                'last_error': '',
            }

    return render_page(
        'live/play.html',
        channel_id=channel_id,
        channel=info,
    )
