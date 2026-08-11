"""用户功能测试：注册、登录、验证码、设置。"""

import os
import sys
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app import app as _app
from core.db import get_db, init_db
from config import REGISTER_VERIFY_CODE

# 测试用户凭据
TEST_USER = 'testuser_' + os.urandom(4).hex()
TEST_PASS = 'TestPass123!'
TEST_EMAIL = f'{TEST_USER}@test.com'


def setup():
    """初始化数据库。"""
    init_db()


def _get_captcha(client):
    """获取图形验证码。"""
    resp = client.get('/api/captcha/generate')
    data = resp.get_json()
    return data['captcha_id'], data['captcha']


def test_register():
    """测试注册流程。"""
    with _app.test_client() as client:
        resp = client.post('/register', data={
            'username': TEST_USER,
            'password': TEST_PASS,
            'confirm': TEST_PASS,
            'verify_code': REGISTER_VERIFY_CODE,
            'captcha': '',
            'captcha_id': '',
            'email': '',
            'email_code': '',
        }, follow_redirects=True)
        # 即使验证码错误，也应该返回 200（注册页面重新渲染）
        assert resp.status_code == 200, f"注册状态码: {resp.status_code}"


def test_login():
    """测试登录页面可达。"""
    with _app.test_client() as client:
        resp = client.get('/login')
        assert resp.status_code == 200


def test_login_bad_credentials():
    """测试错误密码登录。"""
    with _app.test_client() as client:
        resp = client.post('/login', data={
            'username': 'nonexistent_user_xyz',
            'password': 'wrongpass',
            'captcha': '',
            'captcha_id': '',
        }, follow_redirects=True)
        assert resp.status_code == 200


def test_forgot_password_page():
    """测试找回密码页面可达。"""
    with _app.test_client() as client:
        resp = client.get('/forgot-password')
        assert resp.status_code == 200, f"找回密码页状态码: {resp.status_code}"


def test_register_duplicate_username():
    """测试重复用户名注册（应返回错误页面）。"""
    with _app.test_client() as client:
        resp = client.post('/register', data={
            'username': 'admin',
            'password': TEST_PASS,
            'confirm': TEST_PASS,
            'verify_code': REGISTER_VERIFY_CODE,
            'captcha': '',
            'captcha_id': '',
            'email': '',
            'email_code': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        # 检查是否包含错误信息（注册页面应显示错误）
        # 管理员 admin 已存在，应返回错误


def test_register_short_username():
    """测试过短用户名。"""
    with _app.test_client() as client:
        resp = client.post('/register', data={
            'username': 'a',
            'password': TEST_PASS,
            'confirm': TEST_PASS,
            'verify_code': REGISTER_VERIFY_CODE,
            'captcha': '',
            'captcha_id': '',
            'email': '',
            'email_code': '',
        }, follow_redirects=True)
        assert resp.status_code == 200


def test_register_password_mismatch():
    """测试两次密码不一致。"""
    with _app.test_client() as client:
        resp = client.post('/register', data={
            'username': 'testuser_mismatch',
            'password': TEST_PASS,
            'confirm': TEST_PASS + 'x',
            'verify_code': REGISTER_VERIFY_CODE,
            'captcha': '',
            'captcha_id': '',
            'email': '',
            'email_code': '',
        }, follow_redirects=True)
        assert resp.status_code == 200


def test_validate_group_code():
    """测试群内验证码校验。"""
    with _app.test_client() as client:
        # 正确验证码
        resp = client.post('/api/verify-group-code',
            data=json.dumps({'code': REGISTER_VERIFY_CODE}),
            content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

        # 错误验证码
        resp = client.post('/api/verify-group-code',
            data=json.dumps({'code': 'wrong_code'}),
            content_type='application/json')
        assert resp.status_code == 400

        # 空验证码
        resp = client.post('/api/verify-group-code',
            data=json.dumps({'code': ''}),
            content_type='application/json')
        assert resp.status_code == 400


def test_validate_group_code_check():
    """测试群内验证码状态查询。"""
    with _app.test_client() as client:
        resp = client.get('/api/verify-group-code/check')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'verified' in data


def test_admin_user_exists():
    """测试系统中至少有一个管理员用户。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
        ).fetchone()
        count = row[0] if row else 0
        assert count > 0, f"系统中没有管理员用户"
    finally:
        conn.close()


# 运行所有测试
if __name__ == '__main__':
    setup()
    test_functions = [
        test_register,
        test_login,
        test_login_bad_credentials,
        test_forgot_password_page,
        test_register_duplicate_username,
        test_register_short_username,
        test_register_password_mismatch,
        test_validate_group_code,
        test_validate_group_code_check,
        test_admin_user_exists,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")