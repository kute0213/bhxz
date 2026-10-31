"""服务器指南成员API：指南列表、发布草稿、视频资源、收藏。"""

import os
import re
from datetime import datetime

from flask import request, jsonify, url_for

from core.auth import login_required, get_current_user
from core.db import get_db
from core.shared.snowflake import next_id
from core.shared.captcha import captcha_service
from core.shared.ip import get_client_ip
from config import (
    get_page_size,
    get_guide_resource_limit,
    GUIDE_VIDEO_EXTENSIONS,
)
from services.mail import email_service, guide_review_pending as build_pending_html
from services.firewall.protection.file_guard import check_upload, KIND_AUDIO
from services import guides as guide_store
from routes.guides import guides_bp


def _is_banned(user_id, ip_address):
    """检查用户或IP是否被封禁。"""
    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 检查 user_id 封禁
        if user_id:
            row = conn.execute(
                """
                SELECT id FROM guide_edit_bans
                WHERE user_id = ? AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (user_id, now),
            ).fetchone()
            if row:
                return True
        # 检查 IP 封禁
        if ip_address:
            row = conn.execute(
                """
                SELECT id FROM guide_edit_bans
                WHERE ip_address = ? AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (ip_address, now),
            ).fetchone()
            if row:
                return True
    finally:
        conn.close()
    return False


def _slugify(text):
    """将标题转换为 URL slug。"""
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    text = re.sub(r'[-\s]+', '-', text)
    return text[:80] or 'guide'


def _notify_admins_new_guide(title, author_name, is_edit=False):
    """异步通知所有管理员有新指南提交（不阻塞请求）。"""
    if not email_service.is_enabled():
        return

    conn = get_db()
    try:
        admins = conn.execute(
            "SELECT email FROM users WHERE is_admin = 1 AND email IS NOT NULL AND email != ''"
        ).fetchall()
    finally:
        conn.close()

    if not admins:
        return

    action = '修改了' if is_edit else '提交了'
    subject = f'[指南审核] {author_name} {action}「{title}」'
    body = (
        f'管理员您好，\n\n'
        f'用户 {author_name} {action}服务器指南「{title}」。\n'
        f'请尽快前往管理后台审核。\n'
    )
    html = build_pending_html(title, author_name, is_edit=is_edit)
    for admin in admins:
        email_service.send(admin['email'], subject, body, html)


def _ensure_unique_slug(conn, base_slug, exclude_id=None):
    """确保 slug 唯一，重复时追加数字。"""
    slug = base_slug
    counter = 2
    while True:
        if exclude_id:
            existing = conn.execute(
                "SELECT id FROM server_guides WHERE slug = ? AND id != ?",
                (slug, exclude_id),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM server_guides WHERE slug = ?",
                (slug,),
            ).fetchone()
        if not existing:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


@guides_bp.route('/api/guides/list', methods=['GET'])
def api_guides_list():
    """公开指南列表 API（分页，分页大小由系统设置 GUIDES_PER_PAGE 控制）。

    参数：
        page  页码，从 1 开始
        q     关键字，匹配标题与摘要

    仅返回已审核通过的指南；「我的指南」使用独立接口 /api/guides/my。
    """
    user = get_current_user()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    keyword = (request.args.get('q') or '').strip()[:60]

    # 分页大小只由后台设置决定，忽略任何前端传入的参数
    page_size = get_page_size('GUIDES_PER_PAGE', 5)

    where = ["g.status = 'approved'"]
    params = []
    if keyword:
        where.append("(g.title LIKE ? OR g.summary LIKE ?)")
        like = f'%{keyword}%'
        params.extend([like, like])

    where_sql = 'WHERE ' + ' AND '.join(where)
    # 公开指南按置顶优先 → 收藏数倒序 → 标题升序
    order_sql = (
        "ORDER BY g.is_pinned DESC, "
        "(SELECT COUNT(*) FROM guide_favorites f WHERE f.guide_id = g.id) DESC, "
        "g.title ASC"
    )

    conn = get_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM server_guides g {where_sql}", params
        ).fetchone()['c']
        rows = conn.execute(
            f"""
            SELECT g.id, g.title, g.summary, g.status, g.is_pinned,
                   g.created_at, g.updated_at, g.published_at, g.rejected_reason,
                   u.username AS author_name
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        guides = [dict(r) for r in rows]
        _annotate_favorites(conn, guides, user['id'] if user else None)
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'guides': guides,
        'page': page,
        'page_size': page_size,
        'total': total,
        'has_more': page * page_size < total,
        'my_mode': False,
        'keyword': keyword,
    })


@guides_bp.route('/api/guides/my', methods=['GET'])
@login_required
def my_guides():
    """当前用户创建的指南列表（含草稿 / 待审核 / 已拒绝），分页 + 关键词搜索。

    与 /api/guides/list 返回相同结构，供「我的指南」页面无刷新加载。
    参数：page 页码、q 关键字。
    """
    user = get_current_user()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    keyword = (request.args.get('q') or '').strip()[:60]
    page_size = get_page_size('GUIDES_PER_PAGE', 5)

    where = ["g.author_id = ?"]
    params = [user['id']]
    if keyword:
        where.append("(g.title LIKE ? OR g.summary LIKE ?)")
        like = f'%{keyword}%'
        params.extend([like, like])
    where_sql = 'WHERE ' + ' AND '.join(where)

    conn = get_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM server_guides g {where_sql}", params
        ).fetchone()['c']
        rows = conn.execute(
            f"""
            SELECT g.id, g.title, g.slug, g.summary, g.status, g.is_pinned,
                   g.created_at, g.updated_at, g.published_at, g.rejected_reason,
                   u.username AS author_name
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            {where_sql}
            ORDER BY g.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        guides = [dict(r) for r in rows]
        _annotate_favorites(conn, guides, user['id'])
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'guides': guides,
        'page': page,
        'page_size': page_size,
        'total': total,
        'has_more': page * page_size < total,
        'my_mode': True,
        'keyword': keyword,
    })


@guides_bp.route('/api/guides/<int:guide_id>/publish', methods=['POST'])
@login_required
def api_guide_publish(guide_id):
    """发布草稿指南：草稿 → 待审核（未发布）。

    仅作者本人或管理员可操作；正文为空时不允许发布。
    """
    user = get_current_user()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, title, status, author_id FROM server_guides WHERE id = ?",
            (guide_id,),
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '指南不存在'}), 404
        if row['author_id'] != user['id'] and not user.get('is_admin'):
            return jsonify({'success': False, 'message': '无权发布该指南'}), 403
        if row['status'] != 'draft':
            return jsonify({'success': False, 'message': '只有草稿指南可以发布'}), 400

        content = guide_store.read_guide_content(guide_id, '')
        if not content.strip():
            return jsonify({'success': False, 'message': '请先编辑指南内容再发布'}), 400

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """
            UPDATE server_guides
            SET status = 'pending', updated_at = ?, rejected_reason = '', rejected_at = NULL
            WHERE id = ?
            """,
            (now, guide_id),
        )
        conn.commit()
    finally:
        conn.close()

    _notify_admins_new_guide(row['title'], user['username'])
    return jsonify({
        'success': True,
        'message': '指南已发布，等待管理员审核',
        'status': 'pending',
        'redirect': url_for('guides.my_guides_page'),
    })


@guides_bp.route('/api/guides/verify-captcha', methods=['POST'])
def verify_guide_captcha():
    """验证提交指南时的验证码。

    请求 JSON:
    {
        "captcha": "1234",      // 图形验证码
        "captcha_id": "uuid"    // 验证码 ID（服务端内存存储）
    }
    """
    data = request.get_json() or {}
    user_input = (data.get('captcha') or '').strip()
    captcha_id = (data.get('captcha_id') or '').strip()
    # 服务端内存存储校验，一次性删除防止重放
    if not captcha_service.verify(captcha_id, user_input):
        return jsonify({'success': False, 'message': '验证码错误或已过期'})
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 收藏功能
# ---------------------------------------------------------------------------


@guides_bp.route('/api/guides/<int:guide_id>/favorite', methods=['POST'])
@login_required
def toggle_guide_favorite(guide_id):
    """收藏 / 取消收藏指南。返回 (is_favorited, favorite_count)。"""
    user = get_current_user()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, status FROM server_guides WHERE id = ?", (guide_id,)
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '指南不存在'}), 404
        if row['status'] != 'approved' and row['id'] not in (0,):  # 0 占位，实际无
            pass  # 作者收藏自己的待审核指南也允许

        # 检查当前是否已收藏
        existing = conn.execute(
            "SELECT 1 FROM guide_favorites WHERE user_id = ? AND guide_id = ?",
            (user['id'], guide_id),
        ).fetchone()

        if existing:
            conn.execute(
                "DELETE FROM guide_favorites WHERE user_id = ? AND guide_id = ?",
                (user['id'], guide_id),
            )
            is_favorited = False
        else:
            conn.execute(
                "INSERT INTO guide_favorites (id, guide_id, user_id, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (next_id(), guide_id, user['id']),
            )
            is_favorited = True
        conn.commit()

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM guide_favorites WHERE guide_id = ?",
            (guide_id,),
        ).fetchone()
        favorite_count = count_row['c']
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'is_favorited': is_favorited,
        'favorite_count': favorite_count,
    })


# ---------------------------------------------------------------------------
# 指南资源（视频）
# ---------------------------------------------------------------------------

def _guide_for_edit(guide_id):
    """读取指南并校验当前用户是否有编辑权限。

    返回 ``(guide_row, error_response)``：有权限时 ``error_response`` 为 None。
    """
    user = get_current_user()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, author_id FROM server_guides WHERE id = ?", (guide_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None, (jsonify({'success': False, 'message': '指南不存在'}), 404)
    if row['author_id'] != user['id'] and not user.get('is_admin'):
        return None, (jsonify({'success': False, 'message': '无权操作该指南'}), 403)
    return row, None


def _video_payload(guide_id, item):
    """给资源条目补充访问 / 删除 / 改名 URL 与页面显示名。"""
    name = item['name']
    return {
        'name': name,
        'title': item.get('title') or guide_store.video_title(guide_id, name, name),
        'size': item['size'],
        'size_label': item['size_label'],
        'url': url_for('guides.guide_asset', guide_id=guide_id, filename=name),
        'delete_url': url_for('guides.api_guide_video_delete',
                              guide_id=guide_id, filename=name),
        'rename_url': url_for('guides.api_guide_video_rename',
                              guide_id=guide_id, filename=name),
    }


def _quota_payload(guide_id, limit_bytes=None):
    """返回配额字段，供前端统一更新进度条。"""
    limit_bytes = limit_bytes or get_guide_resource_limit()
    used = guide_store.guide_total(guide_id)
    return {
        'used_bytes': used,
        'limit_bytes': limit_bytes,
        'limit_label': guide_store.format_size(limit_bytes),
        'used_label': guide_store.format_size(used),
        'percent': round(min(100.0, used / limit_bytes * 100), 1) if limit_bytes else 0.0,
    }


def _get_video_upload():
    return request.files.get('video') or request.files.get('file')


@guides_bp.route('/api/guides/<int:guide_id>/videos', methods=['GET'])
@login_required
def api_guide_videos(guide_id):
    """指南视频列表（编辑指南时用于「视频」标签页）。"""
    _, error = _guide_for_edit(guide_id)
    if error:
        return error
    limit = get_guide_resource_limit()
    items = [_video_payload(guide_id, i)
             for i in guide_store.list_guide_assets(guide_id)]
    return jsonify({
        'success': True,
        'items': items,
        **_quota_payload(guide_id, limit),
    })


@guides_bp.route('/api/guides/<int:guide_id>/videos', methods=['POST'])
@login_required
def api_guide_video_upload(guide_id):
    """接收指南视频并启动后台转码，返回转码任务 ID。"""
    _, error = _guide_for_edit(guide_id)
    if error:
        return error

    limit = get_guide_resource_limit()
    upload = _get_video_upload()
    ok, msg = check_upload(
        upload, KIND_AUDIO,
        max_bytes=limit,
        allowed_extensions=GUIDE_VIDEO_EXTENSIONS,
        source='guide_video',
    )
    if not ok:
        return jsonify({'success': False, 'message': msg}), 400

    title = (request.form.get('title') or '').strip()[:100]
    ok, msg, task = guide_store.start_guide_video_upload(
        guide_id, upload, limit_bytes=limit, title=title,
    )
    if not ok:
        return jsonify({'success': False, 'message': msg}), 400

    task_id = task['task_id']
    return jsonify({
        'success': True,
        'message': '视频已上传，正在转码',
        'task_id': task_id,
        'progress_url': url_for('guides.api_guide_video_progress',
                                guide_id=guide_id, task_id=task_id),
    })


@guides_bp.route('/api/guides/<int:guide_id>/videos/progress/<task_id>', methods=['GET'])
@login_required
def api_guide_video_progress(guide_id, task_id):
    """查询视频转码进度。"""
    _, error = _guide_for_edit(guide_id)
    if error:
        return error
    task = guide_store.get_video_task(task_id)
    if not task or task['guide_id'] != guide_id:
        return jsonify({'success': False, 'message': '转码任务不存在或已过期'}), 404

    payload = {
        'success': True,
        'status': task['status'],
        'percent': task['percent'],
        'message': task['message'],
    }
    if task['status'] == 'done':
        payload['item'] = _video_payload(guide_id, task['item'])
        payload.update(_quota_payload(guide_id))
    elif task['status'] == 'error':
        payload['message'] = task['error'] or '视频转码失败'
    return jsonify(payload)


@guides_bp.route('/api/guides/<int:guide_id>/videos/<path:filename>/rename', methods=['POST'])
@login_required
def api_guide_video_rename(guide_id, filename):
    """修改视频在页面上显示的伪文件名（写入指南 config.json）。"""
    _, error = _guide_for_edit(guide_id)
    if error:
        return error

    name = os.path.basename(str(filename or ''))
    path = os.path.join(guide_store.assets_dir_for(guide_id), name)
    if not os.path.isfile(path):
        return jsonify({'success': False, 'message': '视频不存在'}), 404

    data = request.get_json(silent=True) or request.form
    title = (data.get('title') or '').strip()[:100]
    guide_store.set_video_title(guide_id, name, title)
    display = guide_store.video_title(guide_id, name, name)
    item = {'name': name, 'title': display,
            'size': os.path.getsize(path),
            'size_label': guide_store.format_size(os.path.getsize(path))}
    return jsonify({
        'success': True,
        'message': '视频名称已更新',
        'item': _video_payload(guide_id, item),
    })


@guides_bp.route('/api/guides/<int:guide_id>/videos/<path:filename>/delete', methods=['POST'])
@login_required
def api_guide_video_delete(guide_id, filename):
    """删除指南视频资源（同时清理 config.json 中的配置）。"""
    _, error = _guide_for_edit(guide_id)
    if error:
        return error
    removed = guide_store.delete_guide_asset(guide_id, filename)
    if not removed:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    return jsonify({
        'success': True,
        'message': '视频已删除',
        **_quota_payload(guide_id),
    })


@guides_bp.route('/api/guides/<int:guide_id>/draft', methods=['POST'])
@login_required
def api_guide_draft(guide_id):
    """保存草稿（不刷新页面）。

    仅草稿状态的指南可用；其他状态仍需走表单提交并经过验证码与审核流程。
    """
    user = get_current_user()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, title, status, author_id FROM server_guides WHERE id = ?",
            (guide_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({'success': False, 'message': '指南不存在'}), 404
    if row['status'] != 'draft':
        return jsonify({'success': False, 'message': '只有草稿可以这样保存'}), 400
    if row['author_id'] != user['id'] and not user.get('is_admin'):
        return jsonify({'success': False, 'message': '无权修改该指南'}), 403

    data = request.get_json(silent=True) or request.form
    title = (data.get('title') or '').strip()
    summary = (data.get('summary') or '').strip()
    content = data.get('content') or ''

    if not title:
        return jsonify({'success': False, 'message': '标题不能为空'}), 400

    from services.firewall.protection.content_filter import check_content_injection
    inj_result = check_content_injection(
        user_id=user['id'], content=title + '\n' + content,
        content_type='guide', ip_address=get_client_ip(),
        username=user['username'],
    )
    if inj_result['blocked']:
        return jsonify({'success': False, 'message': inj_result['message']}), 400

    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        slug = _ensure_unique_slug(conn, _slugify(title), exclude_id=guide_id)
        guide_store.write_guide_content(guide_id, content)
        conn.execute(
            """
            UPDATE server_guides
            SET title = ?, slug = ?, summary = ?, content = '', updated_at = ?
            WHERE id = ?
            """,
            (title, slug, summary, now, guide_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return jsonify({'success': False, 'message': f'保存失败：{exc}'}), 500
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'message': '草稿已保存',
        'title': title,
        'summary': summary,
        'updated_at': now,
    })


def _annotate_favorites(conn, guides, user_id):
    """批量给指南列表加上 favorite_count 和 is_favorited 字段（避免 N+1 查询）。"""
    if not guides:
        return guides
    ids = [g['id'] for g in guides]
    placeholders = ','.join('?' * len(ids))

    # 收藏数批量统计
    count_rows = conn.execute(
        f"SELECT guide_id, COUNT(*) AS c FROM guide_favorites "
        f"WHERE guide_id IN ({placeholders}) GROUP BY guide_id",
        ids,
    ).fetchall()
    count_map = {r['guide_id']: r['c'] for r in count_rows}

    fav_map = {}
    if user_id:
        fav_rows = conn.execute(
            f"SELECT guide_id FROM guide_favorites "
            f"WHERE guide_id IN ({placeholders}) AND user_id = ?",
            ids + [user_id],
        ).fetchall()
        fav_map = {r['guide_id']: True for r in fav_rows}

    for g in guides:
        g['favorite_count'] = count_map.get(g['id'], 0)
        g['is_favorited'] = bool(fav_map.get(g['id']))
    return guides
