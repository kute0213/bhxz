"""游戏账号绑定/解绑路由 —— 绑定/解绑需验证网站密码。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user, verify_password
from core.db import get_db
from services.game_accounts.binding_service import bind_account, unbind_account, get_bound_accounts
from services.validation import validate_mc_username
from routes.game_accounts import game_accounts_bp


def _verify_website_password(user_id: int, password: str) -> tuple[bool, str]:
    """验证网站登录密码。

    Returns:
        (is_valid, error_message)
    """
    if not password:
        return False, '请输入网站密码进行验证'
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False, '用户不存在'
        if verify_password(password, row['password_hash']):
            return True, ''
        return False, '网站密码错误'
    finally:
        conn.close()


@game_accounts_bp.route('/api/bind', methods=['POST'])
@login_required
def api_bind():
    """绑定 MC 账号（需验证网站密码）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    password = data.get('password', '')

    valid, err = validate_mc_username(mc_username)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    pwd_ok, pwd_err = _verify_website_password(user['id'], password)
    if not pwd_ok:
        return jsonify({'success': False, 'message': pwd_err}), 403

    succ, msg = bind_account(user['id'], mc_username)
    return jsonify({'success': succ, 'message': msg})


@game_accounts_bp.route('/api/unbind', methods=['POST'])
@login_required
def api_unbind():
    """解绑 MC 账号（需验证网站密码）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    password = data.get('password', '')

    valid, err = validate_mc_username(mc_username)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    pwd_ok, pwd_err = _verify_website_password(user['id'], password)
    if not pwd_ok:
        return jsonify({'success': False, 'message': pwd_err}), 403

    succ, msg = unbind_account(user['id'], mc_username)
    return jsonify({'success': succ, 'message': msg})


@game_accounts_bp.route('/api/bound')
@login_required
def api_bound():
    """获取当前用户绑定的所有 MC 账号。"""
    user = get_current_user()
    accounts = get_bound_accounts(user['id'])
    return jsonify({'success': True, 'accounts': accounts})