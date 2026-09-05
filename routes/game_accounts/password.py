"""游戏账号密码修改路由 —— 修改绑定的 MC 账号密码。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user
from services.game_accounts.binding_service import is_bound
from services.game_accounts.rcon_client import change_password
from routes.game_accounts import game_accounts_bp


@game_accounts_bp.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    """修改绑定的 MC 账号密码。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    new_password = data.get('new_password', '')

    if not mc_username or not new_password:
        return jsonify({'success': False, 'message': '参数不完整'}), 400

    if len(new_password) < 4:
        return jsonify({'success': False, 'message': '密码至少 4 位'}), 400

    # 校验是否绑定
    if not is_bound(user['id'], mc_username):
        return jsonify({'success': False, 'message': '该账号未绑定，无法修改密码'}), 403

    succ, msg = change_password(mc_username, new_password)
    return jsonify({'success': succ, 'message': msg})