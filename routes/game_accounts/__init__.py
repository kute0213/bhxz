"""申请账号蓝图 —— 玩家申请注册 Minecraft 游戏账号（需管理员审批）。

已移除游戏账号绑定/改密功能（彻底删除），仅保留申请注册能力。
申请记录进入 game_account_registrations 表，管理员在后台审批。
"""

from flask import Blueprint, render_template, request, jsonify

from core.auth import login_required, get_current_user
from services.game_accounts.registration_service import create_application

account_apply_bp = Blueprint('account_apply', __name__, url_prefix='/game-accounts')


@account_apply_bp.route('/apply')
@login_required
def apply_page():
    """申请注册游戏账号页面。"""
    user = get_current_user()
    return render_template('game_accounts/apply.html', user=user)


@account_apply_bp.route('/api/apply-register', methods=['POST'])
@login_required
def api_apply_register():
    """提交游戏账号注册申请（AJAX）。

    请求体 JSON:
        mc_username:  MC 用户名
        captcha_id:   图形验证码 ID
        captcha:      图形验证码内容

    返回:
        { success, message }
    """
    from services.captcha import captcha_service

    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    captcha_id = (data.get('captcha_id') or '').strip()
    captcha_input = (data.get('captcha') or '').strip()

    # ── 基础校验 ──
    if not mc_username:
        return jsonify({'success': False, 'message': 'MC 用户名不能为空'}), 400
    if len(mc_username) < 3:
        return jsonify({'success': False, 'message': 'MC 用户名至少 3 个字符'}), 400
    if len(mc_username) > 16:
        return jsonify({'success': False, 'message': 'MC 用户名不能超过 16 个字符'}), 400

    # ── 校验图形验证码 ──
    if not captcha_id or not captcha_input:
        return jsonify({'success': False, 'message': '请完成图形验证码'}), 400
    if not captcha_service.verify(captcha_id, captcha_input):
        return jsonify({'success': False, 'message': '验证码错误或已过期'}), 400
    captcha_service.consume(captcha_id)

    # ── 提交申请 ──
    success, message = create_application(user['id'], mc_username)
    return jsonify({'success': success, 'message': message})
