"""管理后台背景图片管理路由。"""

from flask import render_template, jsonify, request, abort

from core.auth import admin_required, get_current_user
from routes.admin import admin_bp
from services import background_service


@admin_bp.route('/admin/backgrounds')
@admin_required
def admin_backgrounds_page():
    """背景图片管理页。"""
    user = get_current_user()

    pending_bgs = background_service.get_backgrounds(status=0)
    approved_bgs = background_service.get_backgrounds(status=1)
    rejected_bgs = background_service.get_backgrounds(status=2)

    return render_template(
        'admin/admin_backgrounds.html',
        user=user,
        pending_bgs=pending_bgs,
        approved_bgs=approved_bgs,
        rejected_bgs=rejected_bgs,
        status_labels=background_service.STATUS_LABELS,
    )


@admin_bp.route('/admin/backgrounds/<int:bg_id>/approve', methods=['POST'])
@admin_required
def admin_approve_background(bg_id):
    """通过审核。"""
    user = get_current_user()

    success, message = background_service.approve_background(
        bg_id=bg_id,
        admin_id=user['id'],
        admin_username=user['username'],
        ip_address=request.remote_addr,
    )
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/admin/backgrounds/<int:bg_id>/reject', methods=['POST'])
@login_required
def admin_reject_background(bg_id):
    """驳回审核。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    success, message = background_service.reject_background(
        bg_id=bg_id,
        admin_id=user['id'],
        admin_username=user['username'],
        ip_address=request.remote_addr,
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
        ip_address=request.remote_addr,
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
        ip_address=request.remote_addr,
    )
    return jsonify({'success': success, 'message': message})