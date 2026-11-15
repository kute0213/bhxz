"""音频直播页面路由：直播台、开播页、我的直播、实时录音台与独立播放页。

播放页地址格式：/live/play.html?channelId=<直播ID>
"""

from flask import abort, request

from core.auth import get_current_user, login_required
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


@live_bp.route('/live/start')
@login_required
def live_start_page():
    """独立的「开始直播」页面：循环播放 / 实时录音。"""
    user = get_current_user()
    is_banned = bool(user and store.is_banned(user['id']))
    return render_page(
        'live/start.html',
        is_banned=is_banned,
    )


@live_bp.route('/live/my')
@login_required
def live_my_page():
    """独立的「我的直播」页面：管理全部进行中的直播。"""
    user = get_current_user()
    return render_page(
        'live/my.html',
        is_banned=bool(user and store.is_banned(user['id'])),
    )


@live_bp.route('/live/rec/<int:channel_id>')
@login_required
def live_rec_page(channel_id):
    """实时录音直播台：连接麦克风并实时调整录音参数。"""
    user = get_current_user()
    row = store.get_channel(channel_id)
    if not row or (row.get('mode') or 'loop') != 'rec':
        abort(404)
    if row['user_id'] != user['id'] and not user.get('is_admin'):
        abort(403)

    channel = manager.get(channel_id)
    info = channel.state() if channel else {
        'id': row['id'],
        'user_id': row['user_id'],
        'username': row['username'],
        'title': row['title'],
        'mode': 'rec',
        'mode_label': '实时录音',
        'music_id': None,
        'volume': row.get('volume'),
        'speed': row.get('speed'),
        'created_at': row.get('created_at') or '',
        'alive': False,
        'listeners': 0,
        'last_error': '',
    }
    return render_page(
        'live/rec.html',
        channel=info,
        channel_id=channel_id,
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
                'mode': row.get('mode') or 'loop',
                'mode_label': '实时录音' if row.get('mode') == 'rec' else '循环播放',
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
