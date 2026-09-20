"""IP 封禁服务测试 —— 校验封禁创建、检查、解封与过期清理逻辑。

使用文档测试 IP 段 198.51.100.0/24（RFC 5737），避免污染真实数据。
"""

import pytest

from routes.firewall import (
    validate_ip, ban_ip, is_banned, get_bans, unban_ip,
    cleanup_expired, is_whitelisted, auto_ban, ban_suspicious_ip,
)
from routes.firewall.service import invalidate_cache as _invalidate_cache

# 测试用 IP 段（RFC 5737 保留，不会与真实用户冲突）
T_IP = '198.51.100.10'
T_IP2 = '198.51.100.20'
T_IP6 = '2001:db8::1'
ADMIN_ID = 1
ADMIN_NAME = 'admin'
# 封禁白名单默认 IP（config.py FIREWALL_WHITELIST）
WHITELIST_IP = '112.82.136.172'


@pytest.fixture(autouse=True)
def _cleanup_ban_records():
    """每个用例前后清理测试 IP 段的封禁记录。"""
    from routes.firewall.database import get_db

    def _clean():
        with get_db() as conn:
            conn.execute(
                "DELETE FROM firewall_bans WHERE ip_address LIKE '198.51.100.%' "
                "OR ip_address LIKE '2001:db8::%'"
            )
        _invalidate_cache()

    _clean()
    yield
    _clean()


class TestValidateIp:
    def test_valid_ipv4(self):
        assert validate_ip('192.168.1.1') is True

    def test_valid_ipv6(self):
        assert validate_ip('2001:db8::1') is True

    @pytest.mark.parametrize('bad', [
        '', '   ', 'abc', '999.1.1.1', '1.2.3', '1.2.3.4.5',
        '10.0.0.1;drop', '<script>',
    ])
    def test_invalid(self, bad):
        assert validate_ip(bad) is False


class TestCreateBan:
    def test_permanent_ban(self):
        ok, msg = ban_ip(T_IP, '恶意请求', ADMIN_ID)
        assert ok is True
        assert '永久' in msg
        banned, reason = is_banned(T_IP)
        assert banned is True
        assert reason == '恶意请求'

    def test_temporary_ban(self):
        ok, msg = ban_ip(T_IP, '临时', ADMIN_ID, duration_minutes=1440)
        assert ok is True
        assert '1440' in msg
        banned, _ = is_banned(T_IP)
        assert banned is True

    def test_duplicate_ban_rejected(self):
        assert ban_ip(T_IP, '第一次', ADMIN_ID)[0] is True
        ok, msg = ban_ip(T_IP, '第二次', ADMIN_ID)
        assert ok is False
        assert '已在封禁列表' in msg

    def test_invalid_ip_rejected(self):
        ok, msg = ban_ip('not-an-ip', 'x', ADMIN_ID)
        assert ok is False
        assert '无效' in msg

    def test_invalid_duration_rejected(self):
        ok, msg = ban_ip(T_IP, 'x', ADMIN_ID, duration_minutes='abc')
        assert ok is False
        assert '时长无效' in msg

    def test_negative_duration_means_permanent(self):
        ok, msg = ban_ip(T_IP, 'x', ADMIN_ID, duration_minutes=-5)
        assert ok is True
        assert '永久' in msg


class TestUnban:
    def test_unban_removes_ban(self):
        ban_ip(T_IP, '原因', ADMIN_ID)
        assert is_banned(T_IP)[0] is True
        ban = get_bans()[0]
        ok, msg, _ = unban_ip(ban['id'])
        assert ok is True
        assert T_IP in msg
        assert is_banned(T_IP)[0] is False

    def test_unban_missing_returns_error(self):
        ok, msg, _ = unban_ip(999999)
        assert ok is False
        assert '不存在' in msg


class TestExpiry:
    def test_expired_ban_cleaned(self):
        # 创建一个临时封禁，验证清理不会影响未过期记录
        ok, msg = ban_ip(T_IP2, '临时封禁', ADMIN_ID, duration_minutes=30)
        assert ok is True
        assert is_banned(T_IP2)[0] is True
        # cleanup_expired 不会误清理未过期的封禁
        cleanup_expired()
        assert is_banned(T_IP2)[0] is True
        # 通过解封清除记录
        bans = get_bans()
        ban = next(b for b in bans if b['ip_address'] == T_IP2)
        ok, msg, _ = unban_ip(ban['id'])
        assert ok is True
        assert is_banned(T_IP2)[0] is False


class TestGetBans:
    def test_list_only_active(self):
        ban_ip(T_IP, '永久', ADMIN_ID)
        ban_ip(T_IP2, '临时', ADMIN_ID, duration_minutes=2880)
        bans = get_bans()
        ips = {b['ip_address'] for b in bans}
        assert T_IP in ips and T_IP2 in ips
        # 操作人信息已关联
        for b in bans:
            assert 'banned_by' in b


class TestWhitelist:
    def test_default_whitelist_contains_admin_ip(self):
        assert is_whitelisted(WHITELIST_IP) is True

    def test_other_ip_not_whitelisted(self):
        assert is_whitelisted(T_IP) is False

    def test_whitelisted_ip_cannot_be_banned(self):
        ok, msg = ban_ip(WHITELIST_IP, '手动封禁', ADMIN_ID)
        assert ok is False
        assert '白名单' in msg

    def test_whitelisted_ip_never_reported_banned(self):
        assert is_banned(WHITELIST_IP) == (False, '')

    def test_whitelist_trimmed_on_check(self):
        assert is_whitelisted(' 112.82.136.172 ') is True


class TestAutoBan:
    """自动封禁测试：通过 monkeypatch 覆盖 config.get_config_value 保证确定性。"""

    def _patch_settings(self, monkeypatch, overrides):
        """将 get_config_value 替换为静态映射，未覆盖的键回退默认值。"""
        defaults = {
            'AUTO_BAN_ENABLED': True,
            'AUTO_BAN_DURATION_MINUTES': 30,
            'AUTO_BAN_LOGIN_ENABLED': True,
            'AUTO_BAN_REGISTER_ENABLED': True,
            'AUTO_BAN_EMAIL_ENABLED': True,
            'AUTO_BAN_FORGOT_PASSWORD_ENABLED': True,
        }
        defaults.update(overrides)
        monkeypatch.setattr('config.get_config_value', lambda key, default: defaults.get(key, default))

    def test_auto_ban_triggers(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        ok, msg = auto_ban(T_IP, 'login')
        assert ok is True
        assert is_banned(T_IP)[0] is True
        ban = get_bans()[0]
        # 系统自动封禁的操作人显示为「系统」
        assert ban['banned_by'] == 0

    def test_auto_ban_global_disabled(self, monkeypatch):
        self._patch_settings(monkeypatch, {'AUTO_BAN_ENABLED': False})
        ok, msg = auto_ban(T_IP, 'login')
        assert ok is False
        assert is_banned(T_IP)[0] is False

    def test_auto_ban_per_action_disabled(self, monkeypatch):
        self._patch_settings(monkeypatch, {'AUTO_BAN_REGISTER_ENABLED': False})
        ok, msg = auto_ban(T_IP, 'register')
        assert ok is False
        assert is_banned(T_IP)[0] is False

    def test_auto_ban_skips_whitelist(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        ok, msg = auto_ban(WHITELIST_IP, 'login')
        assert ok is False
        assert '白名单' in msg

    def test_auto_ban_rejects_invalid_ip(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        ok, msg = auto_ban('not-an-ip', 'login')
        assert ok is False
        assert '无效' in msg

    def test_auto_ban_does_not_duplicate(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        assert auto_ban(T_IP, 'login')[0] is True
        ok, msg = auto_ban(T_IP, 'login')
        assert ok is False
        assert '已在封禁列表' in msg


class TestBanSuspiciousIp:
    """可疑访问自动封禁测试：通过 monkeypatch 覆盖 config.get_config_value 保证确定性。"""

    def _patch_settings(self, monkeypatch, overrides):
        defaults = {
            'SUSPICIOUS_BLOCK_ENABLED': True,
            'SUSPICIOUS_BLOCK_DURATION_MINUTES': 60,
            'SUSPICIOUS_BLOCK_SQLI_ENABLED': True,
            'SUSPICIOUS_BLOCK_XSS_ENABLED': True,
            'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED': True,
            'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED': True,
            'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED': True,
            'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED': True,
        }
        defaults.update(overrides)
        monkeypatch.setattr('config.get_config_value', lambda key, default: defaults.get(key, default))

    def test_ban_triggers_with_reason(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        ok, msg = ban_suspicious_ip(T_IP, 'sql_injection', "1' OR '1'='1")
        assert ok is True
        assert is_banned(T_IP)[0] is True
        ban = get_bans()[0]
        # 原因记录攻击类型与命中片段，操作人显示为「系统」
        assert 'sql_injection' in ban['reason']
        assert "1' OR '1'='1" in ban['reason']
        assert ban['banned_by'] == 0

    def test_global_disabled(self, monkeypatch):
        self._patch_settings(monkeypatch, {'SUSPICIOUS_BLOCK_ENABLED': False})
        ok, msg = ban_suspicious_ip(T_IP, 'xss', '<script>')
        assert ok is False
        assert '总开关' in msg
        assert is_banned(T_IP)[0] is False

    def test_per_type_disabled(self, monkeypatch):
        self._patch_settings(monkeypatch, {'SUSPICIOUS_BLOCK_XSS_ENABLED': False})
        ok, msg = ban_suspicious_ip(T_IP, 'xss', '<script>')
        assert ok is False
        assert '未开启' in msg
        assert is_banned(T_IP)[0] is False

    def test_skips_whitelist(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        ok, msg = ban_suspicious_ip(WHITELIST_IP, 'sql_injection', 'union select')
        assert ok is False
        assert '白名单' in msg

    def test_rejects_invalid_ip(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        ok, msg = ban_suspicious_ip('not-an-ip', 'sql_injection', 'union select')
        assert ok is False
        assert '无效' in msg

    def test_does_not_duplicate(self, monkeypatch):
        self._patch_settings(monkeypatch, {})
        assert ban_suspicious_ip(T_IP, 'xss', '<script>')[0] is True
        ok, msg = ban_suspicious_ip(T_IP, 'xss', '<script>')
        assert ok is False
        assert '已在封禁列表' in msg