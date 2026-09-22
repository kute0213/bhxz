"""公共建筑公开页面：列表、新建、详情。"""

from datetime import datetime

from flask import abort, request, redirect, url_for, flash

from core.auth import get_current_user, login_required
from core.db import get_db
from utils.helpers import render_page
from utils.shared.captcha import captcha_service
from utils.shared.ip import get_client_ip
from routes.buildings import buildings_bp


@buildings_bp.route('/buildings')
def building_list():
    """公共建筑列表（?my=1 展示当前用户的；默认展示已审核通过的）。"""
    user = get_current_user()
    conn = get_db()
    try:
        if user and request.args.get('my'):
            # 我的建筑：显示所有状态
            rows = conn.execute(
                """
                SELECT b.*, u.username as author_name
                FROM public_buildings b
                LEFT JOIN users u ON b.author_id = u.id
                WHERE b.author_id = ?
                ORDER BY b.updated_at DESC
                """,
                (user['id'],),
            ).fetchall()
        else:
            # 公开列表：只显示已审核通过的
            rows = conn.execute(
                """
                SELECT b.*, u.username as author_name
                FROM public_buildings b
                LEFT JOIN users u ON b.author_id = u.id
                WHERE b.status = 'approved'
                ORDER BY b.published_at DESC, b.title ASC
                """
            ).fetchall()
        buildings = [dict(r) for r in rows]
    finally:
        conn.close()

    return render_page('buildings/index.html', buildings=buildings, my_mode=bool(user and request.args.get('my')))


@buildings_bp.route('/buildings/create', methods=['GET', 'POST'])
@login_required
def building_create():
    """成员发布新公共建筑（需要审核）。"""
    user = get_current_user()

    if request.method == 'POST':
        # 检查待审核内容上限
        from utils.helpers import check_pending_limit
        allowed, msg = check_pending_limit(user)
        if not allowed:
            flash(msg, 'error')
            return render_page('buildings/create.html', building=None)

        title = (request.form.get('title') or '').strip()
        warp_name = (request.form.get('warp_name') or '').strip()
        description = (request.form.get('description') or '').strip()
        usage_info = (request.form.get('usage_info') or '').strip()
        notes = (request.form.get('notes') or '').strip()

        if not title or not warp_name or not description:
            flash('标题、领地名和介绍不能为空', 'error')
            return render_page('buildings/create.html', building=None)

        # 内容注入检测
        from routes.firewall.content_filter import check_content_injection
        inj_result = check_content_injection(
            user_id=user['id'],
            content=f'{title}\n{warp_name}\n{description}\n{usage_info}\n{notes}',
            content_type='building',
            ip_address=get_client_ip(),
            username=user['username'],
        )
        if inj_result['blocked']:
            flash(inj_result['message'], 'error')
            return render_page('buildings/create.html', building=None)

        # 验证图形验证码
        captcha_input = (request.form.get('captcha') or '').strip()
        captcha_id = (request.form.get('captcha_id') or '').strip()
        if not captcha_service.verify(captcha_id, captcha_input):
            flash('验证码错误或已过期', 'error')
            return render_page('buildings/create.html', building=None)

        from routes.firewall.spam import check_spam, record_activity
        if check_spam(user_id=user['id'], content_type='building', content=title):
            flash('发布过于频繁，请稍后再试', 'error')
            return render_page('buildings/create.html', building=None)

        conn = get_db()
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(
                """
                INSERT INTO public_buildings
                (title, warp_name, description, usage_info, notes, author_id,
                 status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (title, warp_name, description, usage_info, notes, user['id'], now, now),
            )
            conn.commit()
            record_activity(user_id=user['id'], content_type='building', content=title)
            flash('公共建筑已提交，等待管理员审核', 'success')
            return redirect(url_for('buildings.building_list', my=1))
        except Exception as e:
            conn.rollback()
            flash(f'提交失败: {e}', 'error')
        finally:
            conn.close()

    return render_page('buildings/create.html', building=None)


@buildings_bp.route('/buildings/<int:building_id>')
def building_detail(building_id):
    """公共建筑详情页（公开；作者可在我的建筑中查看）。"""
    user = get_current_user()
    conn = get_db()
    author_reported = False
    try:
        if user:
            row = conn.execute(
                """
                SELECT b.*, u.username as author_name
                FROM public_buildings b
                LEFT JOIN users u ON b.author_id = u.id
                WHERE b.id = ?
                """,
                (building_id,),
            ).fetchone()
            # 检查当前用户是否已举报过此建筑
            r = conn.execute(
                "SELECT 1 FROM building_reports WHERE building_id = ? AND reporter_id = ? LIMIT 1",
                (building_id, user['id']),
            ).fetchone()
            author_reported = r is not None
        else:
            row = conn.execute(
                """
                SELECT b.*, u.username as author_name
                FROM public_buildings b
                LEFT JOIN users u ON b.author_id = u.id
                WHERE b.id = ?
                """,
                (building_id,),
            ).fetchone()

        if not row:
            abort(404)

        building = dict(row)

        # 非审核通过且非作者本人，禁止查看
        if building['status'] != 'approved' and (not user or building['author_id'] != user['id']):
            abort(404)

        # 统计评论数
        c = conn.execute(
            "SELECT COUNT(*) AS c FROM building_comments WHERE building_id = ?",
            (building_id,),
        ).fetchone()
        building['comment_count'] = c['c'] if c else 0

        # 读取评论（含用户信息）
        comments = conn.execute(
            """
            SELECT bc.*, u.username
            FROM building_comments bc
            LEFT JOIN users u ON bc.user_id = u.id
            WHERE bc.building_id = ?
            ORDER BY bc.created_at ASC
            """,
            (building_id,),
        ).fetchall()

    finally:
        conn.close()

    # 增加浏览次数
    if user is None or (user and building['author_id'] != user['id']):
        try:
            conn = get_db()
            conn.execute(
                "UPDATE public_buildings SET view_count = view_count + 1 WHERE id = ?",
                (building_id,),
            )
            conn.close()
        except Exception:
            pass

    return render_page(
        'buildings/detail.html',
        building=building,
        comments=[dict(c) for c in comments],
        author_reported=author_reported,
    )