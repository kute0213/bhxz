"""验证码 API 路由。"""

from flask import Blueprint, session, jsonify
from services.captcha import generate_math_captcha

captcha_bp = Blueprint('captcha', __name__)


@captcha_bp.route('/api/captcha/generate')
def generate():
    """
    生成验证码图片。

    返回 JSON:
    {
        "success": true,
        "image": "data:image/png;base64,..."
    }
    """
    try:
        answer, image_data = generate_math_captcha()
        # 将答案存储在 session 中
        session['captcha_answer'] = answer
        return jsonify({
            'success': True,
            'image': image_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'生成验证码失败: {str(e)}'
        }), 500