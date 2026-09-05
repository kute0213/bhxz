"""游戏账号绑定/解绑路由 —— 绑定/解绑需验证 MC 服务器密码。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user
from services.game_accounts.binding_service import bind_account, unbind_account, get_bound_accounts
from services.rcon.easy_auth import verify_login
from services.validation import validate_mc_username
from routes.game_accounts import game_accounts_bp


@game_accounts_bp.route('/api/bind', methods=['POST'])
@login_required
def api_bind():
    """绑定 MC 账号（需验证 MC 服务器密码）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    mc_password = data.get('mc_password', '')

    valid, err = validate_mc_username(mc_username)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    if not mc_password:
        return jsonify({'success': False, 'message': '请输入 MC 服务器密码'}), 400

    # 验证 MC 服务器密码
    login_ok, login_msg = verify_login(mc_username, mc_password)
    if not login_ok:
        return jsonify({'success': False, 'message': login_msg}), 403

    # 验证通过后绑定
    succ, msg = bind_account(user['id'], mc_username)
    return jsonify({'success': succ, 'message': msg})


@game_accounts_bp.route('/api/unbind', methods=['POST'])
@login_required
def api_unbind():
    """解绑 MC 账号（需验证 MC 服务器密码）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    mc_password = data.get('mc_password', '')

    valid, err = validate_mc_username(mc_username)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    if not mc_password:
        return jsonify({'success': False, 'message': '请输入 MC 服务器密码'}), 400

    # 验证 MC 服务器密码
    login_ok, login_msg = verify_login(mc_username, mc_password)
    if not login_ok:
        return jsonify({'success': False, 'message': login_msg}), 403

    # 验证通过后解绑
    succ, msg = unbind_account(user['id'], mc_username)
    return jsonify({'success': succ, 'message': msg})


@game_accounts_bp.route('/api/bound')
@login_required
def api_bound():
    """获取当前用户绑定的所有 MC 账号。"""
    user = get_current_user()
    accounts = get_bound_accounts(user['id'])
    return jsonify({'success': True, 'accounts': accounts})