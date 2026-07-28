"""管理员服务器指南管理：CRUD、审核。"""

from datetime import datetime

from flask import render_template, redirect, url_for, flash, abort, request, jsonify

from core.auth import login_required, get_current_user
from core.db import get_db
from services.email import email_service
from routes.admin import admin_bp


def _notify_author_guide_result(guide_title, author_email, approved, reason=''):
    """异步通知指南作者审核结果（不阻塞请求）。"""
    if not email_service.is_enabled() or not author_email:
        return

    if approved:
        subject = f'[指南审核通过] 「{guide_title}」已通过'
        body = (
            f'您好！\n\n'
            f'您提交的服务器指南「{guide_title}」已通过审核，现已发布。\n'
        )
        html = (
            f'<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">'
            f'<h2 style="color: #4ade80;">指南审核通过</h2>'
            f'<p>您好！</p>'
            f'<p>您提交的服务器指南：</p>'
            f'<div style="font-size: 18px; font-weight: bold; padding: 12px; '
            f'background: #1a2a1a; border-radius: 8px; margin: 12px 0;">{guide_title}</div>'
            f'<p>已通过审核，现已发布。</p></div>'
        )
    else:
        subject = f'[指南审核未通过] 「{guide_title}」被拒绝'
        body = (
            f'您好！\n\n'
            f'很遗憾，您提交的服务器指南「{guide_title}」未通过审核。\n'
        )
        if reason:
            body += f'拒绝原因：{reason}\n'
        body += '您可以修改后重新提交。\n'
        html = (
            f'<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">'
            f'<h2 style="color: #f87171;">指南审核未通过</h2>'
            f'<p>您好！</p>'
            f'<p>很遗憾，您提交的服务器指南：</p>'
            f'<div style="font-size: 18px; font-weight: bold; padding: 12px; '
            f'background: #1a2a1a; border-radius: 8px; margin: 12px 0;">{guide_title}</div>'
            f'<p>未通过审核。</p>'
            + (f'<p>拒绝原因：{reason}</p>' if reason else '')
            + f'<p>您可以修改后重新提交。</p></div>'
        )

    email_service.send(author_email, subject, body, html)


@admin_bp.route('/admin/guides')
@login_required
def admin_guides():
    """管理后台：指南列表（含待审核）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT g.*, u.username as author_name
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            ORDER BY g.status = 'pending' DESC, g.is_pinned DESC, g.title ASC
            """
        ).fetchall()
        guides = [dict(r) for r in rows]
    finally:
        conn.close()

    return render_template('admin_guides.html', user=user, guides=guides)


@admin_bp.route('/admin/guides/create', methods=['GET', 'POST'])
@login_required
def admin_guide_create():
    """管理后台：直接创建指南（自动通过审核）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        summary = (request.form.get('summary') or '').strip()
        content = (request.form.get('content') or '').strip()
        cover_image = (request.form.get('cover_image') or '').strip()
        is_pinned = 1 if request.form.get('is_pinned') else 0
        status = request.form.get('status', 'approved').strip()

        if not title or not content:
            flash('标题和内容不能为空', 'error')
            return redirect(url_for('admin.admin_guide_create'))

        conn = get_db()
        try:
            from routes.guides.api import _slugify, _ensure_unique_slug
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            slug = _ensure_unique_slug(conn, _slugify(title))
            published_at = now if status == 'approved' else None
            conn.execute(
                """
                INSERT INTO server_guides
                (title, slug, summary, content, cover_image, author_id, status,
                 is_pinned, created_at, updated_at, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, slug, summary, content, cover_image, user['id'],
                 status, is_pinned, now, now, published_at),
            )
            conn.commit()
            flash('指南已创建', 'success')
            return redirect(url_for('admin.admin_guides'))
        except Exception as e:
            conn.rollback()
            flash(f'创建失败: {e}', 'error')
        finally:
            conn.close()

    return render_template('admin_guide_form.html', user=user, guide=None)


@admin_bp.route('/admin/guides/<int:guide_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_guide_edit(guide_id):
    """管理后台：编辑任意指南（保持原状态或直接通过）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM server_guides WHERE id = ?", (guide_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)
    guide = dict(row)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        summary = (request.form.get('summary') or '').strip()
        content = (request.form.get('content') or '').strip()
        cover_image = (request.form.get('cover_image') or '').strip()
        is_pinned = 1 if request.form.get('is_pinned') else 0
        status = request.form.get('status', guide['status']).strip()

        if not title or not content:
            flash('标题和内容不能为空', 'error')
            return redirect(url_for('admin.admin_guide_edit', guide_id=guide_id))

        conn = get_db()
        try:
            from routes.guides.api import _slugify, _ensure_unique_slug
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            slug = _ensure_unique_slug(conn, _slugify(title), exclude_id=guide_id)

            published_at = guide['published_at']
            if status == 'approved' and not published_at:
                published_at = now

            conn.execute(
                """
                UPDATE server_guides
                SET title = ?, slug = ?, summary = ?, content = ?,
                    cover_image = ?, status = ?, is_pinned = ?,
                    updated_at = ?, published_at = ?
                WHERE id = ?
                """,
                (title, slug, summary, content, cover_image, status,
                 is_pinned, now, published_at, guide_id),
            )
            conn.commit()
            flash('指南已更新', 'success')
            return redirect(url_for('admin.admin_guides'))
        except Exception as e:
            conn.rollback()
            flash(f'更新失败: {e}', 'error')
        finally:
            conn.close()

    return render_template('admin_guide_form.html', user=user, guide=guide)


@admin_bp.route('/admin/guides/<int:guide_id>/delete', methods=['POST'])
@login_required
def admin_guide_delete(guide_id):
    """管理后台：删除指南。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        conn.execute("DELETE FROM server_guides WHERE id = ?", (guide_id,))
        conn.commit()
        flash('指南已删除', 'success')
    except Exception:
        conn.rollback()
        flash('删除失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_guides'))


@admin_bp.route('/admin/guides/<int:guide_id>/approve', methods=['POST'])
@login_required
def admin_guide_approve(guide_id):
    """管理后台：通过审核。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        guide = conn.execute(
            "SELECT g.title, u.email FROM server_guides g "
            "LEFT JOIN users u ON g.author_id = u.id WHERE g.id = ?",
            (guide_id,),
        ).fetchone()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """
            UPDATE server_guides
            SET status = 'approved', updated_at = ?, published_at = ?, rejected_reason = ''
            WHERE id = ?
            """,
            (now, now, guide_id),
        )
        conn.commit()
        flash('指南已通过审核', 'success')

        if guide:
            _notify_author_guide_result(guide['title'], guide['email'] or '', approved=True)
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_guides'))


@admin_bp.route('/admin/guides/<int:guide_id>/reject', methods=['POST'])
@login_required
def admin_guide_reject(guide_id):
    """管理后台：拒绝审核。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    reason = (request.form.get('reason') or '').strip()

    conn = get_db()
    try:
        guide = conn.execute(
            "SELECT g.title, u.email FROM server_guides g "
            "LEFT JOIN users u ON g.author_id = u.id WHERE g.id = ?",
            (guide_id,),
        ).fetchone()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """
            UPDATE server_guides
            SET status = 'rejected', updated_at = ?, rejected_reason = ?
            WHERE id = ?
            """,
            (now, reason, guide_id),
        )
        conn.commit()
        flash('指南已拒绝', 'success')

        if guide:
            _notify_author_guide_result(guide['title'], guide['email'] or '', approved=False, reason=reason)
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_guides'))
