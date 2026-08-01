"""API 路由：公开 API、验证码、邮箱验证码、管理员 API。"""

from routes.api.public import api_bp
from routes.api.admin import admin_api_bp
from routes.api.captcha import captcha_bp
from routes.api.email_code import email_code_bp

__all__ = ['api_bp', 'admin_api_bp', 'captcha_bp', 'email_code_bp']