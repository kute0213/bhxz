"""服务器指南成员API：提交新指南、申请编辑。"""

import re
from datetime import datetime

from flask import request, jsonify, abort, session

from core.auth import login_required, get_current_user
from core.db import get_db
from services.ip import get_client_ip
from services.captcha import verify_captcha
from services.email import email_service
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
    html = (
        f'<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">'
        f'<h2 style="color: #f4d03f;">新指南待审核</h2>'
        f'<p>管理员您好，</p>'
        f'<p>用户 <b>{author_name}</b> {action}服务器指南：</p>'
        f'<div style="font-size: 18px; font-weight: bold; padding: 12px; '
        f'background: #1a2a1a; border-radius: 8px; margin: 12px 0;">{title}</div>'
        f'<p>请尽快前往管理后台审核。</p></div>'
    )
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


@guides_bp.route('/api/guides/submit', methods=['POST'])
@login_required
def submit_guide():
    """成员提交新指南（进入待审核状态）。"""
    user = get_current_user()
    ip = get_client_ip()

    if _is_banned(user['id'], ip):
        return jsonify({'success': False, 'message': '你已被禁止提交或编辑服务器指南'}), 403

    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    summary = (data.get('summary') or '').strip()
    content = (data.get('content') or '').strip()

    if not title or len(title) > 200:
        return jsonify({'success': False, 'message': '标题不能为空且不超过200字'}), 400
    if not content:
        return jsonify({'success': False, 'message': '内容不能为空'}), 400
    if len(content) > 50000:
        return jsonify({'success': False, 'message': '内容过长，不超过50000字'}), 400

    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        slug = _ensure_unique_slug(conn, _slugify(title))
        conn.execute(
            """
            INSERT INTO server_guides
            (title, slug, summary, content, author_id, status, is_pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
            """,
            (title, slug, summary, content, user['id'], now, now),
        )
        conn.commit()
        _notify_admins_new_guide(title, user['username'], is_edit=False)
        return jsonify({'success': True, 'message': '指南已提交，等待管理员审核'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'提交失败: {e}'}), 500
    finally:
        conn.close()


@guides_bp.route('/api/guides/<int:guide_id>/edit-request', methods=['POST'])
@login_required
def edit_guide_request(guide_id):
    """成员申请编辑已有指南（需审核）。

    只能编辑自己创建的指南；编辑后状态变回 pending 等待审核。
    """
    user = get_current_user()
    ip = get_client_ip()

    if _is_banned(user['id'], ip):
        return jsonify({'success': False, 'message': '你已被禁止提交或编辑服务器指南'}), 403

    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    summary = (data.get('summary') or '').strip()
    content = (data.get('content') or '').strip()

    if not title or len(title) > 200:
        return jsonify({'success': False, 'message': '标题不能为空且不超过200字'}), 400
    if not content:
        return jsonify({'success': False, 'message': '内容不能为空'}), 400
    if len(content) > 50000:
        return jsonify({'success': False, 'message': '内容过长，不超过50000字'}), 400

    conn = get_db()
    try:
        guide = conn.execute(
            "SELECT id, author_id, status FROM server_guides WHERE id = ?",
            (guide_id,),
        ).fetchone()
        if not guide:
            abort(404)

        # 成员只能编辑自己的指南
        if guide['author_id'] != user['id']:
            abort(403)

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        slug = _ensure_unique_slug(conn, _slugify(title), exclude_id=guide_id)
        conn.execute(
            """
            UPDATE server_guides
            SET title = ?, slug = ?, summary = ?, content = ?,
                status = 'pending', updated_at = ?, published_at = NULL, rejected_reason = ''
            WHERE id = ?
            """,
            (title, slug, summary, content, now, guide_id),
        )
        conn.commit()
        _notify_admins_new_guide(title, user['username'], is_edit=True)
        return jsonify({'success': True, 'message': '修改已提交，等待管理员审核'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'修改失败: {e}'}), 500
    finally:
        conn.close()


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
    """验证提交指南时的验证码。"""
    data = request.get_json() or {}
    user_input = (data.get('captcha') or '').strip()
    answer = session.pop('captcha_answer', None)
    if not answer or not verify_captcha(user_input, answer):
        return jsonify({'success': False, 'message': '验证码错误或已过期'})
    return jsonify({'success': True})
