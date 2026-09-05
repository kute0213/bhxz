"""蓝图注册中心 —— 集中管理所有 Flask Blueprint 的注册，保持 app.py 清爽。"""

from flask import Flask
from core.logger import log


def register_blueprints(app: Flask):
    """注册所有蓝图并返回 try_serve_public 函数。

    各蓝图请在此模块导入注册，不要直接修改 app.py。
    """
    from routes.main import main_bp
    from routes.community import community_bp
    from routes.admin import admin_bp
    from routes.api import api_bp, captcha_bp, email_code_bp
    from routes.script import script_bp
    from routes.scheduled import scheduled_bp
    from routes.docs import docs_bp
    from routes.guides import guides_bp
    from routes.discussion import discussion_bp
    from routes.backgrounds import backgrounds_bp
    from routes.public import public_bp, try_serve_public
    from routes.sitemap import sitemap_bp
    from routes.game_accounts import game_accounts_bp

    blueprints = [
        public_bp, main_bp, community_bp, admin_bp,
        api_bp, captcha_bp, email_code_bp,
        script_bp, scheduled_bp, docs_bp, guides_bp, discussion_bp,
        backgrounds_bp, sitemap_bp, game_accounts_bp,
    ]
    for bp in blueprints:
        app.register_blueprint(bp)
    log('INFO', 'RouteRegistry', f'蓝图注册完成，共 {len(blueprints)} 个')

    return try_serve_public