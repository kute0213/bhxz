"""游戏账号注册申请路由 —— 提交申请（需图形验证码）。"""

from flask import request, jsonify

from core.auth import login_required, get_current_user
from services.captcha import captcha_service
from services.game_accounts.registration_service import create_application
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

    if not mc_username:
        return jsonify({'success': False, 'message': 'MC 用户名不能为空'}), 400
    if not password or len(password) < 4:
        return jsonify({'success': False, 'message': '密码至少 4 位'}), 400

    succ, msg = create_application(user['id'], mc_username, password)
    return jsonify({'success': succ, 'message': msg})