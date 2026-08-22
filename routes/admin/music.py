"""大喇叭音频管理路由：查看全部音频、下架（删除）。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, redirect, url_for, flash, abort, request

from core.auth import login_required, get_current_user
from routes.admin import admin_bp
from services import music_service


@admin_bp.route('/admin/music')
@login_required
def admin_music_list():
    """管理员查看所有音频。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    musics = music_service.get_all_musics()
    return render_template('admin/admin_music.html', user=user, musics=musics)


@admin_bp.route('/admin/music/<int:music_id>/delete', methods=['POST'])
@login_required
def admin_music_delete(music_id):
    """管理员下架（删除）音频。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = music_service.delete_music(
        music_id=music_id,
        user_id=user['id'],
        is_admin=True,
        ip_address=request.remote_addr,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_music_list'))
