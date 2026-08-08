"""服务器指南公开页面：列表、详情、创建、编辑。"""

from flask import render_template, abort, request, redirect, url_for, flash
from datetime import datetime

from core.auth import get_current_user, login_required
from core.db import get_db
from services.captcha import captcha_service
from routes.guides import guides_bp


@guides_bp.route('/guides')
def guide_list():
    """公开指南列表页（默认展示已审核通过的；?my=1 展示当前用户的）。"""
    from flask import request
    user = get_current_user()
    conn = get_db()
    try:
        if user and request.args.get('my'):
            rows = conn.execute(
                """
                SELECT g.*, u.username as author_name
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.author_id = ?
                ORDER BY g.updated_at DESC
                """,
                (user['id'],),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT g.*, u.username as author_name
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.status = 'approved'
                ORDER BY g.is_pinned DESC, g.title ASC
                """
            ).fetchall()
        guides = [dict(r) for r in rows]
    finally:
        conn.close()

    return render_template('guides/index.html', user=user, guides=guides, my_mode=bool(user and request.args.get('my')))


@guides_bp.route('/guides/<slug>')
def guide_detail(slug):
    """公开指南详情页（已审核通过的可公开访问；作者可查看自己的待审核指南）。"""
    user = get_current_user()
    conn = get_db()
    try:
        if user:
            row = conn.execute(
                """
                SELECT g.*, u.username as author_name
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.slug = ? AND (g.status = 'approved' OR g.author_id = ?)
                """,
                (slug, user['id']),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT g.*, u.username as author_name
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.slug = ? AND g.status = 'approved'
                """,
                (slug,),
            ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    guide = dict(row)
    return render_template('guides/detail.html', user=user, guide=guide)


@guides_bp.route('/guides/create', methods=['GET', 'POST'])
@login_required
def guide_create():
    """成员创建新指南（进入待审核状态）。"""
    user = get_current_user()

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        summary = (request.form.get('summary') or '').strip()
        content = (request.form.get('content') or '').strip()

        if not title or not content:
            flash('标题和内容不能为空', 'error')
            return render_template('guides/form.html', user=user, guide=None)

        # 验证图形验证码
        captcha_input = (request.form.get('captcha') or '').strip()
        captcha_id = (request.form.get('captcha_id') or '').strip()
        if not captcha_service.verify(captcha_id, captcha_input):
            flash('验证码错误或已过期', 'error')
            return render_template('guides/form.html', user=user, guide=None)

        from routes.guides.api import _slugify, _ensure_unique_slug
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
            flash('指南已提交，等待管理员审核', 'success')
            return redirect(url_for('guides.guide_list', my=1))
        except Exception as e:
            conn.rollback()
            flash(f'提交失败: {e}', 'error')
        finally:
            conn.close()

    return render_template('guides/form.html', user=user, guide=None)


@guides_bp.route('/guides/<int:guide_id>/edit', methods=['GET', 'POST'])
@login_required
def guide_edit(guide_id):
    """成员编辑自己的指南（进入待审核状态）。"""
    user = get_current_user()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM server_guides WHERE id = ?",
            (guide_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    guide = dict(row)

    # 任何登录用户都可以提交修改
    if guide['author_id'] != user['id'] and not user.get('is_admin'):
        flash('注意：你不是原作者，修改后需管理员审核', 'info')

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        summary = (request.form.get('summary') or '').strip()
        content = (request.form.get('content') or '').strip()

        if not title or not content:
            flash('标题和内容不能为空', 'error')
            return render_template('guides/form.html', user=user, guide=guide)

        # 验证图形验证码
        captcha_input = (request.form.get('captcha') or '').strip()
        captcha_id = (request.form.get('captcha_id') or '').strip()
        if not captcha_service.verify(captcha_id, captcha_input):
            flash('验证码错误或已过期', 'error')
            return render_template('guides/form.html', user=user, guide=guide)

        from routes.guides.api import _slugify, _ensure_unique_slug
        conn = get_db()
        try:
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
            flash('修改已提交，等待管理员审核', 'success')
            return redirect(url_for('guides.guide_detail', slug=slug))
        except Exception as e:
            conn.rollback()
            flash(f'修改失败: {e}', 'error')
        finally:
            conn.close()

    return render_template('guides/form.html', user=user, guide=guide)
