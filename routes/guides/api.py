"""服务器指南成员API：提交新指南、申请编辑。"""

import re
from datetime import datetime

from flask import request, jsonify, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from services.ip import get_client_ip
from services.captcha import captcha_service
from services.email import email_service, guide_review_pending as build_pending_html
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
