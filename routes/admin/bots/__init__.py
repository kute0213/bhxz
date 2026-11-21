"""管理后台 —— 假人（BOT）申请审批与下线管理。"""

from flask import request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from routes.admin import admin_bp
from services.bot_applications import (
    get_pending_applications,
    get_all_applications,
    approve_application,
    reject_application,
    kill_bot,
)


@admin_bp.route('/admin/bots')
@admin_required
def admin_bots_page():
    """假人申请审批页面。"""
    return render_page('admin/bots.html')


@admin_bp.route('/admin/api/bots')
@admin_required
def api_get_bots():
    """获取待审批与全部假人申请记录。"""
    return jsonify({
        'success': True,
        'pending': get_pending_applications(),
        'all': get_all_applications(),
    })


@admin_bp.route('/admin/api/bots/<int:app_id>/approve', methods=['POST'])
@admin_required
def api_approve_bot(app_id):
    """同意申请：执行 RCON 生成假人。"""
    user = get_current_user()
    succ, msg = approve_application(app_id, user['id'])
    return jsonify({'success': succ, 'message': msg})


@admin_bp.route('/admin/api/bots/<int:app_id>/reject', methods=['POST'])
@admin_required
def api_reject_bot(app_id):
    """驳回假人申请。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    succ, msg = reject_application(app_id, user['id'], reason)
    return jsonify({'success': succ, 'message': msg})


@admin_bp.route('/admin/api/bots/<int:app_id>/kill', methods=['POST'])
@admin_required
def api_kill_bot(app_id):
    """手动下线假人：执行 RCON 杀死指令。"""
    user = get_current_user()
    succ, msg = kill_bot(app_id, user['id'])
    return jsonify({'success': succ, 'message': msg})
