"""管理后台模板回归测试：统一页面骨架与关键交互容器。"""

from flask import render_template

import app as app_module


def test_settings_page_uses_shared_layout():
    with app_module.app.test_request_context('/admin/settings'):
        html = render_template('admin/settings.html')
    assert '系统设置' in html
    assert 'settings-container' in html
    assert 'settings-search' in html
    assert 'category-nav' in html
    # 统一骨架只输出一次页头，不再由页面自己重复 page-container
    assert html.count('返回管理中心') == 1


def test_mod_intros_page_uses_shared_layout():
    with app_module.app.test_request_context('/admin/mod-intros'):
        html = render_template('admin/mod_intros.html', mod_intros=[])
    assert '模组介绍管理' in html
    assert 'mod-intro-add-form' in html
    assert '返回管理中心' in html
    assert 'intro-card' not in html
