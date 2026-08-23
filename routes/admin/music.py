"""大喇叭音频管理路由：查看全部音频、下架（删除）。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, redirect, url_for, flash, abort, request

from core.auth import login_required, get_current_user
from routes.admin import admin_bp
from services import music_service
from services.email import email_service, music_review_result as build_result_html


def _notify_author_music_result(music_id, approved, ip_address):
    """异步通知音频上传者审核结果（不阻塞请求）。"""
    if not email_service.is_enabled():
        return

    music = music_service.get_music(music_id)
    if not music:
        return
    author_email = music_service.get_author_email(music_id)
    if not author_email:
        return

    if approved:
        subject = f'[音频审核通过] 「{music["title"]}」已公开'
        body = (
            f'您好！\n\n'
            f'您申请公开的大喇叭音频「{music["title"]}」已通过审核，'
            f'现已展示在游戏内大喇叭，所有用户均可看到并播放。\n'
        )
    else:
        subject = f'[音频审核未通过] 「{music["title"]}」被驳回'
        body = (
            f'您好！\n\n'
            f'很遗憾，您申请公开的大喇叭音频「{music["title"]}」未通过审核。\n'
            f'您可以将该音频转为私有，或直接删除。\n'
        )

    html = build_result_html(music['title'], approved)
    email_service.send(author_email, subject, body, html)


@admin_bp.route('/admin/music')
@login_required
def admin_music_list():
    """管理员查看所有音频 + 待审核队列。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    pending_musics = music_service.attach_durations(music_service.get_pending_musics())
    musics = music_service.attach_durations(music_service.get_all_musics())
    return render_template(
        'admin/admin_music.html',
        user=user,
        pending_musics=pending_musics,
        musics=musics,
    )


@admin_bp.route('/admin/music/<int:music_id>/review', methods=['POST'])
@login_required
def admin_music_review(music_id):
    """管理员审核公开申请：通过 / 驳回。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    action = request.form.get('action', '')
    if action == 'approve':
        success, message = music_service.review_music(
            music_id, approve=True,
            reviewer_username=user['username'],
            ip_address=request.remote_addr,
        )
        if success:
            _notify_author_music_result(music_id, approved=True, ip_address=request.remote_addr)
    elif action == 'reject':
        success, message = music_service.review_music(
            music_id, approve=False,
            reviewer_username=user['username'],
            ip_address=request.remote_addr,
        )
        if success:
            _notify_author_music_result(music_id, approved=False, ip_address=request.remote_addr)
    else:
        flash('无效的操作', 'error')
        return redirect(url_for('admin.admin_music_list'))

    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_music_list'))


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
