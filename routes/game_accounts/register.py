"""游戏账号注册申请路由 —— 提交申请（需图形验证码）。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user
from services.captcha import captcha_service
from services.game_accounts.registration_service import create_application
from services.validation import validate_mc_username, validate_game_password
from routes.game_accounts import game_accounts_bp


@game_accounts_bp.route('/api/apply-register', methods=['POST'])
@login_required
def api_apply_register():
    """提交游戏账号注册申请（需图形验证码）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mc_username = (data.get('mc_username') or '').strip()
    password = data.get('password', '')
    captcha_id = (data.get('captcha_id') or '').strip()
    captcha_input = (data.get('captcha') or '').strip()

    # 校验验证码
    if not captcha_id or not captcha_input:
        return jsonify({'success': False, 'message': '请完成图形验证码'}), 400
    if not captcha_service.verify(captcha_id, captcha_input):
        return jsonify({'success': False, 'message': '验证码错误或已过期'}), 400
    captcha_service.consume(captcha_id)

    # 校验 MC 用户名格式
    valid_mc, mc_err = validate_mc_username(mc_username)
    if not valid_mc:
        return jsonify({'success': False, 'message': mc_err}), 400

    # 校验密码强度
    valid_pwd, pwd_err = validate_game_password(password)
    if not valid_pwd:
        return jsonify({'success': False, 'message': pwd_err}), 400

    succ, msg = create_application(user['id'], mc_username, password)
    return jsonify({'success': succ, 'message': msg})