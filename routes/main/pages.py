"""公开页面路由：首页、性能监控。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template
from core.auth import get_current_user
from core.db import get_db
from config import get_config_value
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


@main_bp.route('/performance')
def performance_page():
    user = get_current_user()
    return render_template('performance.html', user=user)


@main_bp.route('/interact')
def interact_page():
    """服务器互动页面：整合大喇叭音频和背景图片入口。"""
    user = get_current_user()
    return render_template('interact.html', user=user)
