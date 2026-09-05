"""邮箱验证码 API 路由。"""

from flask import Blueprint, request, jsonify, session

from services.email import email_code_service, normalize_email, email_service
from services.captcha import captcha_service
from core.logger import log
from config import get_config_value
from services.ip import get_client_ip


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
        "purpose": "注册",         // 可选，默认 "注册"
        "captcha": "1234",         // 图形验证码
        "captcha_id": "uuid",      // 验证码 ID（服务端内存存储）
        // 注册场景要求当前 session 已通过群内验证码
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
    captcha_input = (data.get('captcha') or '').strip()
    captcha_id = (data.get('captcha_id') or '').strip()

    if purpose not in ('注册', '找回密码', '修改邮箱'):
        return jsonify({'success': False, 'message': '不支持的验证码用途'}), 400

    if purpose == '修改邮箱' and 'user_id' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401

    if not email:
        log('EmailCode', '邮箱为空', ip=get_client_ip())
        return jsonify({'success': False, 'message': '请输入邮箱地址'}), 400

    if not _is_valid_email(email):
        log('EmailCode', '邮箱格式不正确', email=email, ip=get_client_ip())
        return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

    # 群内验证码校验（仅注册场景需要）
    if purpose == '注册' and not session.get('group_code_verified', False):
        log('EmailCode', '群内验证码错误', email=email, purpose=purpose, ip=get_client_ip())
        return jsonify({'success': False, 'message': '群内验证码错误，请在QQ群公告中获取正确验证码'}), 400

    # 图形验证码校验（服务端内存存储，一次性删除防止重放）
    if not captcha_service.verify(captcha_id, captcha_input):
        log('EmailCode', '图形验证码错误', email=email, purpose=purpose, ip=get_client_ip())
        return jsonify({'success': False, 'message': '图形验证码错误或已过期', 'need_captcha': True}), 400

    # 检查邮件功能是否启用
    if not email_service.is_enabled():
        log('EmailCode', '邮件功能未启用', email=email, purpose=purpose, ip=get_client_ip())
        return jsonify({'success': False, 'message': '邮件功能未启用'}), 400

    # 检查注册邮箱验证是否开启（仅注册场景）
    if purpose == '注册' and not get_config_value('REGISTER_EMAIL_VERIFY', False):
        log('EmailCode', '注册邮箱验证未开启', email=email, ip=get_client_ip())
        return jsonify({'success': False, 'message': '注册邮箱验证未开启'}), 400

    # 找回密码场景：检查邮件功能是否启用即可
    if purpose == '找回密码' and not email_service.is_enabled():
        log('EmailCode', '邮件功能未启用', email=email, purpose=purpose, ip=get_client_ip())
        return jsonify({'success': False, 'message': '邮件功能未启用'}), 400

    # 发送验证码
    success, message = email_code_service.send_code(email, purpose)
    if success:
        # 消耗验证码，防止重放攻击（前端在发送成功后已重新加载新验证码）
        captcha_service.consume(captcha_id)
        log('EmailCode', '验证码发送成功', email=email, purpose=purpose, ip=get_client_ip())
        return jsonify({'success': True, 'message': message})
    else:
        log('EmailCode', '验证码发送失败', email=email, purpose=purpose, ip=get_client_ip(), reason=message)
        return jsonify({'success': False, 'message': message}), 429
