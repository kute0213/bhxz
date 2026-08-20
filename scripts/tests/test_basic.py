"""基础测试：应用启动、路由可达性、静态文件。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app import app as _app
from core.db import get_db, init_db


def setup():
    """每个测试前初始化数据库。"""
    init_db()


def test_app_imports():
    """测试应用可正常导入。"""
    assert _app is not None, "Flask 应用导入失败"
    assert _app.secret_key is not None, "Secret key 未设置"


def test_home_page():
    """测试首页返回 200。"""
    with _app.test_client() as client:
        resp = client.get('/')
        assert resp.status_code == 200, f"首页状态码: {resp.status_code}"
        content = resp.data.decode('utf-8', errors='replace')
        assert '滨海小镇' in content or 'bhxz' in content or 'Minecraft' in content or 'minecraft' in content


def test_login_page():
    """测试登录页返回 200。"""
    with _app.test_client() as client:
        resp = client.get('/login')
        assert resp.status_code == 200, f"登录页状态码: {resp.status_code}"


def test_register_page():
    """测试注册页返回 200。"""
    with _app.test_client() as client:
        resp = client.get('/register')
        assert resp.status_code == 200, f"注册页状态码: {resp.status_code}"


def test_performance_page():
    """测试性能监控页返回 200。"""
    with _app.test_client() as client:
        resp = client.get('/performance')
        assert resp.status_code == 200, f"性能页状态码: {resp.status_code}"


def test_404_page():
    """测试 404 页面。"""
    with _app.test_client() as client:
        resp = client.get('/nonexistent-page-12345')
        assert resp.status_code == 404, f"404 状态码: {resp.status_code}"


def test_static_css():
    """测试静态 CSS 文件可访问。"""
    with _app.test_client() as client:
        resp = client.get('/static/css/base.css')
        assert resp.status_code in (200, 304), f"CSS 状态码: {resp.status_code}"


def test_static_js():
    """测试静态 JS 文件可访问。"""
    with _app.test_client() as client:
        resp = client.get('/static/js/base.js')
        assert resp.status_code in (200, 304), f"JS 状态码: {resp.status_code}"


def test_api_captcha_generate():
    """测试验证码生成 API。"""
    with _app.test_client() as client:
        resp = client.get('/api/captcha/generate')
        assert resp.status_code == 200, f"验证码生成状态码: {resp.status_code}"
        data = resp.get_json()
        assert data is not None, "响应不是 JSON"
        assert data.get('success') is True, f"验证码生成失败: {data}"
        assert 'image' in data, "缺少 image 字段"
        assert 'captcha_id' in data, "缺少 captcha_id 字段"


def test_api_check_email():
    """测试邮箱功能检查 API。"""
    with _app.test_client() as client:
        resp = client.get('/api/email/check-enabled')
        assert resp.status_code == 200, f"邮箱检查状态码: {resp.status_code}"
        data = resp.get_json()
        assert data is not None, "响应不是 JSON"


def test_api_performance():
    """测试性能数据 API。"""
    with _app.test_client() as client:
        resp = client.get('/api/performance')
        assert resp.status_code == 200, f"性能 API 状态码: {resp.status_code}"
        data = resp.get_json()
        assert data is not None, "响应不是 JSON"


def test_api_stats():
    """测试网站统计 API。"""
    with _app.test_client() as client:
        resp = client.get('/api/stats')
        assert resp.status_code == 200, f"统计 API 状态码: {resp.status_code}"
        data = resp.get_json()
        assert data is not None, "响应不是 JSON"


def test_docs_page():
    """测试文档页面。"""
    with _app.test_client() as client:
        resp = client.get('/docs')
        assert resp.status_code == 200, f"文档页状态码: {resp.status_code}"


def test_discussion_page():
    """测试讨论区页面。"""
    with _app.test_client() as client:
        resp = client.get('/discussion')
        assert resp.status_code == 200, f"讨论区状态码: {resp.status_code}"


def test_guides_page():
    """测试指南页面。"""
    with _app.test_client() as client:
        resp = client.get('/guides')
        assert resp.status_code == 200, f"指南页面状态码: {resp.status_code}"


def test_admin_redirect():
    """测试未登录访问管理后台应重定向到登录页。"""
    with _app.test_client() as client:
        resp = client.get('/admin')
        assert resp.status_code in (302, 401, 403), f"管理后台未登录状态码: {resp.status_code}"


def test_settings_redirect():
    """测试未登录访问设置页面应重定向。"""
    with _app.test_client() as client:
        resp = client.get('/settings')
        assert resp.status_code in (302, 401), f"设置页未登录状态码: {resp.status_code}"


# 运行所有测试
if __name__ == '__main__':
    setup()
    test_functions = [
        test_app_imports,
        test_home_page,
        test_login_page,
        test_register_page,
        test_performance_page,
        test_404_page,
        test_static_css,
        test_static_js,
        test_api_captcha_generate,
        test_api_check_email,
        test_api_performance,
        test_api_stats,
        test_docs_page,
        test_discussion_page,
        test_guides_page,
        test_admin_redirect,
        test_settings_redirect,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")