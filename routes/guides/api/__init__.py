"""服务器指南成员API：提交新指南、申请编辑。"""

import re
from datetime import datetime

from flask import request, jsonify

from core.auth import login_required, get_current_user
from core.db import get_db
from core.shared.captcha import captcha_service
from services.mail import email_service, guide_review_pending as build_pending_html
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


PAGE_SIZE = 10


@guides_bp.route('/api/guides/list', methods=['GET'])
def api_guides_list():
    """指南列表 API（分页，每次 10 条）。

    参数：
        page  页码，从 1 开始
        my    1 表示仅当前用户提交的指南（需登录）
        q     关键字，匹配标题与摘要
    """
    user = get_current_user()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    my_mode = bool(user and request.args.get('my') == '1')
    keyword = (request.args.get('q') or '').strip()[:60]

    where = []
    params = []
    if my_mode:
        where.append("g.author_id = ?")
        params.append(user['id'])
    else:
        where.append("g.status = 'approved'")
    if keyword:
        where.append("(g.title LIKE ? OR g.summary LIKE ?)")
        like = f'%{keyword}%'
        params.extend([like, like])

    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    order_sql = "ORDER BY g.updated_at DESC" if my_mode else "ORDER BY g.is_pinned DESC, g.title ASC"

    conn = get_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM server_guides g {where_sql}", params
        ).fetchone()['c']
        rows = conn.execute(
            f"""
            SELECT g.id, g.title, g.summary, g.content, g.status, g.is_pinned,
                   g.created_at, g.updated_at, g.published_at, g.rejected_reason,
                   u.username AS author_name
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
        guides = [dict(r) for r in rows]
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'guides': guides,
        'page': page,
        'page_size': PAGE_SIZE,
        'total': total,
        'has_more': page * PAGE_SIZE < total,
        'my_mode': my_mode,
        'keyword': keyword,
    })


@guides_bp.route('/api/guides/my', methods=['GET'])
@login_required
def my_guides():
    """获取当前用户创建的所有指南（含待审核）。"""
    user = get_current_user()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, title, slug, summary, status, is_pinned, created_at, updated_at, rejected_reason
            FROM server_guides
            WHERE author_id = ?
            ORDER BY updated_at DESC
            """,
            (user['id'],),
        ).fetchall()
        guides = [dict(r) for r in rows]
    finally:
        conn.close()

    return jsonify({'success': True, 'guides': guides})


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
