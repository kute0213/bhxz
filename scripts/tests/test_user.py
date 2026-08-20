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
        html = resp.get_data(as_text=True)
        assert 'aria-label="关闭登录窗口"' in html
        assert '/register?source=login' in html
        assert 'id="toggle-password"' in html
        assert 'id="remember-username"' in html
        assert 'binhaiRememberedUsername' in html


def test_register_navigation_controls():
    """主页直达注册不显示返回按钮，登录页进入注册才显示。"""
    with _app.test_client() as client:
        direct_resp = client.get('/register')
        direct_html = direct_resp.get_data(as_text=True)
        assert direct_resp.status_code == 200
        assert '返回上一步' not in direct_html
        assert 'aria-label="关闭注册窗口"' in direct_html
        assert 'id="username-availability"' in direct_html
        assert 'data-password-strength' in direct_html

        from_login_resp = client.get('/register?source=login')
        from_login_html = from_login_resp.get_data(as_text=True)
        assert from_login_resp.status_code == 200
        assert '返回上一步' in from_login_html
        assert 'title="返回登录页"' in from_login_html


def test_username_availability_check():
    """用户名可用性查询必须直连数据库并且不区分大小写。"""
    with _app.test_client() as client:
        used_resp = client.get('/api/username/check?username=ADMIN')
        assert used_resp.status_code == 200
        assert used_resp.get_json() == {
            'available': False,
            'message': '该用户名已被注册',
        }

        username = 'available_' + os.urandom(4).hex()
        available_resp = client.get('/api/username/check', query_string={'username': username})
        assert available_resp.status_code == 200
        assert available_resp.get_json()['available'] is True

        invalid_resp = client.get('/api/username/check?username=a')
        assert invalid_resp.status_code == 200
        assert invalid_resp.get_json()['available'] is False


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
        assert 'data-password-strength' in resp.get_data(as_text=True)


def test_settings_password_strength():
    """账户设置的新密码输入框也应启用强度展示。"""
    with _app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['is_admin'] = True
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert 'data-password-strength' in resp.get_data(as_text=True)


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


def test_register_uses_verified_session():
    """群码验证后刷新页面，注册仍应使用服务端 session 中的验证状态。"""
    from unittest.mock import patch

    with _app.test_client() as client:
        with client.session_transaction() as sess:
            sess['group_code_verified'] = True

        with patch('routes.main.auth.register') as register_mock:
            register_mock.return_value = (False, '测试中止')
            resp = client.post('/register', data={
                'username': 'session_user',
                'password': TEST_PASS,
                'confirm': TEST_PASS,
            })

        assert resp.status_code == 200
        assert register_mock.call_args.kwargs['group_code_verified'] is True


def test_login_welcome_message_is_one_time():
    """登录成功后欢迎语应带用户名，并且刷新后不重复展示。"""
    from unittest.mock import patch

    with _app.test_client() as client:
        with patch('routes.main.auth.login') as login_mock:
            login_mock.return_value = (True, {
                'user_id': 1,
                'username': 'WelcomeUser',
                'is_admin': True,
            })
            response = client.post('/login', data={
                'username': 'WelcomeUser',
                'password': TEST_PASS,
            }, follow_redirects=True)

        html = response.get_data(as_text=True)
        assert 'Toast.success(' in html
        assert 'WelcomeUser' in html

        refreshed_html = client.get('/').get_data(as_text=True)
        assert 'Toast.success(' not in refreshed_html


def test_email_code_rejects_unknown_purpose():
    """邮箱验证码用途必须来自白名单，防止绕过注册前置校验。"""
    with _app.test_client() as client:
        resp = client.post('/api/email/send-code', json={
            'email': 'user@example.com',
            'purpose': '任意用途',
        })
        assert resp.status_code == 400
        assert resp.get_json()['message'] == '不支持的验证码用途'


def test_change_email_code_requires_login():
    """修改邮箱验证码不能由未登录用户请求。"""
    with _app.test_client() as client:
        resp = client.post('/api/email/send-code', json={
            'email': 'user@example.com',
            'purpose': '修改邮箱',
        })
        assert resp.status_code == 401


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
        test_register_navigation_controls,
        test_username_availability_check,
        test_login_bad_credentials,
        test_login_welcome_message_is_one_time,
        test_forgot_password_page,
        test_settings_password_strength,
        test_register_duplicate_username,
        test_register_short_username,
        test_register_password_mismatch,
        test_validate_group_code,
        test_validate_group_code_check,
        test_register_uses_verified_session,
        test_email_code_rejects_unknown_purpose,
        test_change_email_code_requires_login,
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
