"""输入验证与安全清洗 —— 统一管理所有用户输入的格式校验与安全过滤。

集中管理验证规则，避免重复代码和验证遗漏。
所有验证函数返回 (is_valid, error_message) 元组。
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# 弱密码库（常见易猜密码，不区分大小写匹配）
# ---------------------------------------------------------------------------
_WEAK_PASSWORDS: set = {
    # 数字序列
    '12345678', '123456789', '1234567890', '12345678910',
    '11111111', '22222222', '33333333', '44444444',
    '55555555', '66666666', '77777777', '88888888', '99999999',
    '00000000', '01234567', '12341234', '12345678901',
    '11223344', '11112222', '12121212', '123123123',
    # 字母序列
    'aaaaaaaa', 'bbbbbbbb', 'cccccccc', 'dddddddd',
    'abcdefgh', 'abcdefg', 'abcdefghij', 'abcabcabc',
    'abcdabcd', 'qwertyui', 'qwertyuiop', 'asdfghjk',
    'zxcvbnmm', 'qwertyuiop[]', 'asdfghjkl;\'',
    'zxcvbnm,./', 'qazwsxed', 'qwertyuio',
    # 常见密码
    'password', 'password1', 'password123', 'passw0rd',
    'admin123', 'admin1234', 'admin12345', 'adminadmin',
    'root1234', 'rootroot', 'manager', 'guest123',
    'test1234', 'testtest', 'temp1234', 'default',
    'iloveyou', 'sunshine', 'princess', 'dragon',
    'monkey', 'football', 'baseball', 'welcome',
    'master', 'shadow', 'shadow123', 'killer',
    'superman', 'batman', 'starwars', 'trustno1',
    'hello123', 'helloworld', 'letmein', 'whatever',
    'pass1234', 'passwd123', 'changeme', 'changeme123',
    '1q2w3e4r', '1qaz2wsx', 'qwe123', 'qweasd',
    # 常见中文密码
    'wang1234', 'zhang123', 'li123456', 'chen123456',
    'yang1234', 'zhao1234', 'huang123', 'wu123456',
    'xiao123', 'liu12345', 'zhou1234', 'lin12345',
    'he123456', 'guo12345', 'ma123456', 'zhu1234',
    'luo12345', 'liang123', 'song1234', 'tang1234',
    # 键盘模式
    '1q2w3e4r5t', 'qwerty123', 'qwerty12345', 'qwerty12',
    'asdfgh123', 'zxcvbn123', '1qazxsw2', 'qazwsx123',
    '!@#$%^&*', '!@#$%^&*()', '1234qwer', '1234asdf',
    'qwer1234', 'asdf1234', 'zxcv1234',
    # 重复模式
    'abababab', 'aabbccdd', 'abc123456',
    '123qweasd', '123qweasdzxc', 'abc123abc',
    'abcd1234', 'a1b2c3d4', 'pass123456',
    'password!', 'password12', 'password1234',
    'admin!', 'admin123!', 'root123!',
    'P@ssw0rd', 'P@ssword', 'p@ssword123',
    'Password1', 'Password123', 'Password123!',
    'Admin123', 'Admin123!', 'Root123',
    'Server123', 'Minecraft1', 'MCserver1',
    'mcserver123', 'minecraft123', 'minecraft',
}

# 用户名中禁止的字符（用于网站用户名）
_FORBIDDEN_USERNAME_CHARS_RE = re.compile(
    r'[<>\'\"\\;&|`$(){}[\]!#%]'
)
# 用户名中允许的 Unicode 类别
_ALLOWED_USERNAME_CATEGORIES = {
    'Lu', 'Ll', 'Lt', 'Lm', 'Lo',  # 字母
    'Nd',                           # 数字
    'Pd',                           # 连接号/短横
    'Pc',                           # 连接符（下划线）
    'Mn', 'Mc',                     # 组合标记
    'Sk',                           # 修饰符号
    'So',                           # 其他符号
}

# MC 用户名规范（Mojang 规则）
_MC_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_]{3,16}$')

# 邮箱基本格式
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# RCON 命令注入检测
_RCON_INJECTION_RE = re.compile(
    r'[;\n\r`$(){}|&"]'
)

# Shell 命令注入检测
_SHELL_INJECTION_RE = re.compile(
    r'[;&|`$(){}<>]|(?<!\\)\n'
)


# ---------------------------------------------------------------------------
# 弱密码检测
# ---------------------------------------------------------------------------

def is_weak_password(password: str) -> bool:
    """检查密码是否为弱密码（常见易猜密码）。

    不区分大小写，匹配时忽略首尾空白。
    返回 True 表示该密码是弱密码，应拒绝使用。
    """
    stripped = password.strip().lower()
    # 直接匹配
    if stripped in _WEAK_PASSWORDS:
        return True
    # 检查是否只包含单一重复字符（如 aaaaaaaa）
    if len(stripped) >= 4 and len(set(stripped)) == 1:
        return True
    # 检查连续递增/递减序列（如 abcdefg, 1234567）
    if _is_sequential(stripped, 4):
        return True
    return False


def _is_sequential(s: str, min_len: int = 4) -> bool:
    """检查字符串是否连续递增/递减序列（仅检查整个字符串，不检查子串）。"""
    if len(s) < min_len:
        return False
    # 检查整个字符串是否连续递增
    asc = True
    desc = True
    for j in range(1, len(s)):
        diff = ord(s[j]) - ord(s[j - 1])
        if diff != 1:
            asc = False
        if diff != -1:
            desc = False
        if not asc and not desc:
            return False
    # 只针对字母数字序列
    if all(c.isalnum() for c in s):
        return True
    return False


# ---------------------------------------------------------------------------
# MC 用户名验证
# ---------------------------------------------------------------------------

def validate_mc_username(username: str) -> tuple:
    """验证 Minecraft 用户名格式。

    Minecraft 账号规则（Mojang）：
    - 长度 3-16 字符
    - 只允许字母（a-z, A-Z）、数字（0-9）、下划线（_）
    - 不能以下划线开头或结尾（宽松检查，仅警告）
    - 不能包含空格、特殊字符

    Args:
        username: 待验证的 MC 用户名

    Returns:
        (is_valid, error_message)
    """
    raw = (username or '').strip()
    if not raw:
        return False, 'MC 用户名不能为空'
    if len(raw) < 3:
        return False, 'MC 用户名至少 3 个字符'
    if len(raw) > 16:
        return False, 'MC 用户名不能超过 16 个字符'
    if not _MC_USERNAME_RE.match(raw):
        return False, 'MC 用户名只能包含字母、数字和下划线'
    # 检测 RCON 命令注入风险
    if _RCON_INJECTION_RE.search(raw):
        return False, 'MC 用户名包含非法字符'
    # 检测反串（如连续下划线）
    if '__' in raw:
        return False, 'MC 用户名不能包含连续下划线'
    return True, ''


# ---------------------------------------------------------------------------
# 网站用户名验证
# ---------------------------------------------------------------------------

def validate_website_username(username: str) -> tuple:
    """验证网站用户名格式。

    规则：
    - 长度 2-20 字符
    - 允许中文、字母、数字、下划线、短横
    - 禁止 HTML/JS 注入字符（< > ' " 反斜杠 ; & | ` $ ( ) { } [ ] ! # %）
    - 禁止空白字符
    - 不能以特殊字符开头或结尾

    Args:
        username: 待验证的用户名

    Returns:
        (is_valid, error_message)
    """
    raw = (username or '').strip()
    if not raw:
        return False, '用户名不能为空'
    if len(raw) < 2:
        return False, '用户名至少 2 个字符'
    if len(raw) > 20:
        return False, '用户名不能超过 20 个字符'

    # 检查是否有空白字符
    if ' ' in raw or '\t' in raw:
        return False, '用户名不能包含空格'

    # 检查禁止字符
    if _FORBIDDEN_USERNAME_CHARS_RE.search(raw):
        return False, '用户名包含非法字符'

    # 检查每个字符的 Unicode 类别是否允许
    for ch in raw:
        cat = unicodedata.category(ch)
        if cat not in _ALLOWED_USERNAME_CATEGORIES:
            return False, f'用户名包含不允许的字符: {ch!r}'

    return True, ''


# ---------------------------------------------------------------------------
# 密码强度验证
# ---------------------------------------------------------------------------

def validate_password_strength(password: str, min_length: int = 8) -> tuple:
    """验证密码强度。

    规则：
    - 至少 min_length 位（默认 8）
    - 包含小写字母
    - 包含大写字母
    - 包含数字
    - 包含特殊字符
    - 不能是弱密码

    Args:
        password: 待验证的密码
        min_length: 最小长度

    Returns:
        (is_valid, error_message)
    """
    if not password:
        return False, '密码不能为空'
    if len(password) < min_length:
        return False, f'密码至少 {min_length} 位'
    if len(password) > 128:
        return False, '密码不能超过 128 位'

    if not any(c.islower() for c in password):
        return False, '密码必须包含至少一个小写字母'
    if not any(c.isupper() for c in password):
        return False, '密码必须包含至少一个大写字母'
    if not any(c.isdigit() for c in password):
        return False, '密码必须包含至少一个数字'
    if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/~`' for c in password):
        return False, '密码必须包含至少一个特殊字符'

    # 弱密码检查
    if is_weak_password(password):
        return False, '密码过于简单，请使用更复杂的密码'

    return True, ''


# ---------------------------------------------------------------------------
# 游戏账号密码验证（简化版，适用于 MC 账号）
# ---------------------------------------------------------------------------

def validate_game_password(password: str, min_length: int = 8) -> tuple:
    """验证游戏账号密码强度。

    规则：
    - 至少 min_length 位（默认 8）
    - 至少包含字母和数字
    - 不能是弱密码
    - 不能包含空格（可能影响 RCON 命令）

    Args:
        password: 待验证的密码
        min_length: 最小长度

    Returns:
        (is_valid, error_message)
    """
    if not password:
        return False, '密码不能为空'
    if len(password) < min_length:
        return False, f'密码至少 {min_length} 位'
    if len(password) > 128:
        return False, '密码不能超过 128 位'

    if ' ' in password:
        return False, '密码不能包含空格'

    if not any(c.isalpha() for c in password):
        return False, '密码必须包含至少一个字母'
    if not any(c.isdigit() for c in password):
        return False, '密码必须包含至少一个数字'

    # 弱密码检查
    if is_weak_password(password):
        return False, '密码过于简单，请使用更复杂的密码'

    return True, ''


# ---------------------------------------------------------------------------
# RCON 命令安全
# ---------------------------------------------------------------------------

def sanitize_rcon_input(text: str) -> str:
    """清洗 RCON 输入，防止命令注入。

    移除可能导致命令注入的特殊字符（; | & ` $ ( ) { } \n \r），
    保留字母、数字、下划线、短横、点、@、#、空格。

    Args:
        text: 待清洗的输入

    Returns:
        清洗后的安全文本
    """
    if not text:
        return ''
    # 替换命令注入字符为空
    safe = _RCON_INJECTION_RE.sub('', text)
    # 额外限制只保留安全字符
    safe = re.sub(r'[^\w\s@#.\-]', '', safe)
    return safe.strip()


def sanitize_rcon_password(password: str) -> str:
    """清洗 RCON 密码参数，确保安全传递给命令。

    Args:
        password: 密码

    Returns:
        安全引用的密码字符串
    """
    if not password:
        return ''
    # 移除命令注入字符（含引号，防止引号逃逸）
    safe = _RCON_INJECTION_RE.sub('', password)
    # 总是用引号包裹，防止空格问题
    return f'"{safe}"'


def sanitize_rcon_username(username: str) -> str:
    """清洗 RCON 用户名参数，确保安全传递给命令。

    Args:
        username: MC 用户名

    Returns:
        安全引用的用户名字符串
    """
    if not username:
        return ''
    # 移除命令注入字符
    safe = _RCON_INJECTION_RE.sub('', username)
    # 用户名不应包含空格，直接返回
    return safe.split()[0] if safe else ''


# ---------------------------------------------------------------------------
# 邮箱格式验证
# ---------------------------------------------------------------------------

def validate_email_format(email: str) -> tuple:
    """验证邮箱格式。

    Args:
        email: 待验证的邮箱

    Returns:
        (is_valid, error_message)
    """
    raw = (email or '').strip()
    if not raw:
        return False, '邮箱不能为空'
    if len(raw) > 254:
        return False, '邮箱地址过长'
    if not _EMAIL_RE.match(raw):
        return False, '邮箱格式不正确'
    return True, ''


# ---------------------------------------------------------------------------
# 封禁理由验证
# ---------------------------------------------------------------------------

def validate_ban_reason(reason: str) -> tuple:
    """验证封禁理由。

    Args:
        reason: 封禁理由

    Returns:
        (is_valid, error_message)
    """
    raw = (reason or '').strip()
    if not raw:
        return False, '封禁理由不能为空'
    if len(raw) > 500:
        return False, '封禁理由不能超过 500 字'
    if _FORBIDDEN_USERNAME_CHARS_RE.search(raw):
        return False, '封禁理由包含非法字符'
    return True, ''