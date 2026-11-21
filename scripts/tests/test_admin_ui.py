"""管理后台模板回归测试：统一页面骨架与关键交互容器。"""

import re
from pathlib import Path

from flask import render_template

import app as app_module


def test_glass_bg_is_solid_color():
    """磨砂底色必须是纯色：渐变→纯色的 hover 过渡会闪成透明磨砂玻璃。"""
    css = (Path(__file__).resolve().parents[2] / 'static/css/base.css').read_text(encoding='utf-8')
    match = re.search(r'--glass-bg:\s*([^;]+);', css)
    assert match, '未找到 --glass-bg 变量'
    value = match.group(1)
    assert 'gradient' not in value
    assert 'rgba(255, 255, 255' in value


def test_settings_page_uses_shared_layout():
    with app_module.app.test_request_context('/admin/settings'):
        html = render_template('admin/settings.html')
    assert '系统设置' in html
    assert 'settings-container' in html
    assert 'settings-search' in html
    assert 'category-nav' in html
    # 统一骨架只输出一次页头，不再由页面自己重复 page-container
    assert html.count('返回管理中心') == 1


def test_bot_apply_page_renders():
    with app_module.app.test_request_context('/bots/apply'):
        html = render_template(
            'bots/apply.html',
            user={'id': 1, 'username': 'alice', 'is_admin': False},
            my_applications=[],
            pending_used=0,
            pending_limit=2,
            online_players=['kute_bot'],
        )
    assert '申请假人' in html
    assert 'player-modal' in html
    assert 'kute_bot' in html


def test_admin_bots_page_uses_shared_layout():
    with app_module.app.test_request_context('/admin/bots'):
        html = render_template('admin/bots.html')
    assert '假人申请管理' in html
    assert html.count('返回管理中心') == 1


def test_mod_intros_page_uses_shared_layout():
    with app_module.app.test_request_context('/admin/mod-intros'):
        html = render_template('admin/mod_intros.html', mod_intros=[])
    assert '模组介绍管理' in html
    assert 'mod-intro-add-form' in html
    assert '返回管理中心' in html
    assert 'intro-card' not in html
