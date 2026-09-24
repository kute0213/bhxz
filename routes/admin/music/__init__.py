"""大喇叭音频管理路由：查看全部音频、下架（删除）。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import jsonify, request

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from routes.admin import admin_bp
import services.music as music_service
from services.mail import email_service, music_review_result as build_result_html
from core.shared.ip import get_client_ip


def _notify_author_music_result(music_id, approved):
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
@admin_required
def admin_music_list():
    """管理员查看所有音频 + 待审核队列（每次 10 条，加载更多走 API）。"""
    pending_musics, pending_total = music_service.get_musics_page(
        status=music_service.STATUS_PENDING, page=1, page_size=music_service.PAGE_SIZE)
    music_service.attach_durations(pending_musics)

    musics, musics_total = music_service.get_musics_page(
        page=1, page_size=music_service.PAGE_SIZE)
    music_service.attach_durations(musics)

    return render_page(
        'admin/music.html',
        pending_musics=pending_musics,
        pending_total=pending_total,
        musics=musics,
        musics_total=musics_total,
        page_size=music_service.PAGE_SIZE,
    )


@admin_bp.route('/admin/music/api/list')
@admin_required
def admin_music_api_list():
    """音频列表 JSON API（分页，每次 10 条）。

    参数：
        type  all=全部音频（默认） pending=待审核队列
        page  页码，从 1 开始
    """
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    list_type = (request.args.get('type') or 'all').strip()
    if list_type not in ('all', 'pending'):
        return jsonify({'success': False, 'message': '无效的列表类型'}), 400

    status = music_service.STATUS_PENDING if list_type == 'pending' else None
    page_size = music_service.PAGE_SIZE
    items, total = music_service.get_musics_page(
        status=status, page=page, page_size=page_size)
    music_service.attach_durations(items)
    for m in items:
        m['tags_list'] = music_service.tags_to_list(m.get('tags'))

    return jsonify({
        'success': True,
        'type': list_type,
        'musics': items,
        'page': page,
        'page_size': page_size,
        'total': total,
        'has_more': page * page_size < total,
    })


@admin_bp.route('/admin/music/<int:music_id>/review', methods=['POST'])
@admin_required
def admin_music_review(music_id):
    """管理员审核公开申请：通过 / 驳回（JSON API，前端无刷新）。"""
    user = get_current_user()

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or request.form.get('action') or '').strip()
    if action not in ('approve', 'reject'):
        return jsonify({'success': False, 'message': '无效的操作'}), 400

    approve = action == 'approve'
    success, message = music_service.review_music(
        music_id, approve=approve,
        reviewer_username=user['username'],
        ip_address=get_client_ip(),
    )
    if success:
        _notify_author_music_result(music_id, approved=approve)
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/music/<int:music_id>/delete', methods=['POST'])
@admin_required
def admin_music_delete(music_id):
    """管理员下架（删除）音频（JSON API，前端无刷新）。"""
    user = get_current_user()

    success, message = music_service.delete_music(
        music_id=music_id,
        user_id=user['id'],
        is_admin=True,
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})
