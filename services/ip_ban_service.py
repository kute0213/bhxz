"""IP 封禁业务服务：封禁、解封、封禁检查、自动封禁。

提供：
- validate_ip() — IP 地址格式校验
- create_ban() — 创建封禁（支持临时封禁）
- get_bans() — 查询有效封禁列表
- unban() — 解除封禁
- is_banned() — 检查 IP 是否被封禁（带内存缓存，30 秒刷新）
- cleanup_expired_bans() — 清理已过期的临时封禁
- auto_ban() — 按配置自动封禁可疑操作来源 IP（白名单 IP 跳过）
- ban_suspicious_ip() — 拦截到可疑访问（SQL 注入/XSS 等攻击特征）时按配置自动封禁来源 IP
- is_whitelisted() — 判断 IP 是否在封禁白名单中

缓存说明：全站每个请求都会调用 is_banned()，为避免频繁查询数据库，
使用进程内缓存（30 秒 TTL）；创建/解除封禁时立即失效缓存。
"""

import ipaddress
import threading
import time
from datetime import datetime, timedelta

from core.db import get_db
from core.logger import log
from config import (
    IP_BAN_WHITELIST,
    AUTO_BAN_ENABLED,
    AUTO_BAN_DURATION_MINUTES,
)

# 封禁缓存 TTL（秒）
CACHE_TTL = 30

_ban_cache = {'ts': 0.0, 'banned': {}}  # {ip: reason}
_ban_cache_lock = threading.Lock()

# 自动封禁：操作类型 → 对应的设置注册表键（默认开启）
AUTO_BAN_ACTION_SETTINGS = {
    'login': 'AUTO_BAN_LOGIN_ENABLED',
    'register': 'AUTO_BAN_REGISTER_ENABLED',
    'email': 'AUTO_BAN_EMAIL_ENABLED',
    'forgot_password': 'AUTO_BAN_FORGOT_PASSWORD_ENABLED',
}

# 可疑访问拦截：攻击类型 → 对应的设置注册表键（默认开启）
SUSPICIOUS_ACTION_SETTINGS = {
    'sql_injection': 'SUSPICIOUS_BLOCK_SQLI_ENABLED',
    'xss': 'SUSPICIOUS_BLOCK_XSS_ENABLED',
    'path_traversal': 'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
    'command_injection': 'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
    'sensitive_probe': 'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
    'malicious_ua': 'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED',
}

# 系统自动封禁操作人的标记 ID（users 表中不存在该用户，显示为「系统」）
SYSTEM_BANNER_ID = 0


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def validate_ip(ip_address):
    """校验 IP 地址格式（支持 IPv4 / IPv6）。"""
    if not ip_address or not ip_address.strip():
        return False
    try:
        ipaddress.ip_address(ip_address.strip())
        return True
    except ValueError:
        return False


def _refresh_cache_locked():
    """刷新封禁缓存（同时清理已过期的临时封禁）。"""
    cleanup_expired_bans()
    now = _now()
    banned = {}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ip_address, reason FROM ip_bans "
            "WHERE expires_at IS NULL OR expires_at > ?",
            (now,),
        ).fetchall()
        for row in rows:
            banned[row['ip_address']] = row['reason'] or ''
    _ban_cache['banned'] = banned
    _ban_cache['ts'] = time.time()


def _invalidate_cache():
    """使封禁缓存失效（下次检查时重新加载）。"""
    with _ban_cache_lock:
        _ban_cache['ts'] = 0.0


def is_whitelisted(ip_address):
    """判断 IP 是否在封禁白名单中（白名单内的 IP 不会被封禁）。"""
    if not ip_address:
        return False
    return ip_address.strip() in IP_BAN_WHITELIST


def is_banned(ip_address):
    """检查 IP 是否被封禁。

    白名单内的 IP 恒返回未封禁（即使存在历史封禁记录也不生效）。

    Returns:
        (banned: bool, reason: str)
    """
    if not ip_address:
        return False, ''
    if is_whitelisted(ip_address):
        return False, ''
    with _ban_cache_lock:
        if time.time() - _ban_cache['ts'] > CACHE_TTL:
            try:
                _refresh_cache_locked()
            except Exception as exc:
                log('WARNING', 'IpBan', f'刷新封禁缓存失败: {exc}')
        return ip_address in _ban_cache['banned'], _ban_cache['banned'].get(ip_address, '')


def create_ban(ip_address, reason, banned_by, duration_days=None):
    """创建 IP 封禁。duration_days 为空表示永久封禁。

    Returns:
        (success, message)
    """
    ip = (ip_address or '').strip()
    if not validate_ip(ip):
        return False, '无效的 IP 地址'
    if is_whitelisted(ip):
        return False, '该 IP 在封禁白名单中，不允许封禁'

    expires_at = None
    if duration_days:
        try:
            days = float(duration_days)
            if days > 0:
                expires = datetime.now() + timedelta(days=days)
                expires_at = expires.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return False, '封禁时长无效'

    try:
        with get_db() as conn:
            now = _now()
            existing = conn.execute(
                "SELECT id FROM ip_bans WHERE ip_address = ? "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (ip, now),
            ).fetchone()
            if existing:
                return False, '该 IP 已在封禁列表中'

            cursor = conn.execute(
                "INSERT INTO ip_bans (ip_address, reason, banned_by, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (ip, reason, banned_by, now, expires_at),
            )
            ban_id = cursor.lastrowid
            conn.commit()
    except Exception as exc:
        log('ERROR', 'IpBan', f'创建封禁失败: {exc}', ip=ip)
        return False, '创建封禁失败'

    _invalidate_cache()
    log('INFO', 'IpBan', 'IP 封禁创建',
        ip=ip, banned_by=banned_by, expires_at=expires_at or '永久')
    return True, f'已封禁 {ip}（{"临时" if expires_at else "永久"}）'


def get_bans():
    """查询所有有效封禁（含操作人用户名；系统自动封禁显示为「系统」）。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT b.*,
                   CASE WHEN b.banned_by = ? THEN '系统' ELSE u.username END AS banned_by_name
            FROM ip_bans b
            LEFT JOIN users u ON b.banned_by = u.id
            WHERE b.expires_at IS NULL OR b.expires_at > ?
            ORDER BY b.created_at DESC
            """,
            (SYSTEM_BANNER_ID, _now()),
        ).fetchall()
        return [dict(r) for r in rows]


def get_ban(ban_id):
    """查询单条封禁记录。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ip_bans WHERE id = ?", (ban_id,)).fetchone()
        return dict(row) if row else None


def unban(ban_id, admin_id, admin_username, ip_address):
    """解除封禁。

    Returns:
        (success, message)
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ip_bans WHERE id = ?", (ban_id,)).fetchone()
        if not row:
            return False, '封禁记录不存在'
        conn.execute("DELETE FROM ip_bans WHERE id = ?", (ban_id,))
        conn.commit()

    _invalidate_cache()
    log('INFO', 'IpBan', 'IP 封禁解除',
        ip=row['ip_address'], ban_id=ban_id, admin_id=admin_id,
        admin_username=admin_username, ip_address=ip_address)
    return True, f'已解除 {row["ip_address"]} 的封禁'


def cleanup_expired_bans():
    """删除已过期的临时封禁，返回删除数量。"""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM ip_bans WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (_now(),),
            )
            deleted = cursor.rowcount
            conn.commit()
        if deleted:
            log('INFO', 'IpBan', '自动清理过期封禁', count=deleted)
        return deleted
    except Exception as exc:
        log('WARNING', 'IpBan', f'清理过期封禁失败: {exc}')
        return 0


def auto_ban(ip_address, action, reason=''):
    """按配置自动封禁可疑操作来源 IP。

    同时满足以下全部条件才会执行封禁：
    1. 全局总开关 AUTO_BAN_ENABLED 开启（管理后台 → 系统设置可调）
    2. 该操作对应的子开关开启（登录/注册/邮箱验证码/找回密码分别控制）
    3. IP 不在封禁白名单中
    4. IP 当前未被封禁

    封禁时长取 AUTO_BAN_DURATION_MINUTES（分钟，0 = 永久），到期自动解除。

    Args:
        ip_address: 来源 IP
        action: 操作类型，取值 login / register / email / forgot_password
        reason: 自定义封禁原因（为空时自动生成）

    Returns:
        (banned: bool, message: str)
    """
    from config import get_config_value

    if not get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED):
        return False, '自动封禁总开关未开启'

    action_key = AUTO_BAN_ACTION_SETTINGS.get(action)
    if action_key and not get_config_value(action_key, True):
        return False, f'「{action}」操作的自动封禁未开启'

    ip = (ip_address or '').strip()
    if is_whitelisted(ip):
        log('INFO', 'IpBan', '自动封禁跳过白名单 IP', ip=ip, action=action)
        return False, '该 IP 在封禁白名单中，跳过自动封禁'

    if not validate_ip(ip):
        return False, '无效的 IP 地址'

    if is_banned(ip)[0]:
        return False, '该 IP 已在封禁列表中'

    # 封禁时长：分钟 → 天（create_ban 以天为单位）
    try:
        duration_minutes = int(get_config_value(
            'AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES))
    except (ValueError, TypeError):
        duration_minutes = AUTO_BAN_DURATION_MINUTES
    duration_days = duration_minutes / 1440.0 if duration_minutes > 0 else None

    success, message = create_ban(
        ip_address=ip,
        reason=reason or f'自动封禁：{action} 操作异常',
        banned_by=SYSTEM_BANNER_ID,
        duration_days=duration_days,
    )
    if success:
        log('Security', '自动封禁生效', ip=ip, action=action,
            duration_minutes=duration_minutes or '永久')
    return success, message


def ban_suspicious_ip(ip_address, attack_type, matched=''):
    """拦截到可疑访问（SQL 注入/XSS 等攻击特征）时按配置自动封禁来源 IP。

    与 auto_ban() 的区别：自动封禁面向「限流触发」，本函数面向「攻击特征命中」，
    使用独立的配置键（SUSPICIOUS_BLOCK_*），总开关、各攻击类型子开关与封禁时长
    均可在管理后台 → 系统设置中热更新。

    Args:
        ip_address: 来源 IP
        attack_type: 攻击类型（sql_injection / xss / path_traversal /
                     command_injection / sensitive_probe / malicious_ua）
        matched: 命中的特征片段（写入封禁原因，便于后台追溯）

    Returns:
        (banned: bool, message: str)
    """
    from config import (
        get_config_value,
        SUSPICIOUS_BLOCK_ENABLED,
        SUSPICIOUS_BLOCK_DURATION_MINUTES,
    )

    if not get_config_value('SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED):
        return False, '可疑访问拦截总开关未开启'

    action_key = SUSPICIOUS_ACTION_SETTINGS.get(attack_type)
    if action_key and not get_config_value(action_key, True):
        return False, f'「{attack_type}」类型拦截未开启'

    ip = (ip_address or '').strip()
    if is_whitelisted(ip):
        log('INFO', 'IpBan', '可疑访问拦截跳过白名单 IP', ip=ip, attack=attack_type)
        return False, '该 IP 在封禁白名单中，跳过自动封禁'

    if not validate_ip(ip):
        return False, '无效的 IP 地址'

    if is_banned(ip)[0]:
        return False, '该 IP 已在封禁列表中'

    # 封禁时长：分钟 → 天（create_ban 以天为单位）
    try:
        duration_minutes = int(get_config_value(
            'SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES))
    except (ValueError, TypeError):
        duration_minutes = SUSPICIOUS_BLOCK_DURATION_MINUTES
    duration_days = duration_minutes / 1440.0 if duration_minutes > 0 else None

    reason = f'可疑访问拦截：{attack_type} 攻击'
    if matched:
        reason += f'（命中：{matched}）'

    success, message = create_ban(
        ip_address=ip,
        reason=reason,
        banned_by=SYSTEM_BANNER_ID,
        duration_days=duration_days,
    )
    if success:
        log('Security', '可疑访问自动封禁生效', ip=ip, attack=attack_type,
            duration_minutes=duration_minutes or '永久')
    return success, message
