"""公开页面路由：首页、性能监控。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

import os
from flask import render_template, send_from_directory, current_app
from core.auth import get_current_user
from core.db import get_db
from config import get_config_value, APP_ROOT
from routes.main import main_bp


@main_bp.route('/')
def home():
    user = get_current_user()
    conn = get_db()
    try:
        mod_intros = conn.execute(
            "SELECT * FROM mod_intros ORDER BY id ASC"
        ).fetchall()
        mod_intros = [dict(r) for r in mod_intros]
    finally:
        conn.close()
    return render_template(
        'index.html', user=user, mod_intros=mod_intros,
        map_url=get_config_value('MAP_URL', 'https://map.bhxz.tw.kg'),
        qq_group_url=get_config_value('QQ_GROUP_URL', ''),
    )


@main_bp.route('/health')
def health_page():
    user = get_current_user()
    return render_template('performance.html', user=user)


@main_bp.route('/interact')
def interact_page():
    """服务器互动页面：整合大喇叭音频和背景图片入口。"""
    user = get_current_user()
    return render_template('interact.html', user=user)


@main_bp.route('/favicon')
def favicon():
    """动态 favicon 路由，根据设置返回对应的图标 SVG。

    管理员可在系统设置面板中修改 FAVICON_ICON 配置项，
    默认使用 compass（指南针）图标。
    """
    icon_name = get_config_value('FAVICON_ICON', 'compass')
    allowed = {'compass', 'mountain', 'star', 'heart'}
    if icon_name not in allowed:
        icon_name = 'compass'

    favicon_dir = os.path.join(APP_ROOT, 'static', 'favicons')
    return send_from_directory(favicon_dir, f'{icon_name}.svg', mimetype='image/svg+xml')


@main_bp.route('/favicon.ico')
def favicon_ico():
    """兼容旧版浏览器的 favicon.ico 请求，重定向到 SVG 版本。"""
    from flask import redirect
    return redirect('/favicon')
