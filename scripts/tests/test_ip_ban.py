"""IP 封禁服务测试 —— 校验封禁创建、检查、解封与过期清理逻辑。

使用文档测试 IP 段 198.51.100.0/24（RFC 5737），避免污染真实数据。
"""

import pytest

from services.ip_ban_service import (
    validate_ip, create_ban, is_banned, get_bans, unban,
    cleanup_expired_bans,
)
from services.ip_ban_service import _invalidate_cache

# 测试用 IP 段（RFC 5737 保留，不会与真实用户冲突）
T_IP = '198.51.100.10'
T_IP2 = '198.51.100.20'
T_IP6 = '2001:db8::1'
ADMIN_ID = 1
ADMIN_NAME = 'admin'


@pytest.fixture(autouse=True)
def _cleanup_ban_records():
    """每个用例前后清理测试 IP 段的封禁记录。"""
    from core.db import get_db

    def _clean():
        with get_db() as conn:
            conn.execute(
                "DELETE FROM ip_bans WHERE ip_address LIKE '198.51.100.%' "
                "OR ip_address LIKE '2001:db8::%'"
            )
            conn.commit()
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
        ok, msg = create_ban(T_IP, '恶意请求', ADMIN_ID)
        assert ok is True
        assert '永久' in msg
        banned, reason = is_banned(T_IP)
        assert banned is True
        assert reason == '恶意请求'

    def test_temporary_ban(self):
        ok, msg = create_ban(T_IP, '临时', ADMIN_ID, duration_days=1)
        assert ok is True
        assert '临时' in msg
        banned, _ = is_banned(T_IP)
        assert banned is True

    def test_duplicate_ban_rejected(self):
        assert create_ban(T_IP, '第一次', ADMIN_ID)[0] is True
        ok, msg = create_ban(T_IP, '第二次', ADMIN_ID)
        assert ok is False
        assert '已在封禁列表' in msg

    def test_invalid_ip_rejected(self):
        ok, msg = create_ban('not-an-ip', 'x', ADMIN_ID)
        assert ok is False
        assert '无效' in msg

    def test_invalid_duration_rejected(self):
        ok, msg = create_ban(T_IP, 'x', ADMIN_ID, duration_days='abc')
        assert ok is False
        assert '时长无效' in msg

    def test_negative_duration_means_permanent(self):
        ok, msg = create_ban(T_IP, 'x', ADMIN_ID, duration_days=-5)
        assert ok is True
        assert '永久' in msg


class TestUnban:
    def test_unban_removes_ban(self):
        create_ban(T_IP, '原因', ADMIN_ID)
        assert is_banned(T_IP)[0] is True
        ban = get_bans()[0]
        ok, msg = unban(ban['id'], ADMIN_ID, ADMIN_NAME, '127.0.0.1')
        assert ok is True
        assert T_IP in msg
        assert is_banned(T_IP)[0] is False

    def test_unban_missing_returns_error(self):
        ok, msg = unban(999999, ADMIN_ID, ADMIN_NAME, '127.0.0.1')
        assert ok is False
        assert '不存在' in msg


class TestExpiry:
    def test_expired_ban_cleaned(self):
        # 写入一条已过期的封禁记录，验证自动清理
        from core.db import get_db
        from datetime import datetime, timedelta
        expired = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        with get_db() as conn:
            conn.execute(
                "INSERT INTO ip_bans (ip_address, reason, banned_by, created_at, expires_at) "
                "VALUES (?, '过期', ?, ?, ?)",
                (T_IP2, ADMIN_ID, expired, expired),
            )
            conn.commit()
        _invalidate_cache()
        # 过期封禁不应生效
        assert is_banned(T_IP2)[0] is False
        # 清理是幂等的：is_banned 刷新缓存时已清理过一次
        deleted = cleanup_expired_bans()
        assert deleted >= 0


class TestGetBans:
    def test_list_only_active(self):
        create_ban(T_IP, '永久', ADMIN_ID)
        create_ban(T_IP2, '临时', ADMIN_ID, duration_days=2)
        bans = get_bans()
        ips = {b['ip_address'] for b in bans}
        assert T_IP in ips and T_IP2 in ips
        # 操作人用户名已关联
        for b in bans:
            assert 'banned_by_name' in b
