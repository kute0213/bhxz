"""服务器指南公开页面：列表、详情、创建、编辑、我的收藏。"""

from flask import abort, request, redirect, url_for, flash
from datetime import datetime

from core.auth import get_current_user, login_required
from core.helpers import render_page
from core.db import get_db
from core.shared.captcha import captcha_service
from core.shared.ip import get_client_ip
from config import get_page_size
from routes.guides import guides_bp
from routes.guides.api import _annotate_favorites


@guides_bp.route('/guides')
def guide_list():
    """公开指南列表页（默认展示已审核通过的；?my=1 展示当前用户的；?q=关键字搜索）。

    公开指南按 置顶优先 → 收藏数倒序 → 标题升序 排序。
    """
    user = get_current_user()
    my_mode = bool(user and request.args.get('my'))
    keyword = (request.args.get('q') or '').strip()[:60]
    page_size = get_page_size('GUIDES_PER_PAGE', 5)

    conn = get_db()
    try:
        where = []
        params = []
        if my_mode:
            where.append("g.author_id = ?")
            params.append(user['id'])
            order_sql = "ORDER BY g.updated_at DESC"
        else:
            where.append("g.status = 'approved'")
            order_sql = (
                "ORDER BY g.is_pinned DESC, "
                "(SELECT COUNT(*) FROM guide_favorites f WHERE f.guide_id = g.id) DESC, "
                "g.title ASC"
            )
        if keyword:
            where.append("(g.title LIKE ? OR g.summary LIKE ?)")
            like = f'%{keyword}%'
            params.extend([like, like])
        where_sql = 'WHERE ' + ' AND '.join(where)

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM server_guides g {where_sql}", params
        ).fetchone()['c']
        rows = conn.execute(
            f"""
            SELECT g.id, g.title, g.summary, g.status, g.is_pinned, g.cover_image,
                   g.created_at, g.updated_at, g.published_at, g.rejected_reason,
                   u.username as author_name,
                   (SELECT COUNT(*) FROM guide_favorites f WHERE f.guide_id = g.id) AS favorite_count
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET 0
            """,
            params + [page_size],
        ).fetchall()
        guides = [dict(r) for r in rows]
        _annotate_favorites(conn, guides, user['id'] if user else None)
    finally:
        conn.close()

    return render_page(
        'guides/index.html',
        guides=guides,
        my_mode=my_mode,
        keyword=keyword,
        has_more=total > len(guides),
    )


@guides_bp.route('/guides/<int:guide_id>')
def guide_detail(guide_id):
    """公开指南详情页（已审核通过的可公开访问；作者可查看自己的待审核指南）。"""
    user = get_current_user()
    conn = get_db()
    try:
        if user:
            row = conn.execute(
                """
                SELECT g.*, u.username as author_name,
                       (SELECT COUNT(*) FROM guide_favorites f WHERE f.guide_id = g.id) AS favorite_count,
                       (SELECT 1 FROM guide_favorites f WHERE f.guide_id = g.id AND f.user_id = ?) AS is_favorited
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.id = ? AND (g.status = 'approved' OR g.author_id = ?)
                """,
                (user['id'], guide_id, user['id']),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT g.*, u.username as author_name,
                       (SELECT COUNT(*) FROM guide_favorites f WHERE f.guide_id = g.id) AS favorite_count,
                       0 AS is_favorited
                FROM server_guides g
                LEFT JOIN users u ON g.author_id = u.id
                WHERE g.id = ? AND g.status = 'approved'
                """,
                (guide_id,),
            ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    guide = dict(row)
    # 把 SQLite 的 0/1 整数转 bool
    guide['is_favorited'] = bool(guide.get('is_favorited'))
    return render_page('guides/detail.html', guide=guide)


@guides_bp.route('/guides/favorites')
@login_required
def guide_favorites():
    """当前用户收藏的服务器指南列表。"""
    user = get_current_user()
    page_size = get_page_size('GUIDES_PER_PAGE', 5)
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT g.id, g.title, g.summary, g.status, g.is_pinned, g.cover_image,
                   g.created_at, g.updated_at, g.published_at, g.rejected_reason,
                   u.username AS author_name,
                   (SELECT COUNT(*) FROM guide_favorites f WHERE f.guide_id = g.id) AS favorite_count
            FROM guide_favorites fav
            JOIN server_guides g ON fav.guide_id = g.id
            LEFT JOIN users u ON g.author_id = u.id
            WHERE fav.user_id = ? AND g.status = 'approved'
            ORDER BY fav.created_at DESC
            LIMIT ? OFFSET 0
            """,
            (user['id'], page_size),
        ).fetchall()
        guides = [dict(r) for r in rows]
        _annotate_favorites(conn, guides, user['id'])
        # 总数用于底部「加载更多」（简化：只取首屏）
        total_row = conn.execute(
            "SELECT COUNT(*) AS c FROM guide_favorites fav "
            "JOIN server_guides g ON fav.guide_id = g.id "
            "WHERE fav.user_id = ? AND g.status = 'approved'",
            (user['id'],),
        ).fetchone()
        total = total_row['c']
    finally:
        conn.close()

    return render_page(
        'guides/favorites.html',
        guides=guides,
        has_more=total > len(guides),
    )


@guides_bp.route('/guides/create', methods=['GET', 'POST'])
@login_required
def guide_create():
    """成员创建新指南（进入待审核状态）。"""
    user = get_current_user()

    if request.method == 'POST':
        # 检查待审核内容上限
        from core.helpers import check_pending_limit
        allowed, msg = check_pending_limit(user)
        if not allowed:
            flash(msg, 'error')
            return render_page('guides/form.html', guide=None)

        title = (request.form.get('title') or '').strip()
        summary = (request.form.get('summary') or '').strip()
        content = (request.form.get('content') or '').strip()

        if not title or not content:
            flash('标题和内容不能为空', 'error')
            return render_page('guides/form.html', guide=None)

        # 内容注入检测
        from routes.firewall.content_filter import check_content_injection
        inj_result = check_content_injection(
            user_id=user['id'], content=title + '\n' + content,
            content_type='guide', ip_address=get_client_ip(),
            username=user['username'],
        )
        if inj_result['blocked']:
            flash(inj_result['message'], 'error')
            return render_page('guides/form.html', guide=None)

        # 验证图形验证码
        captcha_input = (request.form.get('captcha') or '').strip()
        captcha_id = (request.form.get('captcha_id') or '').strip()
        if not captcha_service.verify(captcha_id, captcha_input):
            flash('验证码错误或已过期', 'error')
            return render_page('guides/form.html', guide=None)

        from routes.firewall.spam import check_spam, record_activity
        if check_spam(user_id=user['id'], content_type='guide', content=title):
            flash('发布过于频繁，请稍后再试', 'error')
            return render_page('guides/form.html', guide=None)

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
            record_activity(user_id=user['id'], content_type='guide', content=title)
            flash('指南已提交，等待管理员审核', 'success')
            return redirect(url_for('guides.guide_list', my=1))
        except Exception as e:
            conn.rollback()
            flash(f'提交失败: {e}', 'error')
        finally:
            conn.close()

    return render_page('guides/form.html', guide=None)


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
            return render_page('guides/form.html', guide=guide)

        # 内容注入检测
        from routes.firewall.content_filter import check_content_injection
        inj_result = check_content_injection(
            user_id=user['id'], content=title + '\n' + content,
            content_type='guide', ip_address=get_client_ip(),
            username=user['username'],
        )
        if inj_result['blocked']:
            flash(inj_result['message'], 'error')
            return render_page('guides/form.html', guide=guide)

        # 验证图形验证码
        captcha_input = (request.form.get('captcha') or '').strip()
        captcha_id = (request.form.get('captcha_id') or '').strip()
        if not captcha_service.verify(captcha_id, captcha_input):
            flash('验证码错误或已过期', 'error')
            return render_page('guides/form.html', guide=guide)

        from routes.firewall.spam import check_spam, record_activity
        if check_spam(user_id=user['id'], content_type='guide', content=title):
            flash('发布过于频繁，请稍后再试', 'error')
            return render_page('guides/form.html', guide=guide)

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
            record_activity(user_id=user['id'], content_type='guide', content=title)
            flash('修改已提交，等待管理员审核', 'success')
            return redirect(url_for('guides.guide_detail', guide_id=guide_id))
        except Exception as e:
            conn.rollback()
            flash(f'修改失败: {e}', 'error')
        finally:
            conn.close()

    return render_page('guides/form.html', guide=guide)
