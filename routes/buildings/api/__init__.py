"""公共建筑 API 路由：评论、删除评论、举报。"""

from datetime import datetime

from flask import request, jsonify

from core.auth import login_required, get_current_user
from core.db import get_db
from utils.shared.ip import get_client_ip
from utils.shared.captcha import captcha_service
from routes.buildings import buildings_bp


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