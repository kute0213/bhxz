"""管理员广播邮件：向全体用户发送 Markdown 格式的广播消息。

所有路由均要求管理员权限，AJAX 请求在权限不足时返回 JSON 401/403
（而非 HTML 重定向），避免前端 fetch 解析 JSON 报 "Unexpected token '<'"。
"""

from datetime import datetime

from flask import render_template, request, jsonify, g

from core.auth import admin_required, get_current_user
from core.db import get_db
from services.email import email_service, broadcast_message
from routes.admin import admin_bp


@admin_bp.route('/admin/broadcast')
@admin_required
def admin_broadcast():
    """广播邮件页面。"""
    return render_template('admin/admin_broadcast.html', user=g._current_user)


@admin_bp.route('/admin/broadcast/send', methods=['POST'])
@admin_required
def admin_broadcast_send():
    """处理广播邮件发送（AJAX，返回 JSON）。

    请求 JSON:
    {
        "subject": "广播标题",
        "body": "# Markdown 内容",
        "confirm": "CONFIRM"
    }
    """
    user = get_current_user()

    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or '').strip()
    body = (data.get('body') or '').strip()
    confirm = data.get('confirm') == 'CONFIRM'

    # 1. 检查邮件功能是否启用
    if not email_service.is_enabled():
        return jsonify({'success': False, 'message': '邮件功能未启用，请先在系统设置中配置 SMTP'})

    # 2. 二次确认校验（防止误操作）
    if not confirm:
        return jsonify({'success': False, 'message': '请确认发送意图'})

    # 3. 输入验证
    if not subject:
        return jsonify({'success': False, 'message': '请输入广播标题'})
    if len(subject) > 200:
        return jsonify({'success': False, 'message': '标题过长（最多 200 字）'})
    if not body:
        return jsonify({'success': False, 'message': '请输入广播内容'})
    if len(body) > 20000:
        return jsonify({'success': False, 'message': '内容过长（最多 20000 字）'})

    # 4. 获取所有有邮箱的用户（一次查询）
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT email FROM users WHERE email IS NOT NULL AND email != ''"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return jsonify({'success': False, 'message': '没有已绑定邮箱的用户'})

    # 5. 构建 HTML 并批量入队（异步发送，不阻塞请求）
    sender_name = user['username']
    html = broadcast_message(subject, body, sender_name)
    plain_body = f'来自 {sender_name} 的全体广播：\n\n{body}\n'
    subject_line = f'[广播] {subject}'

    sent_count = 0
    for row in rows:
        email = row['email']
        if not email:
            continue
        email_service.send(to=email, subject=subject_line, body=plain_body, html=html)
        sent_count += 1

    # 6. 记录广播日志（失败不影响主流程）
    try:
        log_conn = get_db()
        try:
            log_conn.execute(
                "INSERT INTO broadcast_logs "
                "(subject, body, sender_id, sender_name, recipient_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (subject, body, user['id'], user['username'], sent_count,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            )
            log_conn.commit()
        finally:
            log_conn.close()
    except Exception:
        pass

    return jsonify({
        'success': True,
        'message': f'广播已入队，共 {sent_count} 位用户将收到邮件',
        'count': sent_count,
    })


@admin_bp.route('/admin/broadcast/logs')
@admin_required
def admin_broadcast_logs():
    """获取广播历史日志（AJAX，返回 JSON）。"""
    conn = get_db()
    try:
        try:
            rows = conn.execute(
                "SELECT id, subject, body, sender_name, recipient_count, created_at "
                "FROM broadcast_logs ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            logs = [dict(r) for r in rows]
        except Exception:
            logs = []
    finally:
        conn.close()

    return jsonify({'success': True, 'logs': logs})
