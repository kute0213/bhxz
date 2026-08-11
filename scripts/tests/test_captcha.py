"""验证码服务测试：图形验证码生成、验证、消耗。"""

import os
import sys
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app import app as _app
from services.captcha import captcha_service


def setup():
    """初始化。"""
    from core.db import init_db
    init_db()


def test_captcha_generate():
    """测试验证码生成。"""
    with _app.test_client() as client:
        resp = client.get('/api/captcha/generate')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'captcha_id' in data
        assert 'image' in data
        assert data['captcha_id'] is not None


def test_captcha_verify_valid():
    """测试验证码验证（正确的验证码）。"""
    # 直接通过 service 生成（现在返回 3 个值：captcha_id, answer, image_data）
    captcha_id, answer, image_data = captcha_service.generate()
    with _app.test_client() as client:
        resp = client.post('/api/captcha/verify',
            data=json.dumps({'captcha_id': captcha_id, 'captcha': answer}),
            content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True, f"验证码验证失败: {data}"


def test_captcha_verify_invalid():
    """测试验证码验证（错误的验证码）。"""
    with _app.test_client() as client:
        resp = client.post('/api/captcha/verify',
            data=json.dumps({'captcha_id': 'nonexistent', 'captcha': '123'}),
            content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is False, "无效验证码应验证失败"


def test_captcha_verify_empty():
    """测试验证码验证（空参数，API 返回 400）。"""
    with _app.test_client() as client:
        resp = client.post('/api/captcha/verify',
            data=json.dumps({'captcha_id': '', 'captcha': ''}),
            content_type='application/json')
        assert resp.status_code == 400, f"空参数应返回 400，实际: {resp.status_code}"
        data = resp.get_json()
        assert data['success'] is False, "空验证码应验证失败"


def test_captcha_direct_service():
    """测试直接使用 captcha_service。"""
    # 生成（现在返回 3 个值：captcha_id, answer, image_data）
    captcha_id, answer, image_data = captcha_service.generate()
    assert captcha_id is not None
    assert answer is not None
    assert image_data is not None

    # 验证（不消耗）
    assert captcha_service.verify(captcha_id, answer) is True
    assert captcha_service.verify(captcha_id, 'wrong') is False

    # 消耗
    captcha_service.consume(captcha_id)

    # 消耗后验证应失败
    assert captcha_service.verify(captcha_id, answer) is False


# 运行所有测试
if __name__ == '__main__':
    setup()
    test_functions = [
        test_captcha_generate,
        test_captcha_verify_valid,
        test_captcha_verify_invalid,
        test_captcha_verify_empty,
        test_captcha_direct_service,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")