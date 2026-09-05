"""游戏账号绑定/解绑路由。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user
from services.game_accounts.binding_service import bind_account, unbind_account, get_bound_accounts
from services.validation import validate_mc_username
from routes.game_accounts import game_accounts_bp


@game_accounts_bp.route('/api/bind', methods=['POST'])
@login_required
def api_bind():
    """绑定 MC 账号。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()

    valid, err = validate_mc_username(mc_username)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    succ, msg = bind_account(user['id'], mc_username)
    return jsonify({'success': succ, 'message': msg})


@game_accounts_bp.route('/api/unbind', methods=['POST'])
@login_required
def api_unbind():
    """解绑 MC 账号。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()

    valid, err = validate_mc_username(mc_username)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    succ, msg = unbind_account(user['id'], mc_username)
    return jsonify({'success': succ, 'message': msg})


@game_accounts_bp.route('/api/bound')
@login_required
def api_bound():
    """获取当前用户绑定的所有 MC 账号。"""
    user = get_current_user()
    accounts = get_bound_accounts(user['id'])
    return jsonify({'success': True, 'accounts': accounts})