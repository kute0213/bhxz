"""模板上下文处理器 —— 向所有模板注入全局变量。"""

from flask import request, session
from markupsafe import Markup

from config import get_config_value
from services import background_service
from services.sitemap_cache import sitemap_cache
from core.csrf import get_csrf_token


def register_template_context(app):
    """注册模板上下文处理器，使全局配置在所有模板中可用。"""

    @app.context_processor
    def inject_global_config():
        # 获取所有已通过审核的背景图片（全站背景可用图片池）
        background_images = background_service.get_approved_backgrounds()

        # CSRF 模板辅助函数
        def csrf_field():
            token = get_csrf_token()
            return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')

        def csrf_token_str():
            return get_csrf_token()

        show_background = get_config_value('SHOW_BACKGROUND', True)
        bg_size = get_config_value('BACKGROUND_IMAGE_SIZE', 'cover')

        # canonical / Open Graph 使用的站点根地址：
        # 优先匹配站点配置域名（含正确协议，避免反向代理下误判为 http）；
        # 公网域名默认使用 https；仅本机地址回退到当前请求根地址。
        host = request.host.split(':')[0]
        canonical_base_url = sitemap_cache.base_url_for_host(host)
        if not canonical_base_url:
            if host and host not in ('localhost', '127.0.0.1', '::1'):
                canonical_base_url = f'https://{host}'
            else:
                canonical_base_url = request.url_root.rstrip('/')

        return {
            # 登录欢迎语只展示一次，避免刷新页面后重复打扰用户。
            'login_welcome_username': session.pop('login_welcome_username', None),
            'background_images': background_images if show_background else [],
            'background_image_size': bg_size,
            'csrf_field': csrf_field,
            'csrf_token': csrf_token_str,
            'canonical_base_url': canonical_base_url,
            # 备案号（热重载）
            'show_beian': get_config_value('SHOW_BEIAN', False),
            'icp_beian': get_config_value('ICP_BEIAN', ''),
            'police_beian': get_config_value('POLICE_BEIAN', ''),
            'copyright_year': get_config_value('COPYRIGHT_YEAR', '2024'),
            'copyright_site_name': get_config_value('COPYRIGHT_SITE_NAME', '滨海小镇'),
        }