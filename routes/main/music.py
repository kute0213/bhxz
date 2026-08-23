"""大喇叭音频路由：板块页面、独立上传页、上传进度、播放、删除、公开切换、音量增益。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
播放链接格式：/music/<音频ID>.m3u8（公开音频所有人可播，私有仅本人/管理员可播）。
上传采用异步任务：POST /music/upload 返回 task_id，前端轮询 /music/upload/progress/<task_id>。
"""

import os

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    send_file,
    jsonify,
)

from core.auth import login_required, get_current_user
from config import UPLOAD_MUSIC_DIR
from routes.main import main_bp
from services import music_service


def _can_access(music, user):
    """是否有权限播放音频：已公开任意访问；其余仅本人或管理员。"""
    if music['status'] == music_service.STATUS_PUBLIC:
        return True
    if not user:
        return False
    return user['id'] == music['user_id'] or bool(user.get('is_admin'))


@main_bp.route('/music')
def music_page():
    """大喇叭音频板块：公开音频列表（支持按名称搜索）。"""
    user = get_current_user()
    keyword = request.args.get('q', '').strip()
    public_musics = music_service.get_public_musics(keyword)
    return render_template(
        'music/list.html',
        user=user,
        public_musics=public_musics,
        keyword=keyword,
    )


@main_bp.route('/music/my')
@login_required
def my_music_page():
    """我的音频：独立页面，展示当前用户上传的全部音频。"""
    user = get_current_user()
    my_musics = music_service.get_user_musics(user['id'])
    return render_template(
        'music/my.html',
        user=user,
        my_musics=my_musics,
    )


@main_bp.route('/music/upload')
@login_required
def upload_music_page():
    """大喇叭音频上传页：独立页面，含详细进度条与音量增益设置。"""
    user = get_current_user()
    return render_template(
        'music/upload.html',
        user=user,
        gain_min=music_service.GAIN_MIN,
        gain_max=music_service.GAIN_MAX,
    )


def _redirect_back(default='main.music_page'):
    """返回操作来源页（next 参数须为站内相对路径），否则回到公开音频列表。"""
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for(default))


@main_bp.route('/music/upload', methods=['POST'])
@login_required
def upload_music():
    """开始异步上传任务（AJAX）。成功返回 {task_id}，失败返回 {error}。"""
    user = get_current_user()
    title = request.form.get('title', '').strip()
    is_public = request.form.get('is_public') in ('1', 'on', 'true')
    gain = request.form.get('gain', '0')
    upload_file = request.files.get('audio_file')

    success, result = music_service.start_upload(
        user_id=user['id'],
        username=user['username'],
        title=title,
        is_public=is_public,
        gain=gain,
        upload_file=upload_file,
        ip_address=request.remote_addr,
    )
    if success:
        return jsonify({'task_id': result['task_id']})
    return jsonify({'error': result}), 400


@main_bp.route('/music/upload/progress/<task_id>')
@login_required
def upload_music_progress(task_id):
    """查询上传任务进度（AJAX 轮询），返回 JSON。"""
    task = music_service.get_upload_progress(task_id)
    if not task:
        return jsonify({'status': 'error', 'message': '任务不存在或已过期'}), 404
    return jsonify(task)


@main_bp.route('/music/<int:music_id>/gain', methods=['POST'])
@login_required
def update_music_gain(music_id):
    """调整音频音量增益（重新转码）。上传者本人或管理员可操作。"""
    user = get_current_user()
    gain = request.form.get('gain', '0')
    success, message = music_service.update_gain(
        music_id=music_id,
        gain=gain,
        user_id=user['id'],
        is_admin=bool(user.get('is_admin')),
        ip_address=request.remote_addr,
    )
    flash(message, 'success' if success else 'error')
    return _redirect_back()


@main_bp.route('/music/<int:music_id>/toggle', methods=['POST'])
@login_required
def toggle_music_public(music_id):
    user = get_current_user()
    success, message = music_service.toggle_music_public(
        music_id=music_id,
        user_id=user['id'],
        is_admin=bool(user.get('is_admin')),
        ip_address=request.remote_addr,
    )
    flash(message, 'success' if success else 'error')
    return _redirect_back()


@main_bp.route('/music/<int:music_id>/delete', methods=['POST'])
@login_required
def delete_music(music_id):
    user = get_current_user()
    success, message = music_service.delete_music(
        music_id=music_id,
        user_id=user['id'],
        is_admin=bool(user.get('is_admin')),
        ip_address=request.remote_addr,
    )
    flash(message, 'success' if success else 'error')
    return _redirect_back()


# ---------------------------------------------------------------------------
# 播放服务：m3u8 播放列表 + HLS 分片
# ---------------------------------------------------------------------------

@main_bp.route('/music/<int:music_id>.m3u8')
def serve_music_playlist(music_id):
    """HLS 播放列表，格式：/music/<编号>.m3u8。"""
    music = music_service.get_music(music_id)
    if not music:
        abort(404)
    user = get_current_user()
    if not _can_access(music, user):
        abort(404)

    playlist_path = music_service.get_music_file_path(music_id)
    if not os.path.isfile(playlist_path):
        abort(404)

    resp = send_file(playlist_path, mimetype='application/vnd.apple.mpegurl')
    # 音频内容不可变，可放心缓存
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@main_bp.route('/music/<int:music_id>/<path:filename>')
def serve_music_segment(music_id, filename):
    """HLS 分片文件，格式：/music/<编号>/<分片>.ts。"""
    music = music_service.get_music(music_id)
    if not music:
        abort(404)
    user = get_current_user()
    if not _can_access(music, user):
        abort(404)

    base_dir = os.path.abspath(os.path.join(UPLOAD_MUSIC_DIR, str(music_id)))
    safe = os.path.normpath(filename).replace('\\', '/')
    if not safe or safe.startswith('/') or '..' in safe.split('/'):
        abort(404)

    target = os.path.abspath(os.path.join(base_dir, safe))
    if not (target == base_dir or target.startswith(base_dir + os.sep)):
        abort(404)
    if not os.path.isfile(target):
        abort(404)

    return send_file(target, mimetype='video/mp2t')
