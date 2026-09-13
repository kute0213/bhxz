"""管理员后台 —— 游戏账号注册申请审批、封禁管理。

（原 routes/admin/game_accounts.py 精简重命名：已删除游戏账号绑定管理部分）
"""

from flask import request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from routes.admin import admin_bp
from services.game_accounts.registration_service import (
    get_pending_applications, get_all_applications,
    approve_application, reject_application,
    ban_account, unban_account, get_banned_accounts,
)
from services.validation import validate_mc_username, validate_ban_reason


@admin_bp.route('/admin/game-accounts')
@admin_required
def admin_game_accounts():
    """账号注册申请管理页面。"""
    return render_page('admin/admin_game_accounts.html')


# ---------------------------------------------------------------------------
# 注册申请 API
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/api/game-accounts/applications')
@admin_required
def api_get_applications():
    """获取所有注册申请记录。"""
    pending = get_pending_applications()
    all_apps = get_all_applications()
    return jsonify({
        'success': True,
        'pending': pending,
        'all': all_apps,
    })


@admin_bp.route('/admin/api/game-accounts/applications/<int:app_id>/approve', methods=['POST'])
@admin_required
def api_approve_application(app_id):
    """审批通过注册申请。"""
    user = get_current_user()
    succ, msg = approve_application(app_id, user['id'])
    return jsonify({'success': succ, 'message': msg})


@admin_bp.route('/admin/api/game-accounts/applications/<int:app_id>/reject', methods=['POST'])
@admin_required
def api_reject_application(app_id):
    """驳回注册申请。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    succ, msg = reject_application(app_id, user['id'], reason)
    return jsonify({'success': succ, 'message': msg})


# ---------------------------------------------------------------------------
# 封禁管理 API
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/api/game-accounts/bans')
@admin_required
def api_get_bans():
    """获取封禁列表。"""
    bans = get_banned_accounts()
    return jsonify({'success': True, 'bans': bans})


@admin_bp.route('/admin/api/game-accounts/bans', methods=['POST'])
@admin_required
def api_ban():
    """封禁 MC 账号申请资格。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    reason = (data.get('reason') or '').strip()

    valid_mc, mc_err = validate_mc_username(mc_username)
    if not valid_mc:
        return jsonify({'success': False, 'message': mc_err}), 400

    valid_reason, reason_err = validate_ban_reason(reason)
    if not valid_reason:
        return jsonify({'success': False, 'message': reason_err}), 400

    succ, msg = ban_account(mc_username, reason, user['id'])
    return jsonify({'success': succ, 'message': msg})


@admin_bp.route('/admin/api/game-accounts/bans/<path:mc_username>', methods=['DELETE'])
@admin_required
def api_unban(mc_username):
    """解除封禁。"""
    valid_mc, mc_err = validate_mc_username(mc_username)
    if not valid_mc:
        return jsonify({'success': False, 'message': mc_err}), 400
    succ, msg = unban_account(mc_username)
    return jsonify({'success': succ, 'message': msg})
