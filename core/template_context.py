"""模板上下文处理器 —— 向所有模板注入全局变量。"""

from flask import session
from markupsafe import Markup

from config import get_config_value
from services import background_service
from core.csrf import get_csrf_token


def register_template_context(app):
    """注册模板上下文处理器，使全局配置在所有模板中可用。"""

    @app.context_processor
    def inject_global_config():
        # 获取已启用的背景图片
        active_bgs = background_service.get_active_backgrounds()

        # CSRF 模板辅助函数
        def csrf_field():
            token = get_csrf_token()
            return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')

        def csrf_token_str():
            return get_csrf_token()

        return {
            # 登录欢迎语只展示一次，避免刷新页面后重复打扰用户。
            'login_welcome_username': session.pop('login_welcome_username', None),
            'active_backgrounds': active_bgs,
            'csrf_field': csrf_field,
            'csrf_token': csrf_token_str,
            # 备案号（热重载）
            'show_beian': get_config_value('SHOW_BEIAN', False),
            'icp_beian': get_config_value('ICP_BEIAN', ''),
            'police_beian': get_config_value('POLICE_BEIAN', ''),
            'copyright_year': get_config_value('COPYRIGHT_YEAR', '2024'),
            'copyright_site_name': get_config_value('COPYRIGHT_SITE_NAME', '滨海小镇'),
        }