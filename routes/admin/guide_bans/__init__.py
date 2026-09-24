"""管理员指南编辑封禁管理。

管理操作（创建/解除封禁）统一返回 JSON，前端无刷新。
"""

from datetime import datetime, timedelta

from flask import request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin/guide-bans')
@admin_required
def admin_guide_bans():
    """管理后台：封禁列表。"""
    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows = conn.execute(
            """
            SELECT b.*,
                   u.username as banned_user_name,
                   a.username as banned_by_name
            FROM guide_edit_bans b
            LEFT JOIN users u ON b.user_id = u.id
            LEFT JOIN users a ON b.banned_by = a.id
            WHERE b.expires_at IS NULL OR b.expires_at > ?
            ORDER BY b.created_at DESC
            """,
            (now,),
        ).fetchall()
        bans = [dict(r) for r in rows]
    finally:
        conn.close()

    return render_page('admin/guide_bans.html', bans=bans)


@admin_bp.route('/admin/guide-bans/create', methods=['POST'])
@admin_required
def admin_guide_ban_create():
    """管理后台：创建封禁（JSON API，前端无刷新）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}

    target_type = (data.get('target_type') or request.form.get('target_type') or 'ip').strip()
    target_value = (data.get('target_value') or request.form.get('target_value') or '').strip()
    reason = (data.get('reason') or request.form.get('reason') or '').strip()
    duration_days = (str(data.get('duration_days') or request.form.get('duration_days') or '')).strip()

    if not target_value:
        return jsonify({'success': False, 'message': '封禁目标不能为空'}), 400

    user_id = None
    ip_address = None
    banned_user_name = None

    if target_type == 'user':
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id, username FROM users WHERE username = ?", (target_value,)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'message': f'用户 "{target_value}" 不存在'}), 404
            user_id = row['id']
            banned_user_name = row['username']
        finally:
            conn.close()
    else:
        ip_address = target_value

    expires_at = None
    if duration_days:
        try:
            days = int(duration_days)
            if days > 0:
                expires = datetime.now() + timedelta(days=days)
                expires_at = expires.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass

    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute(
            """
            INSERT INTO guide_edit_bans (user_id, ip_address, banned_by, reason, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, ip_address, user['id'], reason, now, expires_at),
        )
        conn.commit()
        ban_id = cur.lastrowid
        return jsonify({
            'success': True,
            'message': '封禁已创建',
            'ban': {
                'id': ban_id,
                'is_user': bool(user_id),
                'target': banned_user_name or ip_address,
                'reason': reason,
                'operator': user['username'],
                'expires_at': expires_at,
            },
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'创建失败: {e}'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/guide-bans/<int:ban_id>/delete', methods=['POST'])
@admin_required
def admin_guide_ban_delete(ban_id):
    """管理后台：解除封禁（JSON API，前端无刷新）。"""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM guide_edit_bans WHERE id = ?", (ban_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'success': False, 'message': '封禁记录不存在'}), 404
        return jsonify({'success': True, 'message': '封禁已解除'})
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '解除失败'}), 500
    finally:
        conn.close()

