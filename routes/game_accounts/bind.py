"""游戏账号绑定路由 —— 通过 RCON 验证密码并绑定到网站用户。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user
from services.easyauth_bind import bind_account
from services.validation import validate_mc_username
from core.db import get_db
from datetime import datetime
from routes.game_accounts import game_accounts_bp


@game_accounts_bp.route('/api/bind', methods=['POST'])
@login_required
def api_bind():
    """绑定 MC 游戏账号（需通过 RCON 验证游戏内密码）。

    请求体 JSON:
        username:    MC 用户名
        password:    游戏内密码

    返回:
        { success, message, username, uuid, error_code }
    """
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')

    # 基础校验
    if not username:
        return jsonify({'success': False, 'message': 'MC 用户名不能为空'}), 400
    if not password:
        return jsonify({'success': False, 'message': '密码不能为空'}), 400

    # 校验 MC 用户名格式
    valid_mc, mc_err = validate_mc_username(username)
    if not valid_mc:
        return jsonify({'success': False, 'message': mc_err}), 400

    # 检查当前用户是否已绑定账号
    conn = get_db()
    try:
        my_bind = conn.execute(
            "SELECT id, mc_username FROM game_account_bindings WHERE user_id = ?",
            (user['id'],),
        ).fetchone()
        if my_bind:
            return jsonify({'success': False, 'message': f'你已绑定账号 {my_bind["mc_username"]}，请先解绑后再绑定其他账号'}), 400
    finally:
        conn.close()

    # 检查该 MC 账号是否已被绑定
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id, user_id FROM game_account_bindings WHERE mc_username = ?",
            (username,),
        ).fetchone()
        if existing:
            return jsonify({'success': False, 'message': '该 MC 账号已被其他用户绑定'}), 400
    finally:
        conn.close()

    # 通过 RCON 验证密码
    result = bind_account(username, password)
    if not result['success']:
        return jsonify(result), 401

    # 验证通过，绑定到当前用户
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    actual_username = result['username']
    conn = get_db()
    try:
        # 再次检查（防止并发）
        existing = conn.execute(
            "SELECT id FROM game_account_bindings WHERE mc_username = ?",
            (actual_username,),
        ).fetchone()
        if existing:
            return jsonify({'success': False, 'message': '该 MC 账号已被其他用户绑定'}), 400

        conn.execute(
            "INSERT INTO game_account_bindings (user_id, mc_username, created_at) VALUES (?, ?, ?)",
            (user['id'], actual_username, now),
        )
        conn.commit()

        result['success'] = True
        result['message'] = f"账号 '{actual_username}' 绑定成功"
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'绑定失败: {e}'}), 500
    finally:
        conn.close()