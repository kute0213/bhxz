"""验证码 API 路由。"""

from flask import Blueprint, jsonify, request
from services.captcha import captcha_service
from core.logger import log
from services.ip import get_client_ip

captcha_bp = Blueprint('captcha', __name__)


@captcha_bp.route('/api/captcha/generate')
def generate():
    """
    生成验证码图片。

    答案存于服务端内存（CaptchaService），不依赖 session，
    返回随机 captcha_id 供前端提交时携带，防止被 curl 等工具绕过。

    返回 JSON:
    {
        "success": true,
        "image": "data:image/png;base64,...",
        "captcha_id": "uuid"
    }
    """
    try:
        # 刷新时立即作废上一张，避免旧验证码继续占用内存或被重放。
        previous_id = (request.args.get('previous_id') or '').strip()
        if previous_id:
            captcha_service.consume(previous_id)

        # 生成验证码，答案存于服务端内存，返回 captcha_id
        captcha_id, _answer, image_data = captcha_service.generate()
        log('Captcha', '验证码生成成功', captcha_id=captcha_id, ip=get_client_ip())
        response = jsonify({
            'success': True,
            'image': image_data,
            'captcha_id': captcha_id,
            'code_length': 4,
            'expires_in': 300,
        })
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
    except Exception as e:
        log('Captcha', '验证码生成失败', error=str(e), ip=get_client_ip())
        return jsonify({
            'success': False,
            'message': f'生成验证码失败: {str(e)}'
        }), 500


@captcha_bp.route('/api/captcha/verify', methods=['POST'])
def verify():
    """验证图形验证码（仅校验，不消耗，供前端弹窗验证后提交表单使用）。

    请求 JSON:
    {
        "captcha_id": "uuid",
        "captcha": "用户输入"
    }

    返回 JSON:
    {
        "success": true/false,
        "message": "验证结果说明"
    }
    """
    data = request.get_json(silent=True) or {}
    captcha_id = (data.get('captcha_id') or '').strip()
    captcha_input = (data.get('captcha') or '').strip()

    if not captcha_id or not captcha_input:
        return jsonify({'success': False, 'message': '参数不完整'}), 400

    if len(captcha_input) != 4:
        return jsonify({'success': False, 'message': '请输入完整的 4 位验证码'}), 400

    if captcha_service.verify(captcha_id, captcha_input):
        log('Captcha', '验证码校验成功', captcha_id=captcha_id, ip=get_client_ip())
        return jsonify({'success': True, 'message': '验证成功'})
    else:
        log('Captcha', '验证码校验失败', captcha_id=captcha_id, ip=get_client_ip())
        return jsonify({'success': False, 'message': '验证码错误或已过期'})
