"""公共建筑公开页面：列表、新建、详情。"""

from datetime import datetime

from flask import abort, request, redirect, url_for, flash

from core.auth import get_current_user, login_required
from core.db import get_db
from core.helpers import render_page
from core.shared.captcha import captcha_service
from core.shared.ip import get_client_ip
from routes.buildings import buildings_bp
from services import buildings as buildings_service


@buildings_bp.route('/buildings')
def building_list():
    """公共建筑列表。

    支持 ?my=1（我的建筑，显示全部状态）、?q=关键词（匹配标题与标签）、
    ?tag=标签（精确筛选）。默认按收藏数倒序排列，每次加载 10 条，
    前端点击「加载更多」通过 /api/buildings 继续获取。
    """
    user = get_current_user()
    my_mode = bool(user and request.args.get('my'))
    query = (request.args.get('q') or '').strip()
    active_tag = (request.args.get('tag') or '').strip()

    items, has_more = buildings_service.list_buildings(
        search=query,
        tag=active_tag,
        page=1,
        page_size=buildings_service.PAGE_SIZE,
        author_id=user['id'] if user else None,
        my_mode=my_mode,
    )

    favorite_ids = set()
    if user:
        favorite_ids = buildings_service.get_favorite_ids(
            user['id'], [b['id'] for b in items]
        )

    return render_page(
        'buildings/index.html',
        buildings=items,
        has_more=has_more,
        my_mode=my_mode,
        search_query=query,
        active_tag=active_tag,
        all_tags=buildings_service.get_all_tags(),
        favorite_ids=favorite_ids,
    )


@buildings_bp.route('/buildings/create', methods=['GET', 'POST'])
@login_required
def building_create():
    """成员发布新公共建筑（需要审核）。"""
    user = get_current_user()

    if request.method == 'POST':
        # 检查待审核内容上限
        from core.helpers import check_pending_limit
        allowed, msg = check_pending_limit(user)
        if not allowed:
            flash(msg, 'error')
            return render_page('buildings/create.html', building=None)

        title = (request.form.get('title') or '').strip()
        warp_name = (request.form.get('warp_name') or '').strip()
        description = (request.form.get('description') or '').strip()
        usage_info = (request.form.get('usage_info') or '').strip()
        notes = (request.form.get('notes') or '').strip()
        tags = buildings_service.normalize_tags(request.form.get('tags'))

        if not title or not warp_name or not description:
            flash('标题、领地名和介绍不能为空', 'error')
            return render_page('buildings/create.html', building=None)

        # 内容注入检测
        from routes.firewall.content_filter import check_content_injection
        inj_result = check_content_injection(
            user_id=user['id'],
            content=f'{title}\n{warp_name}\n{description}\n{usage_info}\n{notes}\n{tags}',
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
                (title, warp_name, description, usage_info, notes, tags, author_id,
                 status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (title, warp_name, description, usage_info, notes, tags, user['id'], now, now),
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

        # 收藏数
        fav = conn.execute(
            "SELECT COUNT(*) AS c FROM building_favorites WHERE building_id = ?",
            (building_id,),
        ).fetchone()
        building['favorite_count'] = fav['c'] if fav else 0

        # 当前用户是否已收藏
        building['is_favorited'] = False
        if user:
            r = conn.execute(
                "SELECT 1 FROM building_favorites WHERE building_id = ? AND user_id = ? LIMIT 1",
                (building_id, user['id']),
            ).fetchone()
            building['is_favorited'] = r is not None

        # 检查当前用户是否已举报过此建筑
        if user:
            r = conn.execute(
                "SELECT 1 FROM building_reports WHERE building_id = ? AND reporter_id = ? LIMIT 1",
                (building_id, user['id']),
            ).fetchone()
            author_reported = r is not None

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
