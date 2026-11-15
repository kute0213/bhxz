"""音频直播 JSON API：列表、状态、开播、停止、PCM 推流、音源搜索。"""

from flask import jsonify, request

from config import get_live_max_loop_per_user
from core.auth import get_current_user, login_required
from core.shared.ip import get_client_ip, is_trusted_proxy
from routes.live import live_bp
from services.live import manager, store
from services.live.constants import (
    MAX_REC_PER_USER,
    MODE_LABELS,
    MODE_LOOP,
    MODE_REC,
    M3U8_PATH,
    MP3_PATH,
    PLAY_PAGE_PATH,
    is_valid_mode,
)
from services.live.ingest import validate_pcm_chunk
from services.music import STATUS_LABELS, get_user_musics_page, tags_to_list


def _base_url():
    """构造对外访问的站点根地址。

    反向代理 / 内网穿透下 Flask 看到的协议恒为 http，这里在可信代理场景下
    采信 X-Forwarded-Proto / X-Forwarded-Host，避免分享出去的链接是 http。
    """
    scheme = request.scheme
    host = request.host
    if is_trusted_proxy(request.remote_addr):
        proto = (request.headers.get('X-Forwarded-Proto') or '')
        proto = proto.split(',')[0].strip().lower()
        if proto in ('http', 'https'):
            scheme = proto
        fwd_host = (request.headers.get('X-Forwarded-Host') or '')
        fwd_host = fwd_host.split(',')[0].strip()
        if fwd_host:
            host = fwd_host
    return f'{scheme}://{host}'


def _links(channel_id):
    """直播的三种访问地址（绝对地址，便于前端复制分享）。"""
    base = _base_url()
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
            'mode_label': MODE_LABELS.get(row.get('mode'), '循环播放'),
            'music_id': row.get('music_id'),
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
    """当前用户的开播状态：封禁信息、全部进行中的直播与数量上限。"""
    user = get_current_user()
    ban = store.get_ban(user['id'])
    rows = store.get_user_active_channels(user['id'])
    channels = []
    for row in rows:
        channel = manager.get(row['id'])
        channels.append(_payload(channel, row) if channel and channel.is_live()
                        else _payload(None, row))

    loop_used = sum(1 for c in channels if c.get('mode') == MODE_LOOP)
    rec_used = sum(1 for c in channels if c.get('mode') == MODE_REC)
    return jsonify({
        'success': True,
        'banned': bool(ban),
        'ban': ban,
        'channels': channels,
        # 兼容旧前端字段：最新一个直播
        'channel': channels[0] if channels else None,
        'limits': {
            'loop_max': get_live_max_loop_per_user(),
            'loop_used': loop_used,
            'rec_max': MAX_REC_PER_USER,
            'rec_used': rec_used,
        },
    })


@live_bp.route('/api/live/musics')
@login_required
def api_live_musics():
    """当前用户可用的直播音源（含私有音频），支持搜索与分页。"""
    user = get_current_user()
    keyword = (request.args.get('q') or '').strip()[:60]
    page = request.args.get('page', type=int) or 1

    items, has_more = get_user_musics_page(
        user['id'], keyword=keyword, page=page, page_size=20)
    for m in items:
        m['tags_list'] = tags_to_list(m.get('tags'))
        m['status_label'] = STATUS_LABELS.get(m.get('status'), '')

    return jsonify({
        'success': True,
        'musics': items,
        'has_more': has_more,
        'page': page,
        'next_page': page + 1,
    })


@live_bp.route('/api/live/start', methods=['POST'])
@login_required
def api_live_start():
    """开始直播：循环播放音频或实时录音。"""
    user = get_current_user()
    data = _json_body()

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'message': '请填写直播标题'}), 400

    mode = str(data.get('mode') or MODE_LOOP).strip()
    if not is_valid_mode(mode):
        return jsonify({'success': False, 'message': '不支持的直播模式'}), 400

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

    if mode == MODE_REC:
        ok, result = manager.start_rec(user['id'], user['username'], title)
    else:
        ok, result = manager.start_loop(
            user['id'], user['username'], title, data.get('music_id'))
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


@live_bp.route('/api/live/<int:channel_id>/pcm', methods=['POST'])
@login_required
def api_live_pcm(channel_id):
    """实时录音：接收浏览器上传的 s16le PCM 裸数据（48kHz 双声道）。

    使用 HTTPS 分片上传而不是 WebRTC：不需要 UDP / STUN / TURN，也不依赖
    原生扩展，部署在反向代理后同样可用。前端约每 200ms 上传一次。
    """
    user = get_current_user()
    channel = manager.get(channel_id)
    if channel is None or not channel.is_live():
        return jsonify({'success': False, 'message': '直播不存在或已结束'}), 404
    if channel.mode != MODE_REC:
        return jsonify({'success': False, 'message': '该直播不是实时录音模式'}), 400
    if channel.user_id != int(user['id']) and not user.get('is_admin'):
        return jsonify({'success': False, 'message': '无权向该直播推送音频'}), 403

    data = request.get_data(cache=False)
    ok, message, status = validate_pcm_chunk(data)
    if not ok:
        return jsonify({'success': False, 'message': message}), status

    if not channel.write_pcm(data):
        return jsonify({'success': False, 'message': '直播音频管道已关闭'}), 409
    return jsonify({'success': True})
