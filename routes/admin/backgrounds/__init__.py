"""管理后台背景图片管理路由。"""

from flask import jsonify, abort

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from routes.admin import admin_bp
from services import background_service
from core.shared.ip import get_client_ip


@admin_bp.route('/admin/backgrounds')
@admin_required
def admin_backgrounds_page():
    """背景图片管理页（每组默认 10 条，加载更多走 API）。"""
    pending_bgs, pending_total = background_service.get_backgrounds_page(
        status=background_service.STATUS_PENDING, page=1)
    approved_bgs, approved_total = background_service.get_backgrounds_page(
        status=background_service.STATUS_APPROVED, page=1)
    rejected_bgs, rejected_total = background_service.get_backgrounds_page(
        status=background_service.STATUS_REJECTED, page=1)

    return render_page(
        'admin/backgrounds.html',
        pending_bgs=pending_bgs, pending_total=pending_total,
        approved_bgs=approved_bgs, approved_total=approved_total,
        rejected_bgs=rejected_bgs, rejected_total=rejected_total,
        page_size=background_service.ADMIN_PAGE_SIZE,
        status_labels=background_service.STATUS_LABELS,
    )


@admin_bp.route('/admin/api/backgrounds')
@admin_required
def admin_backgrounds_api():
    """背景图片列表 API（JSON，分页，每次 10 条）。

    参数：
        status  0=待审核 1=已通过 2=已驳回
        page    页码，从 1 开始
    """
    from flask import request

    try:
        status = int(request.args.get('status', 0))
    except (TypeError, ValueError):
        status = 0
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    if status not in background_service.STATUS_LABELS:
        return jsonify({'success': False, 'message': '无效的状态'}), 400

    page_size = background_service.ADMIN_PAGE_SIZE
    items, total = background_service.get_backgrounds_page(
        status=status, page=page, page_size=page_size)

    return jsonify({
        'success': True,
        'backgrounds': items,
        'status': status,
        'page': page,
        'page_size': page_size,
        'total': total,
        'has_more': page * page_size < total,
    })


@admin_bp.route('/admin/backgrounds/<int:bg_id>/approve', methods=['POST'])
@admin_required
def admin_approve_background(bg_id):
    """通过审核。"""
    user = get_current_user()

    success, message = background_service.approve_background(
        bg_id=bg_id,
        admin_id=user['id'],
        admin_username=user['username'],
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/backgrounds/<int:bg_id>/reject', methods=['POST'])
@admin_required
def admin_reject_background(bg_id):
    """驳回审核。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = background_service.reject_background(
        bg_id=bg_id,
        admin_id=user['id'],
        admin_username=user['username'],
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/backgrounds/<int:bg_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_background(bg_id):
    """切换背景图片活跃状态。"""
    user = get_current_user()

    success, message = background_service.toggle_active(
        bg_id=bg_id,
        admin_id=user['id'],
        admin_username=user['username'],
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/backgrounds/<int:bg_id>/delete', methods=['POST'])
@admin_required
def admin_delete_background(bg_id):
    """删除背景图片。"""
    user = get_current_user()

    success, message = background_service.delete_background(
        bg_id=bg_id,
        user_id=user['id'],
        is_admin=True,
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})