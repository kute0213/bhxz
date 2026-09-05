"""游戏账号密码修改路由 —— 修改绑定的 MC 账号密码（需验证网站密码）。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user, verify_password
from core.db import get_db
from services.game_accounts.binding_service import is_bound
from services.rcon.easy_auth import change_password
from services.validation import validate_game_password
from routes.game_accounts import game_accounts_bp


@game_accounts_bp.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    """修改绑定的 MC 账号密码（需验证网站密码）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    new_password = data.get('new_password', '')
    site_password = data.get('password', '')

    if not mc_username or not new_password:
        return jsonify({'success': False, 'message': '参数不完整'}), 400

    # 校验 MC 用户名格式
    from services.validation import validate_mc_username
    valid_mc, mc_err = validate_mc_username(mc_username)
    if not valid_mc:
        return jsonify({'success': False, 'message': mc_err}), 400

    # 校验密码强度
    valid_pwd, pwd_err = validate_game_password(new_password)
    if not valid_pwd:
        return jsonify({'success': False, 'message': pwd_err}), 400

    # 校验是否绑定
    if not is_bound(user['id'], mc_username):
        return jsonify({'success': False, 'message': '该账号未绑定，无法修改密码'}), 403

    # 验证网站密码
    if not site_password:
        return jsonify({'success': False, 'message': '请输入网站密码进行验证'}), 403
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user['id'],),
        ).fetchone()
        if not row or not verify_password(site_password, row['password_hash']):
            return jsonify({'success': False, 'message': '网站密码错误'}), 403
    finally:
        conn.close()

    succ, msg = change_password(mc_username, new_password)
    return jsonify({'success': succ, 'message': msg})