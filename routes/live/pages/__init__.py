"""音频直播页面路由：直播台与独立播放页。

播放页地址格式：/live/play.html?channelId=<直播ID>
"""

from flask import abort, request

from core.auth import get_current_user
from core.helpers import render_page
from routes.live import live_bp
from services.live import manager, store


@live_bp.route('/live')
def live_page():
    """音频直播台：正在直播列表 + 开播 / 我的直播入口。"""
    user = get_current_user()
    is_banned = bool(user and store.is_banned(user['id']))
    return render_page(
        'live/index.html',
        is_banned=is_banned,
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
