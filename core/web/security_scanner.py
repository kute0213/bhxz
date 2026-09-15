"""可疑访问扫描器 —— 识别 SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感文件与漏洞端点探测 / 恶意扫描 UA。

设计原则：
- 仅负责「识别」：命中特征时返回攻击类型与匹配片段，是否拦截/封禁由 middleware 结合配置开关决定
- URL（路径 + 查询串）使用全量特征（原始与 URL 解码两层匹配，覆盖编码绕过）
- 请求体（仅文本类且 ≤1MB）只使用高置信度特征（强 SQL 注入/命令注入），避免用户生成的
  Markdown/富文本内容（代码示例含 <script>、反引号、select 等）被误判
- 先做特殊字符预检，再逐类型正则匹配，降低每请求开销；静态资源（/static/）由调用方跳过

攻击类型标识与 config.py 中 SETTINGS_REGISTRY 的子开关键一一对应。
"""

import re
from urllib.parse import unquote

# 攻击类型标识（与 config.py SUSPICIOUS_BLOCK_*_ENABLED 子开关对应）
TYPE_SQL_INJECTION = 'sql_injection'
TYPE_XSS = 'xss'
TYPE_PATH_TRAVERSAL = 'path_traversal'
TYPE_COMMAND_INJECTION = 'command_injection'
TYPE_SENSITIVE_PROBE = 'sensitive_probe'
TYPE_MALICIOUS_UA = 'malicious_ua'

_RE_FLAGS = re.IGNORECASE

# ---------------------------------------------------------------------------
# URL 层特征（路径 + 查询串全量匹配）
# ---------------------------------------------------------------------------

URL_PATTERNS = {
    TYPE_SQL_INJECTION: [
        re.compile(r'\bunion\s+(all\s+)?select\b', _RE_FLAGS),
        re.compile(r"'\s*(or|and)\s+['\"]?\d+['\"]?\s*[=<>!]+\s*['\"]?\d*", _RE_FLAGS),
        re.compile(r"\b(or|and)\s+['\"]?\d+['\"]?\s*[=<>!]+\s*['\"]?\d+", _RE_FLAGS),
        re.compile(r'\b(sleep|benchmark|pg_sleep|waitfor\s+delay)\s*\(', _RE_FLAGS),
        re.compile(
            r'\b(information_schema|sqlite_master|pg_catalog|sys\.tables|mysql\.(user|db))\b',
            _RE_FLAGS,
        ),
        re.compile(r'(--|#|/\*)\s*$'),
        re.compile(r'\b(concat|concat_ws|group_concat|load_file|hex|char|ascii|substr|substring|ord)\s*\(', _RE_FLAGS),
        re.compile(r'\bselect\b[\s\S]{0,120}\bfrom\b', _RE_FLAGS),
    ],
    TYPE_XSS: [
        re.compile(r'<\s*script[\s>/]', _RE_FLAGS),
        re.compile(r'<\s*img[^>]*\bonerror\s*=', _RE_FLAGS),
        re.compile(r'<\s*(svg|iframe|object|embed|math|form)[\s>/]', _RE_FLAGS),
        re.compile(r'\bjavascript\s*:', _RE_FLAGS),
        re.compile(r'\b(vbscript|data:text/html|data:text/javascript|data:image/svg\+xml)\s*:', _RE_FLAGS),
        re.compile(r"\bon\w+\s*=\s*['\"]", _RE_FLAGS),
        re.compile(r'<\?php', _RE_FLAGS),
        re.compile(r'document\.(cookie|location|write)', _RE_FLAGS),
        re.compile(r'\b(eval|alert|prompt|confirm)\s*\(', _RE_FLAGS),
    ],
    TYPE_COMMAND_INJECTION: [
        re.compile(
            r"[;&|`]\s*(cat|ls|dir|id|whoami|uname|hostname|pwd|rm|sh|bash|cmd|powershell|"
            r"python|perl|php|ruby|nc|netcat|wget|curl|fetch|type|find|grep|echo|netstat|"
            r"ifconfig|ipconfig|kill|chmod|chown|mkdir|rmdir|dd|base64|tee|head|tail)\b",
            _RE_FLAGS,
        ),
        re.compile(r'\b(cat|ls|id|whoami|pwd|uname|hostname|netstat|ifconfig)\s+[;&|>]', _RE_FLAGS),
        re.compile(r'\$\([^)]{1,100}\)'),
        re.compile(r'`[^`]{1,100}`'),
    ],
    TYPE_PATH_TRAVERSAL: [
        re.compile(r'(\.\./|\.\.\\|\.\.%2f|\.\.%5c|%2e%2e%2f|%2e%2e%5c|%2e%2e/)', _RE_FLAGS),
        re.compile(r'%00'),
        re.compile(
            r'(/etc/(passwd|shadow|hosts|group|sudoers)|c:\\windows\\system32|boot\.ini|\.ssh/(id_rsa|authorized_keys))',
            _RE_FLAGS,
        ),
        re.compile(r'(\.\./){2,}', _RE_FLAGS),
    ],
    TYPE_SENSITIVE_PROBE: [
        # 敏感文件：.env / .git / .svn / 常见配置与后门文件
        re.compile(r'(^|/)(\.env|\.git|\.svn|\.hg|\.htaccess|\.htpasswd|\.bash_history)(/|$|\.|\?)', _RE_FLAGS),
        re.compile(
            r'(^|/)(config\.php|wp-config\.php|phpinfo(\.php)?|web\.config|adminer(\.php)?|'
            r'shell\.php|cmd\.php|eval\.php|info\.php|test\.php|php\.ini)(/|$|\?)',
            _RE_FLAGS,
        ),
        # 常见漏洞端点 / 第三方应用探测
        re.compile(
            r'(^|/)(phpmyadmin|pma|wp-admin|wp-login|wp-content|wp-includes|wordpress|joomla|'
            r'drupal|administrator|cgi-bin|jenkins|actuator|druid|solr|swagger|swagger-ui|'
            r'api-docs|graphql|v2/_catalog|webdav|owa|exchange|manager/html|phpunit|'
            r'laravel|vendor/composer)(/|$|\?)',
            _RE_FLAGS,
        ),
    ],
}

# ---------------------------------------------------------------------------
# 请求体仅使用的高置信度特征（避免误伤正常用户生成内容）
# ---------------------------------------------------------------------------

BODY_PATTERNS = {
    TYPE_SQL_INJECTION: [
        re.compile(r'\bunion\s+(all\s+)?select\b', _RE_FLAGS),
        re.compile(r"'\s*(or|and)\s+['\"]?\d+['\"]?\s*[=<>!]+\s*['\"]?\d*", _RE_FLAGS),
        re.compile(r"\b(or|and)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+", _RE_FLAGS),
        re.compile(r'\b(sleep|benchmark|pg_sleep|waitfor\s+delay)\s*\(', _RE_FLAGS),
        re.compile(r'\b(information_schema|sqlite_master|pg_catalog)\b', _RE_FLAGS),
        re.compile(r'(--|/\*)\s*$'),
        re.compile(r'\b(load_file|group_concat)\s*\(', _RE_FLAGS),
    ],
    TYPE_COMMAND_INJECTION: [
        re.compile(
            r"[;&|]\s*(cat|ls|dir|id|whoami|uname|hostname|pwd|rm|sh|bash|cmd|powershell|"
            r"wget|curl|nc|netcat|python|perl|php|ruby)\b",
            _RE_FLAGS,
        ),
        re.compile(r'\b(cat|ls|id|whoami|pwd)\s+[;&|]', _RE_FLAGS),
        re.compile(r'\$\([^)]{1,100}\)'),
    ],
}

# 恶意扫描器 User-Agent 关键词（小写匹配；仅收录明确的安全扫描工具，避免误伤合法爬虫）
MALICIOUS_UA_KEYWORDS = (
    'sqlmap', 'nikto', 'nuclei', 'wpscan', 'acunetix', 'nessus', 'openvas',
    'metasploit', 'dirb', 'dirbuster', 'gobuster', 'masscan', 'zgrab', 'hydra',
    'medusa', 'whatweb', 'fimap', 'jbrofuzz', 'w3af', 'xsser', 'beef', 'nmap',
    'c99shell', 'r57shell', 'havij', 'pangolin', 'netsparker', 'burp',
    'arachni', 'skipfish', 'zaproxy', 'owasp',
)

# 快速预检：命中危险字符集合才进入完整正则匹配
_DANGER_CHARS = set("'\"<>;&|`%()=*\\/")


def _precheck(text: str) -> bool:
    """快速预检：是否包含任何危险字符（或路径穿越点）。"""
    return any(c in _DANGER_CHARS for c in text) or '..' in text


def _match_first(patterns, text):
    """返回第一个命中的匹配片段（截断至 80 字符），未命中返回 None。"""
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            matched = m.group(0)
            return matched if len(matched) <= 80 else matched[:80]
    return None


def scan_request(path, query_string='', body='', user_agent=''):
    """扫描一次请求，返回 (attack_type, matched)；未命中返回 (None, '').

    Args:
        path: 请求路径（已解码）
        query_string: 原始查询串（未解码，内部做 URL 解码匹配以覆盖编码绕过）
        body: 文本类请求体（≤1MB，由调用方保证）
        user_agent: 请求 User-Agent
    """
    raw_url = path + ('?' + query_string if query_string else '')
    decoded_url = unquote(raw_url)

    # 1. 敏感文件/漏洞端点探测：路径即攻击指纹，无需特殊字符，优先于预检
    m = _match_first(URL_PATTERNS[TYPE_SENSITIVE_PROBE], raw_url)
    if m:
        return TYPE_SENSITIVE_PROBE, m
    m = _match_first(URL_PATTERNS[TYPE_SENSITIVE_PROBE], decoded_url)
    if m:
        return TYPE_SENSITIVE_PROBE, m

    # 2. 恶意扫描器 UA
    if user_agent:
        ua = user_agent.lower()
        for keyword in MALICIOUS_UA_KEYWORDS:
            if keyword in ua:
                return TYPE_MALICIOUS_UA, keyword

    # 3. URL 其余攻击类型：预检通过后，原始与解码两层全量匹配
    if _precheck(raw_url) or _precheck(decoded_url):
        for attack_type, patterns in URL_PATTERNS.items():
            if attack_type == TYPE_SENSITIVE_PROBE:
                continue
            for text in (raw_url, decoded_url):
                m = _match_first(patterns, text)
                if m:
                    return attack_type, m

    # 4. 请求体：仅高置信度特征（SQL 注入 / 命令注入）
    if body:
        m = _match_first(BODY_PATTERNS[TYPE_SQL_INJECTION], body)
        if m:
            return TYPE_SQL_INJECTION, m
        m = _match_first(BODY_PATTERNS[TYPE_COMMAND_INJECTION], body)
        if m:
            return TYPE_COMMAND_INJECTION, m

    return None, ''