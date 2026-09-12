"""验证模块测试 —— 使用 pytest 确保验证逻辑正确无误判。"""

import pytest

from services.validation import (
    validate_mc_username, validate_website_username,
    validate_password_strength, validate_game_password,
    is_weak_password, sanitize_rcon_input,
    sanitize_rcon_password, sanitize_rcon_username,
    validate_email_format, validate_ban_reason,
)


class TestMCUsername:
    """MC 用户名验证测试"""

    @pytest.mark.parametrize('username,expected', [
        ('Steve', True),
        ('Alex_123', True),
        ('xX_Player_Xx', True),
        ('a', False),
        ('abcd1234567890abc', False),
        ('player name', False),
        ('player;name', False),
        ('player\nname', False),
        ('player__name', False),
        ('', False),
    ])
    def test_mc_username(self, username, expected):
        valid, msg = validate_mc_username(username)
        assert valid == expected, f'{username!r}: valid={valid}, msg={msg!r}'


class TestWebsiteUsername:
    """网站用户名验证测试"""

    @pytest.mark.parametrize('username,expected', [
        ('张三', True),
        ('test_user', True),
        ('test-user', True),
        ('a', False),
        ('<script>', False),
        ('test;drop', False),
        ('test user', False),
        ('admin" or 1=1', False),
        ('test_user_123', True),
        ('', False),
        ('李四', True),
        ('abc-def_123', True),
        ('test\\backslash', False),
    ])
    def test_website_username(self, username, expected):
        valid, msg = validate_website_username(username)
        assert valid == expected, f'{username!r}: valid={valid}, msg={msg!r}'


class TestPasswordStrength:
    """网站密码强度测试"""

    @pytest.mark.parametrize('password,expected', [
        ('Abcdef1!', True),
        ('Password1!', True),
        ('12345678', False),
        ('abcdefgh', False),
        ('Abcdefgh', False),
        ('Abc12345', False),
        ('Abcd1234!@#', True),
        ('', False),
        ('Admin123!', False),
        ('password123', False),
        ('My_C0mpl3x!', True),
        ('aaaaaaaa', False),
        ('1234567890', False),
        ('X!a0' + 'x' * 200, False),
    ])
    def test_password_strength(self, password, expected):
        valid, msg = validate_password_strength(password)
        assert valid == expected, f'{password[:20]!r}: valid={valid}, msg={msg!r}'


class TestGamePassword:
    """游戏账号密码测试"""

    @pytest.mark.parametrize('password,expected', [
        ('Abcdef1!', True),
        ('Password1!', True),
        ('12345678', False),
        ('abcdefghij', False),
        ('abc12345', True),
        ('', False),
        ('admin123', False),
        ('My_Pass2024', True),
        ('abc def', False),
        ('a1' + 'x' * 200, False),
    ])
    def test_game_password(self, password, expected):
        valid, msg = validate_game_password(password)
        assert valid == expected, f'{password[:20]!r}: valid={valid}, msg={msg!r}'


class TestRCONSafety:
    """RCON 命令注入防护测试"""

    @pytest.mark.parametrize('input_val,expected', [
        ('Steve', 'Steve'),
        ('player;rm -rf', 'playerrm'),
        ('admin|shutdown', 'adminshutdown'),
        ('test\nname', 'testname'),
        ('hello_world', 'hello_world'),
    ])
    def test_sanitize_username(self, input_val, expected):
        safe = sanitize_rcon_username(input_val)
        assert safe == expected, f'sanitize_username({input_val!r}) = {safe!r}'

    @pytest.mark.parametrize('input_val,expected', [
        ('password', 'password'),
        ('my pass', '"my pass"'),
        ('pass;word', 'password'),
        ('pass"word', 'password'),
    ])
    def test_sanitize_password(self, input_val, expected):
        safe = sanitize_rcon_password(input_val)
        assert safe == expected, f'sanitize_password({input_val!r}) = {safe!r}'


class TestWeakPassword:
    """弱密码检测测试"""

    @pytest.mark.parametrize('password,expected', [
        ('password', True),
        ('12345678', True),
        ('admin1234', True),
        ('My_C0mpl3x!', False),
        ('Abcdef1!', False),
        ('abc12345', False),
        ('aaaaaaaa', True),
        ('abcdefgh', True),
        ('', False),
    ])
    def test_weak_password(self, password, expected):
        result = is_weak_password(password)
        assert result == expected, f'is_weak({password[:20]!r}) = {result}'


class TestEmailFormat:
    """邮箱格式验证测试"""

    @pytest.mark.parametrize('email,expected', [
        ('user@example.com', True),
        ('test@test.com', True),
        ('', False),
        ('notanemail', False),
        ('@example.com', False),
        ('user@', False),
        ('a' * 300 + '@test.com', False),
    ])
    def test_email_format(self, email, expected):
        valid, msg = validate_email_format(email)
        assert valid == expected, f'{email!r}: valid={valid}, msg={msg!r}'


class TestBanReason:
    """封禁理由验证测试"""

    @pytest.mark.parametrize('reason,expected', [
        ('作弊', True),
        ('恶意攻击其他玩家', True),
        ('', False),
        ('a' * 501, False),
        ('<script>alert(1)</script>', False),
    ])
    def test_ban_reason(self, reason, expected):
        valid, msg = validate_ban_reason(reason)
        assert valid == expected, f'{reason!r}: valid={valid}, msg={msg!r}'