"""验证码 API 路由。"""

from flask import Blueprint, jsonify, request
from services.captcha import captcha_service
from services.logger import log

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
        # 生成验证码，答案存于服务端内存，返回 captcha_id
        captcha_id, _answer, image_data = captcha_service.generate()
        log('Captcha', '验证码生成成功', captcha_id=captcha_id, ip=request.remote_addr)
        return jsonify({
            'success': True,
            'image': image_data,
            'captcha_id': captcha_id
        })
    except Exception as e:
        log('Captcha', '验证码生成失败', error=str(e), ip=request.remote_addr)
        return jsonify({
            'success': False,
            'message': f'生成验证码失败: {str(e)}'
        }), 500
