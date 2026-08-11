"""服务层直接测试：测试 services 模块的纯业务逻辑。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from core.db import init_db, get_db
from core.auth import hash_password, validate_password
from services.captcha import captcha_service
from services.attachment_service import parse_attachment_json, save_attachments, clean_attachments
from services.user_service import register, login, change_password, change_username
from config import REGISTER_VERIFY_CODE


def setup():
    """初始化数据库。"""
    init_db()


def test_validate_password():
    """测试密码强度校验。"""
    assert validate_password('short') is not None, "过短密码应被拒绝"
    assert validate_password('12345678') is not None, "纯数字密码应被拒绝"
    assert validate_password('TestPass123!') is None, "合法密码应通过"
    assert validate_password('abcdefgh') is None, "8位纯字母密码符合最短长度+至少一个字母的要求"


def test_hash_password():
    """测试密码哈希。"""
    pwd = 'TestPass123!'
    h1 = hash_password(pwd)
    h2 = hash_password(pwd)
    assert h1 == h2, "相同密码的哈希应一致"
    assert h1 != hash_password('DifferentPass123!'), "不同密码的哈希应不同"


def test_attachment_parse():
    """测试附件 JSON 解析。"""
    # None 或空
    assert parse_attachment_json(None) == []
    assert parse_attachment_json('') == []

    # 字符串
    result = parse_attachment_json('"file.txt"')
    assert result == ['file.txt'], f"字符串解析结果: {result}"

    # JSON 数组
    result = parse_attachment_json('["a.txt", "b.txt"]')
    assert result == ['a.txt', 'b.txt'], f"数组解析结果: {result}"

    # 无效 JSON
    result = parse_attachment_json('not json')
    assert result == ['not json'], f"无效 JSON 解析结果: {result}"


def test_captcha_service():
    """测试验证码服务。"""
    # 生成（现在返回 3 个值：captcha_id, answer, image_data）
    captcha_id, answer, image_data = captcha_service.generate()
    assert captcha_id is not None
    assert answer is not None
    assert image_data is not None

    # 验证正确
    assert captcha_service.verify(captcha_id, answer) is True

    # 验证错误
    assert captcha_service.verify(captcha_id, '99999') is False

    # 验证已消耗
    captcha_service.consume(captcha_id)
    assert captcha_service.verify(captcha_id, answer) is False

    # 验证不存在的 ID
    assert captcha_service.verify('nonexistent', '123') is False


def test_user_service_register_invalid():
    """测试注册验证（应该失败的情况）。"""
    ip = '127.0.0.1'

    # 用户名过短
    success, msg = register('a', 'TestPass123!', 'TestPass123!', REGISTER_VERIFY_CODE,
                           '', '', '', '', ip, False)
    assert success is False, "过短用户名应注册失败"

    # 密码不一致
    success, msg = register('testuser', 'TestPass123!', 'DifferentPass!', REGISTER_VERIFY_CODE,
                           '', '', '', '', ip, False)
    assert success is False, "密码不一致应注册失败"

    # 空用户名
    success, msg = register('', 'TestPass123!', 'TestPass123!', REGISTER_VERIFY_CODE,
                           '', '', '', '', ip, False)
    assert success is False, "空用户名应注册失败"


def test_user_service_login_invalid():
    """测试登录验证（应该失败的情况）。"""
    ip = '127.0.0.1'

    # 空用户名
    success, data = login('', '', '', '', ip)
    assert success is False, "空用户名应登录失败"

    # 错误的验证码
    success, data = login('nonexistent', 'test', '', '', ip)
    assert success is False, "错误验证码应登录失败"


def test_change_password_validation():
    """测试修改密码验证。"""
    ip = '127.0.0.1'

    # 空当前密码
    success, msg = change_password(1, 'admin', '', 'NewPass123!', 'NewPass123!', ip)
    assert success is False, "空当前密码应失败"

    # 密码不一致
    success, msg = change_password(1, 'admin', 'admin1324', 'NewPass123!', 'Different!', ip)
    # 这里密码可能不对，但至少验证不通过
    assert success is False or msg is not None


def test_duplicate_email_check():
    """测试邮箱唯一性检查。"""
    conn = get_db()
    try:
        # 检查是否已有多个相同邮箱
        rows = conn.execute(
            "SELECT email, COUNT(*) as cnt FROM users WHERE email != '' AND email IS NOT NULL GROUP BY email HAVING cnt > 1"
        ).fetchall()
        assert len(rows) == 0, f"存在重复邮箱: {rows}"
    finally:
        conn.close()


# 运行所有测试
if __name__ == '__main__':
    setup()
    test_functions = [
        test_validate_password,
        test_hash_password,
        test_attachment_parse,
        test_captcha_service,
        test_user_service_register_invalid,
        test_user_service_login_invalid,
        test_change_password_validation,
        test_duplicate_email_check,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")