"""邮箱验证码 API 路由。"""

from flask import Blueprint, request, jsonify, session

from services.email_code import email_code_service, normalize_email
from services.email import email_service
from config import get_config_value


email_code_bp = Blueprint('email_code', __name__)


def _is_valid_email(email: str) -> bool:
    """简单邮箱格式校验。"""
    if '@' not in email:
        return False
    local, domain = email.rsplit('@', 1)
    if not local or not domain or '.' not in domain:
        return False
    parts = domain.rsplit('.', 1)
    return len(parts) == 2 and len(parts[1]) >= 2


@email_code_bp.route('/api/email/check-enabled')
def check_email_enabled():
    """检查邮件功能是否启用（前端用于决定是否显示邮箱验证码字段）。"""
    return jsonify({
        'enabled': email_service.is_enabled(),
        'register_verify': get_config_value('REGISTER_EMAIL_VERIFY', False),
    })


@email_code_bp.route('/api/email/send-code', methods=['POST'])
def send_email_code():
    """发送邮箱验证码。

    请求 JSON:
    {
        "email": "user@example.com",
        "purpose": "注册"  // 可选，默认 "注册"
    }

    返回 JSON:
    {
        "success": true,
        "message": "验证码已发送"
    }
    """
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get('email') or '')
    purpose = data.get('purpose') or '注册'

    if not email:
        return jsonify({'success': False, 'message': '请输入邮箱地址'}), 400

    if not _is_valid_email(email):
        return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

    # 检查邮件功能是否启用
    if not email_service.is_enabled():
        return jsonify({'success': False, 'message': '邮件功能未启用'}), 400

    # 检查注册邮箱验证是否开启（仅注册场景）
    if purpose == '注册' and not get_config_value('REGISTER_EMAIL_VERIFY', False):
        return jsonify({'success': False, 'message': '注册邮箱验证未开启'}), 400

    # 发送验证码
    success, message = email_code_service.send_code(email, purpose)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 429
