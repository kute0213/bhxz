"""IP 封禁业务服务：封禁、解封、封禁检查。

提供：
- validate_ip() — IP 地址格式校验
- create_ban() — 创建封禁（支持临时封禁）
- get_bans() — 查询有效封禁列表
- unban() — 解除封禁
- is_banned() — 检查 IP 是否被封禁（带内存缓存，30 秒刷新）
- cleanup_expired_bans() — 清理已过期的临时封禁

缓存说明：全站每个请求都会调用 is_banned()，为避免频繁查询数据库，
使用进程内缓存（30 秒 TTL）；创建/解除封禁时立即失效缓存。
"""

import ipaddress
import threading
import time
from datetime import datetime, timedelta

from core.db import get_db
from core.logger import log

# 封禁缓存 TTL（秒）
CACHE_TTL = 30

_ban_cache = {'ts': 0.0, 'banned': {}}  # {ip: reason}
_ban_cache_lock = threading.Lock()


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


def is_banned(ip_address):
    """检查 IP 是否被封禁。

    Returns:
        (banned: bool, reason: str)
    """
    if not ip_address:
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
    """查询所有有效封禁（含操作人用户名）。"""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT b.*, u.username AS banned_by_name
            FROM ip_bans b
            LEFT JOIN users u ON b.banned_by = u.id
            WHERE b.expires_at IS NULL OR b.expires_at > ?
            ORDER BY b.created_at DESC
            """,
            (_now(),),
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
