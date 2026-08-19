"""公开页面路由：首页、性能监控、背景图片。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

import os

from flask import render_template, send_from_directory, abort, make_response
from core.auth import get_current_user
from core.db import get_db
from config import get_config_value, UPLOAD_BACKGROUNDS_DIR
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


# ---------------------------------------------------------------------------
# 背景图片服务
# ---------------------------------------------------------------------------

# 支持的图片扩展名，按优先级排序
_BG_EXTENSIONS = ['webp', 'jpg', 'jpeg', 'png', 'gif']

# 常见的屏幕比例映射
_BG_RATIO_ALIASES = {
    '16_9': '16_9',
    '16:9': '16_9',
    '16_10': '16_10',
    '16:10': '16_10',
    '8_5': '16_10',
    '4_3': '4_3',
    '4:3': '4_3',
    '3_2': '3_2',
    '3:2': '3_2',
    '9_16': '9_16',
    '9:16': '9_16',
    '3_4': '3_4',
    '3:4': '3_4',
    '1_1': '1_1',
    '1:1': '1_1',
}


@main_bp.route('/background/<ratio>')
def serve_background(ratio):
    """根据屏幕比例返回合适的背景图片。

    查找顺序：
    1. bg_<ratio>.webp / .jpg / .jpeg / .png / .gif
    2. 如果找不到精确比例，尝试最接近的常见比例

    图片由 `background-size: cover` 配合 CSS 裁剪，服务端仅做选择。
    """
    normalized = _BG_RATIO_ALIASES.get(ratio, ratio)

    filename = None
    for ext in _BG_EXTENSIONS:
        candidate = f'bg_{normalized}.{ext}'
        if os.path.isfile(os.path.join(UPLOAD_BACKGROUNDS_DIR, candidate)):
            filename = candidate
            break

    if not filename:
        # 尝试从目录中随机一张作为兜底
        try:
            entries = os.listdir(UPLOAD_BACKGROUNDS_DIR)
            bg_files = [f for f in entries if f.startswith('bg_') and any(
                f.endswith('.' + ext) for ext in _BG_EXTENSIONS
            )]
            if bg_files:
                filename = bg_files[0]
        except OSError:
            pass

    if not filename:
        abort(404)

    resp = make_response(send_from_directory(UPLOAD_BACKGROUNDS_DIR, filename))
    # 缓存 1 小时，减少重复请求
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp