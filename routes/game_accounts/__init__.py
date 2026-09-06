"""游戏账号蓝图 —— 申请注册 MC 账号与绑定已注册账号。"""

from flask import Blueprint, render_template, request, jsonify

from core.auth import login_required, get_current_user
from core.db import get_db
from services.easyauth_bind import bind_account
from services.rcon.easy_auth import change_password as rcon_change_password
game_accounts_bp = Blueprint('game_accounts', __name__, url_prefix='/game-accounts')


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------

@game_accounts_bp.route('/')
@login_required
def index():
    """游戏账号功能首页，显示已绑定账号列表和操作入口。"""
    user = get_current_user()
    conn = get_db()
    try:
        bound_accounts = conn.execute(
            "SELECT id, mc_username, created_at FROM game_account_bindings WHERE user_id = ? ORDER BY created_at DESC",
            (user['id'],),
        ).fetchall()
        bound_accounts = [dict(r) for r in bound_accounts]
    finally:
        conn.close()
    return render_template('game_accounts/index.html', user=user, bound_accounts=bound_accounts)


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------

@game_accounts_bp.route('/bind')
@login_required
def bind_page():
    """绑定游戏账号页面。"""
    user = get_current_user()
    return render_template('game_accounts/bind.html', user=user)


@game_accounts_bp.route('/apply')
@login_required
def apply_page():
    """申请注册游戏账号页面。"""
    user = get_current_user()
    return render_template('game_accounts/apply.html', user=user)


@game_accounts_bp.route('/change-password')
@login_required
def change_password_page():
    """修改已绑定账号密码页面。"""
    user = get_current_user()
    conn = get_db()
    try:
        bound_accounts = conn.execute(
            "SELECT id, mc_username, created_at FROM game_account_bindings WHERE user_id = ? ORDER BY created_at DESC",
            (user['id'],),
        ).fetchall()
        bound_accounts = [dict(r) for r in bound_accounts]
    finally:
        conn.close()
    return render_template('game_accounts/change_password.html', user=user, bound_accounts=bound_accounts)


# ---------------------------------------------------------------------------
# API：获取已绑定账号列表
# ---------------------------------------------------------------------------

@game_accounts_bp.route('/api/bound-accounts')
@login_required
def api_bound_accounts():
    """获取当前用户已绑定的游戏账号列表。"""
    user = get_current_user()
    conn = get_db()
    try:
        accounts = conn.execute(
            "SELECT id, mc_username, created_at FROM game_account_bindings WHERE user_id = ? ORDER BY created_at DESC",
            (user['id'],),
        ).fetchall()
        return jsonify({'success': True, 'accounts': [dict(r) for r in accounts]})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取失败: {e}'}), 500
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API：修改已绑定账号密码
# ---------------------------------------------------------------------------

@game_accounts_bp.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    """修改已绑定 MC 账号的游戏内密码。

    请求体 JSON:
        mc_username:  MC 用户名
        current_password: 当前密码（用于验证）
        new_password: 新密码

    返回:
        { success, message }
    """
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    # ── 基础校验 ──
    if not mc_username:
        return jsonify({'success': False, 'message': 'MC 用户名不能为空'}), 400
    if not current_password:
        return jsonify({'success': False, 'message': '当前密码不能为空'}), 400
    if not new_password:
        return jsonify({'success': False, 'message': '新密码不能为空'}), 400
    if len(new_password) < 4:
        return jsonify({'success': False, 'message': '新密码至少 4 个字符'}), 400
    if len(new_password) > 32:
        return jsonify({'success': False, 'message': '新密码不能超过 32 个字符'}), 400

    # ── 检查该账号是否属于当前用户 ──
    conn = get_db()
    try:
        binding = conn.execute(
            "SELECT id FROM game_account_bindings WHERE user_id = ? AND mc_username = ?",
            (user['id'], mc_username),
        ).fetchone()
        if not binding:
            return jsonify({'success': False, 'message': '该账号未绑定或不属于你'}), 400
    finally:
        conn.close()

    # ── 验证当前密码 ──
    result = bind_account(mc_username, current_password)
    if not result['success']:
        return jsonify({'success': False, 'message': '当前密码验证失败: ' + result['message']}), 401

    # ── 修改密码 ──
    try:
        succ, msg = rcon_change_password(mc_username, new_password)
        if succ:
            return jsonify({'success': True, 'message': '密码修改成功，下次登录游戏时请使用新密码'})
        else:
            return jsonify({'success': False, 'message': f'密码修改失败: {msg}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'密码修改异常: {e}'}), 500


# 导入子模块注册路由
from routes.game_accounts import register   # noqa: E402,F401
from routes.game_accounts import bind       # noqa: E402,F401