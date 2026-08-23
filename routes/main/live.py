"""大喇叭直播台路由：直播台页面、开播/结束/推流、每路直播 m3u8 与分片输出。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services.live_service。
支持多路主播同时直播，每路拥有独立播放链接：
    /music/live/<直播ID>/playlist.m3u8   （标准 HLS 直播流，游戏端周期性拉取即可实时播放）
    /music/live/<直播ID>/<分片文件名>      （该路 TS 分片）
"""

import os

from flask import (
    render_template, redirect, url_for, flash, request, abort, jsonify, send_file,
)

from core.auth import login_required, get_current_user
from routes.main import main_bp
from services.live_service import live_service


@main_bp.route('/music/live')
def live_page():
    """实时直播台页面：所有正在直播的主播列表 + 开播/收听入口。"""
    user = get_current_user()
    status = live_service.get_status()
    my_live = live_service.get_user_broadcast(user) if user else None
    return render_template(
        'music/live.html',
        user=user,
        live=status,
        broadcasts=status.get('broadcasts', []),
        my_live=my_live,
        is_owner=my_live is not None,
    )


@main_bp.route('/api/live/status')
def live_status_api():
    """直播状态 JSON 接口（前端轮询）。"""
    return jsonify(live_service.get_status())


@main_bp.route('/music/live/start', methods=['POST'])
@login_required
def live_start():
    """开播：所有登录用户均可，多路主播可同时开播。

    前端 JS 直连时（X-Requested-With: XMLHttpRequest）返回 JSON 并携带该路推流令牌，
    由 JS 在已获麦克风授权的上下文中直接开始推流，避免刷新后权限边界问题；
    无 JS 时回退为表单 + 重定向。
    """
    user = get_current_user()
    title = request.form.get('title', '').strip()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = request.get_json(silent=True) or {}
        title = title or str(data.get('title', '')).strip()

    success, message, bid = live_service.start(user, title)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        payload = {'success': success, 'message': message}
        if success:
            payload['broadcast_id'] = bid
            my = live_service.get_user_broadcast(user)
            payload['push_token'] = my['push_token'] if my else None
            payload['playlist_url'] = url_for('main.live_playlist', bid=bid)
        return jsonify(payload)

    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.live_page'))


@main_bp.route('/music/live/stop', methods=['POST'])
@login_required
def live_stop():
    """结束直播：主播本人结束自己那路，或管理员强制结束指定/任意一路。"""
    user = get_current_user()
    admin = bool(user.get('is_admin'))
    bid = (request.form.get('bid') or '').strip()
    if bid:
        success = live_service.stop(bid, user, admin=admin)
    else:
        # 未指定直播 ID：结束调用者自己的直播（主播本人）
        success = live_service.stop_own(user)
    if success:
        flash('直播已结束', 'success')
    else:
        flash('没有正在进行的直播，或您无权结束该直播', 'error')
    return redirect(url_for('main.live_page'))


@main_bp.route('/music/live/push', methods=['POST'])
@login_required
def live_push():
    """推流：接收浏览器 MediaRecorder 产生的音频分片（请求体为原始字节）。

    推流令牌全局唯一，直接锁定主播自己的那路直播，不与其他路冲突。
    """
    user = get_current_user()
    token = request.headers.get('X-Push-Token', '')
    if not token or not live_service.push(user['id'], token, request.get_data()):
        return ('forbidden', 403)
    return ('ok', 200)


@main_bp.route('/music/live/<bid>/playlist.m3u8')
def live_playlist(bid):
    """指定直播的 HLS 播放列表。必须禁用缓存，让播放器（含游戏端）持续追帧刷新。"""
    playlist_path = live_service.get_live_m3u8_path(bid)
    if not playlist_path or not os.path.isfile(playlist_path):
        abort(404)
    resp = send_file(playlist_path, mimetype='application/vnd.apple.mpegurl')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@main_bp.route('/music/live/<bid>/<path:filename>')
def live_segment(bid, filename):
    """指定直播的 TS 分片。禁用缓存，避免播放器误用过期分片。"""
    base_dir = live_service.get_live_dir(bid)
    if not base_dir:
        abort(404)
    safe = os.path.normpath(filename).replace('\\', '/')
    if not safe or safe.startswith('/') or '..' in safe.split('/'):
        abort(404)
    target = os.path.abspath(os.path.join(base_dir, safe))
    if not (target == base_dir or target.startswith(base_dir + os.sep)):
        abort(404)
    if not os.path.isfile(target):
        abort(404)
    resp = send_file(target, mimetype='video/mp2t')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp
