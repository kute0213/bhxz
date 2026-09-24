"""公共建筑 API 路由：搜索/列表、收藏、标签、评论、举报。"""

from datetime import datetime

from flask import request, jsonify

from core.auth import login_required, get_current_user
from core.db import get_db
from core.shared.ip import get_client_ip
from core.shared.captcha import captcha_service
from routes.buildings import buildings_bp
from services import buildings as buildings_service


@buildings_bp.route('/api/buildings')
def api_buildings_list():
    """公共建筑搜索/分页列表（JSON，供前端无刷新搜索与「加载更多」）。

    参数：
      q    关键词（匹配标题与标签）
      tag  精确标签筛选
      page 页码（从 1 开始，默认 1）
      my   为 1 时返回当前用户的建筑（需登录）
    """
    user = get_current_user()
    my_mode = bool(user and request.args.get('my'))
    query = (request.args.get('q') or '').strip()[:100]
    tag = (request.args.get('tag') or '').strip()[:32]
    page = request.args.get('page', type=int) or 1

    items, has_more = buildings_service.list_buildings(
        search=query,
        tag=tag,
        page=page,
        page_size=buildings_service.PAGE_SIZE,
        author_id=user['id'] if user else None,
        my_mode=my_mode,
    )

    favorite_ids = set()
    if user:
        favorite_ids = buildings_service.get_favorite_ids(
            user['id'], [b['id'] for b in items]
        )

    for b in items:
        b['is_favorited'] = b['id'] in favorite_ids

    return jsonify({
        'success': True,
        'buildings': items,
        'has_more': has_more,
        'page': page,
        'next_page': page + 1,
        'my_mode': my_mode,
    })


@buildings_bp.route('/buildings/<int:building_id>/favorite', methods=['POST'])
@login_required
def toggle_building_favorite(building_id):
    """收藏 / 取消收藏公共建筑（JSON）。"""
    user = get_current_user()
    success, message, is_favorited, favorite_count = buildings_service.toggle_favorite(
        user_id=user['id'], building_id=building_id,
    )
    return jsonify({
        'success': success,
        'message': message,
        'is_favorited': is_favorited,
        'favorite_count': favorite_count,
    })


@buildings_bp.route('/buildings/<int:building_id>/tags', methods=['POST'])
@login_required
def edit_building_tags(building_id):
    """编辑建筑标签（作者本人或管理员，JSON）。"""
    user = get_current_user()
    raw_tags = request.form.get('tags') or ''

    # 标签同样做内容注入检测，避免通过标签绕过内容防护
    from routes.firewall.content_filter import check_content_injection
    inj = check_content_injection(
        user_id=user['id'], content=raw_tags, content_type='building_tags',
        ip_address=get_client_ip(), username=user['username'],
    )
    if inj['blocked']:
        return jsonify({'success': False, 'message': inj['message']})

    success, message, tags = buildings_service.set_tags(
        building_id=building_id,
        user_id=user['id'],
        is_admin=bool(user.get('is_admin')),
        raw_tags=raw_tags,
    )
    return jsonify({'success': success, 'message': message, 'tags': tags})


@buildings_bp.route('/buildings/<int:building_id>/comment', methods=['POST'])
@login_required
def add_comment(building_id):
    """发表评论。"""
    user = get_current_user()

    from routes.firewall.spam import check_spam, record_activity
    from routes.firewall.content_filter import check_content_injection

    content = (request.form.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空'})

    # 内容注入检测
    inj_result = check_content_injection(
        user_id=user['id'], content=content,
        content_type='building_comment', ip_address=get_client_ip(),
        username=user['username'],
    )
    if inj_result['blocked']:
        return jsonify({'success': False, 'message': inj_result['message']})

    # 验证图形验证码
    captcha_input = (request.form.get('captcha') or '').strip()
    captcha_id = (request.form.get('captcha_id') or '').strip()
    if not captcha_service.verify(captcha_id, captcha_input):
        return jsonify({'success': False, 'message': '验证码错误或已过期'})

    if check_spam(user_id=user['id'], content_type='building_comment', content=content):
        return jsonify({'success': False, 'message': '发布过于频繁，请稍后再试'})

    conn = get_db()
    try:
        # 确认建筑存在且已审核通过（或作者自己可评论）
        building = conn.execute(
            "SELECT id, author_id, status FROM public_buildings WHERE id = ?",
            (building_id,),
        ).fetchone()
        if not building:
            return jsonify({'success': False, 'message': '建筑不存在'})
        if building['status'] != 'approved' and building['author_id'] != user['id']:
            return jsonify({'success': False, 'message': '该建筑尚未审核通过'})

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO building_comments (building_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (building_id, user['id'], content, now),
        )
        conn.commit()
        record_activity(user_id=user['id'], content_type='building_comment', content=content)

        return jsonify({
            'success': True,
            'message': '评论已发布',
            'comment': {
                'id': conn.last_insert_rowid(),
                'username': user['username'],
                'content': content,
                'created_at': now,
            },
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'评论失败: {e}'})
    finally:
        conn.close()


@buildings_bp.route('/buildings/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    """删除评论（作者本人或管理员可操作）。"""
    user = get_current_user()

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT bc.*, b.author_id as building_author_id FROM building_comments bc "
            "LEFT JOIN public_buildings b ON bc.building_id = b.id "
            "WHERE bc.id = ?",
            (comment_id,),
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '评论不存在'})

        is_own_comment = row['user_id'] == user['id']
        is_building_author = row['building_author_id'] == user['id']
        is_admin = user.get('is_admin', False)

        if not (is_own_comment or is_building_author or is_admin):
            return jsonify({'success': False, 'message': '无权删除此评论'})

        conn.execute("DELETE FROM building_comments WHERE id = ?", (comment_id,))
        conn.commit()
        return jsonify({'success': True, 'message': '评论已删除'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'删除失败: {e}'})
    finally:
        conn.close()


@buildings_bp.route('/buildings/<int:building_id>/report', methods=['POST'])
@login_required
def report_building(building_id):
    """举报公共建筑。"""
    user = get_current_user()

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        return jsonify({'success': False, 'message': '请填写举报原因'})

    conn = get_db()
    try:
        # 不能举报自己的建筑
        building = conn.execute(
            "SELECT id, author_id FROM public_buildings WHERE id = ?",
            (building_id,),
        ).fetchone()
        if not building:
            return jsonify({'success': False, 'message': '建筑不存在'})
        if building['author_id'] == user['id']:
            return jsonify({'success': False, 'message': '不能举报自己的建筑'})

        # 不能重复举报
        existing = conn.execute(
            "SELECT 1 FROM building_reports WHERE building_id = ? AND reporter_id = ? AND status = 'pending' LIMIT 1",
            (building_id, user['id']),
        ).fetchone()
        if existing:
            return jsonify({'success': False, 'message': '您已举报过此建筑，请等待管理员处理'})

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO building_reports (building_id, reporter_id, reason, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (building_id, user['id'], reason, now),
        )
        conn.commit()
        return jsonify({'success': True, 'message': '举报已提交，管理员会尽快处理'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'举报失败: {e}'})
    finally:
        conn.close()