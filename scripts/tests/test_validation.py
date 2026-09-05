"""验证模块测试 —— 确保验证逻辑正确无误判。"""

from services.validation import (
    validate_mc_username, validate_website_username,
    validate_password_strength, validate_game_password,
    is_weak_password, sanitize_rcon_input,
    sanitize_rcon_password, sanitize_rcon_username,
    validate_email_format, validate_ban_reason,
)


def test_mc_username():
    """MC 用户名验证测试"""
    print('=== MC 用户名验证测试 ===')
    tests = [
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
    ]
    for username, expected in tests:
        valid, msg = validate_mc_username(username)
        status = 'PASS' if valid == expected else 'FAIL'
        print(f'  [{status}] {username!r}: valid={valid}, msg={msg!r}')


def test_website_username():
    """网站用户名验证测试"""
    print('\n=== 网站用户名验证测试 ===')
    tests = [
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
    ]
    for username, expected in tests:
        valid, msg = validate_website_username(username)
        status = 'PASS' if valid == expected else 'FAIL'
        print(f'  [{status}] {username!r}: valid={valid}, msg={msg!r}')


def test_password_strength():
    """网站密码强度测试"""
    print('\n=== 网站密码强度测试 ===')
    tests = [
        ('Abcdef1!', True),        # 8 位，含大小写字母数字特殊字符
        ('Password1!', True),      # 10 位，含大小写字母数字特殊字符，非弱密码
        ('12345678', False),       # 无字母
        ('abcdefgh', False),       # 无大写、数字、特殊字符
        ('Abcdefgh', False),       # 无数字、特殊字符
        ('Abc12345', False),       # 无特殊字符
        ('Abcd1234!@#', True),     # 强密码
        ('', False),               # 空
        ('Admin123!', False),      # 弱密码（admin123!）
        ('My_C0mpl3x!', True),     # 强密码
        ('aaaaaaaa', False),       # 无大写字母/数字/特殊字符
        ('1234567890', False),     # 无字母
        ('X!a0' + 'x' * 200, False),  # 太长
    ]
    for pwd, expected in tests:
        valid, msg = validate_password_strength(pwd)
        status = 'PASS' if valid == expected else 'FAIL'
        print(f'  [{status}] {pwd[:20]!r}: valid={valid}, msg={msg!r}')


def test_game_password():
    """游戏账号密码测试"""
    print('\n=== 游戏账号密码测试 ===')
    tests = [
        ('Abcdef1!', True),        # 8 位，含字母数字
        ('Password1!', True),      # 10 位，含字母数字
        ('12345678', False),       # 无字母
        ('abcdefghij', False),     # 无数字
        ('abc12345', True),        # 8 位，含字母数字，非弱密码
        ('', False),               # 空
        ('admin123', False),       # 弱密码
        ('My_Pass2024', True),     # 强密码
        ('abc def', False),        # 含空格
        ('a1' + 'x' * 200, False), # 太长
    ]
    for pwd, expected in tests:
        valid, msg = validate_game_password(pwd)
        status = 'PASS' if valid == expected else 'FAIL'
        print(f'  [{status}] {pwd[:20]!r}: valid={valid}, msg={msg!r}')


def test_rcon_safety():
    """RCON 命令注入防护测试"""
    print('\n=== RCON 命令注入防护测试 ===')
    tests = [
        ('Steve', 'Steve'),
        ('player;rm -rf', 'playerrm'),
        ('admin|shutdown', 'adminshutdown'),
        ('test\nname', 'testname'),
        ('hello_world', 'hello_world'),
    ]
    for inp, expected in tests:
        safe = sanitize_rcon_username(inp)
        status = 'PASS' if safe == expected else 'FAIL'
        print(f'  [{status}] sanitize_username({inp!r}) = {safe!r}')

    print('\n密码引用测试:')
    for pwd in ['password', 'my pass', 'pass;word', 'pass"word']:
        safe = sanitize_rcon_password(pwd)
        print(f'  sanitize_password({pwd!r}) = {safe!r}')


def test_weak_password():
    """弱密码检测测试"""
    print('\n=== 弱密码检测测试 ===')
    tests = [
        ('password', True),
        ('12345678', True),
        ('admin1234', True),
        ('My_C0mpl3x!', False),
        ('Abcdef1!', False),
        ('abc12345', False),
        ('aaaaaaaa', True),
        ('abcdefgh', True),
        ('', False),
    ]
    for pwd, expected in tests:
        result = is_weak_password(pwd)
        status = 'PASS' if result == expected else 'FAIL'
        print(f'  [{status}] is_weak({pwd[:20]!r}) = {result}')


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/workspace')

    test_mc_username()
    test_website_username()
    test_password_strength()
    test_game_password()
    test_rcon_safety()
    test_weak_password()
    print('\n所有测试完成！')