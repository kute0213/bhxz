"""管理员指南编辑封禁管理。"""

from datetime import datetime, timedelta

from flask import render_template, redirect, url_for, flash, abort, request

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin/guide-bans')
@login_required
def admin_guide_bans():
    """管理后台：封禁列表。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

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

    return render_template('admin/admin_guide_bans.html', user=user, bans=bans)


@admin_bp.route('/admin/guide-bans/create', methods=['POST'])
@login_required
def admin_guide_ban_create():
    """管理后台：创建封禁。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    target_type = request.form.get('target_type', 'ip').strip()
    target_value = (request.form.get('target_value') or '').strip()
    reason = (request.form.get('reason') or '').strip()
    duration_days = request.form.get('duration_days', '').strip()

    if not target_value:
        flash('封禁目标不能为空', 'error')
        return redirect(url_for('admin.admin_guide_bans'))

    user_id = None
    ip_address = None

    if target_type == 'user':
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (target_value,)
            ).fetchone()
            if not row:
                flash(f'用户 "{target_value}" 不存在', 'error')
                return redirect(url_for('admin.admin_guide_bans'))
            user_id = row['id']
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
        conn.execute(
            """
            INSERT INTO guide_edit_bans (user_id, ip_address, banned_by, reason, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, ip_address, user['id'], reason, now, expires_at),
        )
        conn.commit()
        flash('封禁已创建', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'创建失败: {e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_guide_bans'))


@admin_bp.route('/admin/guide-bans/<int:ban_id>/delete', methods=['POST'])
@login_required
def admin_guide_ban_delete(ban_id):
    """管理后台：解除封禁。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        conn.execute("DELETE FROM guide_edit_bans WHERE id = ?", (ban_id,))
        conn.commit()
        flash('封禁已解除', 'success')
    except Exception:
        conn.rollback()
        flash('解除失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_guide_bans'))
