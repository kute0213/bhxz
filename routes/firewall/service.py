"""防火墙统一业务服务 —— 封禁 IP/账号、白名单管理、警告系统、自动封禁、刷屏记录。

为所有路由模块提供统一、安全的调用接口：
    from routes.firewall import ban_ip, unban_ip, is_banned, ...

设计要点：
  - 所有写操作通过 DuckDB 持久化，同时失效内存缓存
  - 白名单 IP 在任何封禁操作中都会被跳过
  - 内存缓存由 monitor.py 每秒同步，service 层只负责失效通知
  - 所有函数公开、线程安全、异常安全（内部 catch 一切异常）
"""

import ipaddress
import threading
import time
from datetime import datetime, timedelta

from routes.firewall.database import get_db
from routes.firewall.database import (
    invalidate_cache,
    invalidate_ip_cache,
    invalidate_account_cache,
    invalidate_whitelist_cache,
    is_ip_banned_cache,
    is_account_banned_cache,
    is_whitelisted_cache,
    push_expiry,
    record_ban_detail,     # 自动记录封禁详情
    push_ban_context,      # 从 WSGI/DDOS 层传递上下文
    get_ban_detail,        # 查询封禁详情
    # 账号白名单
    get_account_whitelist_db,
    is_account_whitelisted_db,
    whitelist_account_db,
    unwhitelist_account_db,
)
from core.system.logger import log

# 系统自动封禁操作人的标记 ID（users 表中不存在该用户，显示为「系统」）
SYSTEM_BANNER_ID = 0

# 内置安全 IP —— 永远不受防火墙影响（不能封禁、始终视为白名单）
BUILTIN_SAFE_IPS = frozenset({'127.0.0.1', '::1', 'localhost'})

# 自动封禁：操作类型 → 对应的设置注册表键（默认开启）
AUTO_BAN_ACTION_SETTINGS = {
    'login': 'AUTO_BAN_LOGIN_ENABLED',
    'register': 'AUTO_BAN_REGISTER_ENABLED',
    'email': 'AUTO_BAN_EMAIL_ENABLED',
    'forgot_password': 'AUTO_BAN_FORGOT_PASSWORD_ENABLED',
}

# 自动封禁屡教不改记录：{ ip: [count, first_timestamp] }
_auto_ban_offenses = {}
_auto_ban_offenses_lock = threading.Lock()

# 可疑访问拦截：攻击类型 → 对应的设置注册表键（默认开启）
SUSPICIOUS_ACTION_SETTINGS = {
    'sql_injection': 'SUSPICIOUS_BLOCK_SQLI_ENABLED',
    'xss': 'SUSPICIOUS_BLOCK_XSS_ENABLED',
    'path_traversal': 'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
    'command_injection': 'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
    'sensitive_probe': 'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
    'malicious_ua': 'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED',
}


# ---------------------------------------------------------------------------
# IP 格式校验
# ---------------------------------------------------------------------------


def validate_ip(ip_address):
    """校验 IP 地址格式（支持 IPv4 / IPv6）。"""
    if not ip_address or not ip_address.strip():
        return False
    try:
        ipaddress.ip_address(ip_address.strip())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# 白名单管理
# ---------------------------------------------------------------------------


def get_whitelist():
    """获取防火墙白名单列表（从内存缓存读取，由监控线程每秒同步）。

    Returns:
        list[str]: IP 地址列表
    """
    from routes.firewall import database as _db
    cached = getattr(_db, '_cache', {}).get('whitelist', set())
    return list(cached)


def is_whitelisted(ip_address):
    """判断 IP 是否在防火墙白名单或内置安全 IP 列表中。

    内置安全 IP（127.0.0.1、::1）永远不受防火墙影响，始终视为白名单。
    白名单内的 IP 不会被执行任何封禁操作。
    """
    if not ip_address:
        return False
    ip = ip_address.strip()
    if ip in BUILTIN_SAFE_IPS:
        return True
    return is_whitelisted_cache(ip)


def whitelist_add(ip_address):
    """添加 IP 到防火墙白名单。

    Returns:
        (success: bool, message: str)
    """
    ip = (ip_address or '').strip()
    if not validate_ip(ip):
        return False, '无效的 IP 地址'
    if is_whitelisted(ip):
        return False, '该 IP 已在白名单中'
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO firewall_whitelist (ip_address) VALUES (?)",
                (ip,),
            )
    except Exception as exc:
        return False, f'添加白名单失败: {exc}'
    invalidate_whitelist_cache()
    log('DEBUG', 'Firewall', '白名单添加', ip=ip)
    return True, f'已将 {ip} 加入白名单'


def whitelist_remove(ip_address):
    """从防火墙白名单移除 IP。

    Returns:
        (success: bool, message: str)
    """
    ip = (ip_address or '').strip()
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM firewall_whitelist WHERE ip_address = ?",
                (ip,),
            )
    except Exception as exc:
        return False, f'移除白名单失败: {exc}'
    invalidate_whitelist_cache()
    log('DEBUG', 'Firewall', '白名单移除', ip=ip)
    return True, f'已将 {ip} 移出白名单'


# ---------------------------------------------------------------------------
# 封禁管理
# ---------------------------------------------------------------------------


def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def ban_ip(ip_address, reason, banned_by=SYSTEM_BANNER_ID, duration_minutes=None):
    """创建 IP 封禁。

    Args:
        ip_address: 要封禁的 IP 地址
        reason: 封禁原因
        banned_by: 操作人 ID（0 = 系统）
        duration_minutes: 封禁时长（分钟），None 表示永久封禁

    Returns:
        (success: bool, message: str)
    """
    ip = (ip_address or '').strip()
    if not validate_ip(ip):
        return False, '无效的 IP 地址'
    if ip in BUILTIN_SAFE_IPS:
        return False, '不能封禁本地回环地址'
    if is_whitelisted(ip):
        return False, '该 IP 在防火墙白名单中，不允许封禁'

    expires_at = None
    if duration_minutes is not None:
        try:
            mins = float(duration_minutes)
            if mins > 0:
                expires_at = (datetime.now() + timedelta(minutes=mins)).strftime(
                    '%Y-%m-%d %H:%M:%S'
                )
        except (ValueError, TypeError):
            return False, '封禁时长无效'

    try:
        with get_db() as conn:
            now = _now_str()
            existing = conn.execute(
                "SELECT id FROM firewall_bans WHERE ip_address = ? "
                "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
                (ip,),
            ).fetchone()
            if existing:
                return False, '该 IP 已在封禁列表中'

            result = conn.execute(
                "INSERT INTO firewall_bans (ip_address, reason, banned_by, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?) RETURNING id",
                (ip, reason, banned_by, now, expires_at),
            )
            new_id = result.fetchone()[0]
            # 注册过期时间
            push_expiry(expires_at, 'ip', new_id)
    except Exception as exc:
        log('ERROR', 'Firewall', f'创建封禁失败: {exc}', ip=ip)
        return False, '创建封禁失败'

    invalidate_ip_cache()
    duration_text = '永久' if expires_at is None else f'{duration_minutes} 分钟'
    log(
        'DEBUG', 'Firewall', 'IP 封禁创建',
        ip=ip, banned_by=banned_by, duration=duration_text,
    )

    # 自动记录封禁详情（收集自请求上下文 + 线程本地，无额外参数）
    record_ban_detail(
        ban_id=new_id, ban_type='ip',
        ip_address=ip, reason=reason, banned_by=banned_by,
        created_at=now, expires_at=expires_at,
    )

    return True, f'已封禁 {ip}（{duration_text}）'


def unban_ip(ban_id):
    """按记录 ID 解除封禁。

    Returns:
        (success: bool, message: str, ip_address: str)
    """
    ip_address = ''
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT ip_address FROM firewall_bans WHERE id = ?",
                (ban_id,),
            ).fetchone()
            if not row:
                return False, '封禁记录不存在', ''
            ip_address = row[0]
            conn.execute("DELETE FROM firewall_bans WHERE id = ?", (ban_id,))
    except Exception as exc:
        return False, f'解除封禁失败: {exc}', ''
    invalidate_ip_cache()
    log('DEBUG', 'Firewall', 'IP 封禁解除', ban_id=ban_id, ip=ip_address)
    return True, f'已解除 {ip_address} 的封禁', ip_address


def unban_by_ip(ip_address):
    """按 IP 地址解除封禁。

    Returns:
        (success: bool, message: str)
    """
    ip = (ip_address or '').strip()
    if not ip:
        return False, 'IP 地址不能为空'
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM firewall_bans WHERE ip_address = ?",
                (ip,),
            )
    except Exception as exc:
        return False, f'解除封禁失败: {exc}'
    invalidate_ip_cache()
    log('DEBUG', 'Firewall', 'IP 封禁解除（按 IP）', ip=ip)
    return True, f'已解除 {ip} 的封禁'


def is_banned(ip_address):
    """检查 IP 是否被封禁（使用 database.py 内存缓存，O(1) 查询）。

    白名单内的 IP 恒返回未封禁（即使存在历史封禁记录也不生效）。

    Returns:
        (banned: bool, reason: str)
    """
    if not ip_address:
        return False, ''
    ip = ip_address.strip()
    if ip in BUILTIN_SAFE_IPS:
        return False, ''
    if is_whitelisted_cache(ip):
        return False, ''
    return is_ip_banned_cache(ip)


def get_bans():
    """查询所有有效 IP 封禁。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, ip_address, reason, banned_by, "
                "       strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at, "
                "       CASE WHEN expires_at IS NULL THEN NULL "
                "            ELSE strftime('%Y-%m-%d %H:%M:%S', expires_at) "
                "       END AS expires_at "
                "FROM firewall_bans "
                "WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP "
                "ORDER BY created_at DESC"
            ).fetchall()
            return [
                {
                    'id': r[0], 'ip_address': r[1], 'reason': r[2],
                    'banned_by': r[3], 'created_at': r[4], 'expires_at': r[5],
                }
                for r in rows
            ]
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询封禁列表失败: {exc}')
        return []


def get_ban(ban_id):
    """查询单条 IP 封禁记录。"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id, ip_address, reason, banned_by, "
                "       strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at, "
                "       CASE WHEN expires_at IS NULL THEN NULL "
                "            ELSE strftime('%Y-%m-%d %H:%M:%S', expires_at) "
                "       END AS expires_at "
                "FROM firewall_bans WHERE id = ?",
                (ban_id,),
            ).fetchone()
            if row:
                return {
                    'id': row[0], 'ip_address': row[1], 'reason': row[2],
                    'banned_by': row[3], 'created_at': row[4], 'expires_at': row[5],
                }
        return None
    except Exception:
        return None


def get_banned_ips():
    """获取全部有效封禁 IP（从内存缓存读取）。

    Returns:
        dict: {ip_address: reason}
    """
    from routes.firewall import database as _db
    cached = getattr(_db, '_cache', {}).get('banned_ips', {})
    return dict(cached)


def cleanup_expired():
    """清理已过期的临时 IP 封禁（由监控线程定期调用，此处保留供手动调用）。"""
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM firewall_bans "
                "WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP"
            )
    except Exception as exc:
        log('WARNING', 'Firewall', f'清理过期 IP 封禁失败: {exc}')


# ---------------------------------------------------------------------------
# 账号封禁管理
# ---------------------------------------------------------------------------


def ban_account(user_id, reason, banned_by=SYSTEM_BANNER_ID, duration_minutes=None):
    """创建账号封禁。

    Args:
        user_id: 用户 ID
        reason: 封禁原因
        banned_by: 操作人 ID（0 = 系统）
        duration_minutes: 封禁时长（分钟），None 表示永久封禁

    Returns:
        (success: bool, message: str)
    """
    if not user_id or user_id < 0:
        return False, '无效的用户 ID'

    expires_at = None
    if duration_minutes is not None:
        try:
            mins = float(duration_minutes)
            if mins > 0:
                expires_at = (datetime.now() + timedelta(minutes=mins)).strftime(
                    '%Y-%m-%d %H:%M:%S'
                )
        except (ValueError, TypeError):
            return False, '封禁时长无效'

    try:
        with get_db() as conn:
            now = _now_str()
            existing = conn.execute(
                "SELECT id FROM firewall_account_bans WHERE user_id = ? "
                "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
                (user_id,),
            ).fetchone()
            if existing:
                return False, '该账号已在封禁列表中'

            result = conn.execute(
                "INSERT INTO firewall_account_bans "
                "(user_id, reason, banned_by, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?) RETURNING id",
                (user_id, reason, banned_by, now, expires_at),
            )
            new_id = result.fetchone()[0]
            # 注册过期时间
            push_expiry(expires_at, 'account', new_id)
    except Exception as exc:
        log('ERROR', 'Firewall', f'创建账号封禁失败: {exc}', user_id=user_id)
        return False, '创建账号封禁失败'

    invalidate_account_cache()
    duration_text = '永久' if expires_at is None else f'{duration_minutes} 分钟'
    log(
        'INFO', 'Firewall', '账号封禁创建',
        user_id=user_id, banned_by=banned_by, duration=duration_text,
    )

    # 自动记录封禁详情
    record_ban_detail(
        ban_id=new_id, ban_type='account',
        ip_address='', reason=reason, banned_by=banned_by,
        created_at=now, expires_at=expires_at,
        user_id=user_id,
    )

    return True, f'已封禁用户 {user_id}（{duration_text}）'


def unban_account(ban_id):
    """按记录 ID 解除账号封禁。

    Returns:
        (success: bool, message: str, user_id: int)
    """
    user_id = 0
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT user_id FROM firewall_account_bans WHERE id = ?",
                (ban_id,),
            ).fetchone()
            if not row:
                return False, '封禁记录不存在', 0
            user_id = row[0]
            conn.execute(
                "DELETE FROM firewall_account_bans WHERE id = ?",
                (ban_id,),
            )
    except Exception as exc:
        return False, f'解除账号封禁失败: {exc}', 0
    invalidate_account_cache()
    log('DEBUG', 'Firewall', '账号封禁解除', ban_id=ban_id, user_id=user_id)
    return True, f'已解除用户 {user_id} 的封禁', user_id


def unban_account_by_user(user_id):
    """按用户 ID 解除账号封禁。

    Returns:
        (success: bool, message: str)
    """
    if not user_id:
        return False, '用户 ID 不能为空'
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM firewall_account_bans WHERE user_id = ?",
                (user_id,),
            )
    except Exception as exc:
        return False, f'解除账号封禁失败: {exc}'
    invalidate_account_cache()
    log('DEBUG', 'Firewall', '账号封禁解除（按用户）', user_id=user_id)
    return True, f'已解除用户 {user_id} 的封禁'


def is_account_banned(user_id):
    """检查账号是否被封禁（使用 database.py 内存缓存）。

    Returns:
        (banned: bool, reason: str)
    """
    if not user_id or user_id < 0:
        return False, ''
    return is_account_banned_cache(user_id)


def get_account_bans():
    """查询所有有效账号封禁。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, user_id, reason, banned_by, "
                "       strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at, "
                "       CASE WHEN expires_at IS NULL THEN NULL "
                "            ELSE strftime('%Y-%m-%d %H:%M:%S', expires_at) "
                "       END AS expires_at "
                "FROM firewall_account_bans "
                "WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP "
                "ORDER BY created_at DESC"
            ).fetchall()
            return [
                {
                    'id': r[0], 'user_id': r[1], 'reason': r[2],
                    'banned_by': r[3], 'created_at': r[4], 'expires_at': r[5],
                }
                for r in rows
            ]
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询账号封禁列表失败: {exc}')
        return []


def get_account_ban(ban_id):
    """查询单条账号封禁记录。"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id, user_id, reason, banned_by, "
                "       strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at, "
                "       CASE WHEN expires_at IS NULL THEN NULL "
                "            ELSE strftime('%Y-%m-%d %H:%M:%S', expires_at) "
                "       END AS expires_at "
                "FROM firewall_account_bans WHERE id = ?",
                (ban_id,),
            ).fetchone()
            if row:
                return {
                    'id': row[0], 'user_id': row[1], 'reason': row[2],
                    'banned_by': row[3], 'created_at': row[4], 'expires_at': row[5],
                }
        return None
    except Exception:
        return None


def get_combined_bans(offset=0, limit=10):
    """获取合并后的封禁列表（IP + 账号），按时间倒序，分页。

    将 IP 封禁与账号封禁统一为相同结构，按 created_at DESC 排序。
    账号封禁自动解析用户名。

    Args:
        offset: 跳过条数
        limit: 每页条数

    Returns:
        (list[dict], total): (当前页记录, 总记录数)
    """
    try:
        ip_bans = get_bans()
        account_bans_raw = get_account_bans()

        # 统一化为标准格式
        combined = []

        for b in ip_bans:
            combined.append({
                'id': b['id'],
                'ban_type': 'ip',
                'identifier': b['ip_address'],
                'identifier_label': b['ip_address'],
                'user_id': None,
                'username': None,
                'reason': b.get('reason', ''),
                'banned_by': b.get('banned_by', 0),
                'created_at': b.get('created_at', ''),
                'expires_at': b.get('expires_at'),
            })

        # 解析账号禁用户名
        from core.db import get_db as get_sqlite
        for b in account_bans_raw:
            uid = b['user_id']
            username = None
            try:
                conn = get_sqlite()
                row = conn.execute(
                    "SELECT username FROM users WHERE id = ?", (uid,)
                ).fetchone()
                username = row[0] if row else None
                conn.close()
            except Exception:
                pass
            combined.append({
                'id': b['id'],
                'ban_type': 'account',
                'identifier': str(uid),
                'identifier_label': (username or f'用户{uid}') + f' #{uid}',
                'user_id': uid,
                'username': username,
                'reason': b.get('reason', ''),
                'banned_by': b.get('banned_by', 0),
                'created_at': b.get('created_at', ''),
                'expires_at': b.get('expires_at'),
            })

        # 按时间倒序
        combined.sort(key=lambda x: x['created_at'] or '', reverse=True)

        total = len(combined)
        page = combined[offset:offset + limit]
        return page, total
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询合并封禁列表失败: {exc}')
        return [], 0


# ---------------------------------------------------------------------------
# 刷屏记录
# ---------------------------------------------------------------------------


def record_spam(user_id, content_type, content_preview='', action='flag'):
    """记录一次刷屏行为到日志表。

    Args:
        user_id: 用户 ID
        content_type: 内容类型（discussion_topic, discussion_reply, guide, music 等）
        content_preview: 内容预览（可选）
        action: 采取的动作（flag / ban）
    """
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO firewall_spam_log "
                "(user_id, content_type, content_preview, action, created_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, content_type, content_preview, action),
            )
    except Exception as exc:
        log('WARNING', 'Firewall', f'记录刷屏日志失败: {exc}', user_id=user_id)


def get_spam_log(hours=24):
    """获取指定小时内的刷屏日志列表（含用户名，通过 LEFT JOIN 关联）。

    Args:
        hours: 时间窗口（小时）

    Returns:
        list[dict]: 刷屏日志记录列表
    """
    try:
        with get_db() as conn:
            # DuckDB 不支持跨数据库 JOIN，这里尝试直接关联
            # 如果 main.users 在同一 DuckDB 中则有效，否则 username 回退为 '[已删除]'
            try:
                rows = conn.execute(
                    "SELECT s.id, s.user_id, "
                    "       COALESCE(u.username, '[已删除]') AS username, "
                    "       s.content_type, s.content_preview, s.action, "
                    "       strftime('%Y-%m-%d %H:%M:%S', s.created_at) AS created_at "
                    "FROM firewall_spam_log s "
                    "LEFT JOIN main.users u ON s.user_id = u.id "
                    "WHERE s.created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours' "
                    "ORDER BY s.created_at DESC".format(hours),
                ).fetchall()
                return [
                    {
                        'id': r[0], 'user_id': r[1], 'username': r[2],
                        'content_type': r[3], 'content_preview': r[4],
                        'action': r[5], 'created_at': r[6],
                    }
                    for r in rows
                ]
            except Exception:
                # 如果跨数据库 JOIN 失败，降级为查询不包含 username
                rows = conn.execute(
                    "SELECT s.id, s.user_id, "
                    "       s.content_type, s.content_preview, s.action, "
                    "       strftime('%Y-%m-%d %H:%M:%S', s.created_at) AS created_at "
                    "FROM firewall_spam_log s "
                    "WHERE s.created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours' "
                    "ORDER BY s.created_at DESC".format(hours),
                ).fetchall()
                return [
                    {
                        'id': r[0], 'user_id': r[1],
                        'username': '[已删除]',
                        'content_type': r[2], 'content_preview': r[3],
                        'action': r[4], 'created_at': r[5],
                    }
                    for r in rows
                ]
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询刷屏日志失败: {exc}')
        return []


def get_user_spam_count(user_id, hours=1):
    """获取用户在指定小时内的刷屏记录数。

    Args:
        user_id: 用户 ID
        hours: 时间窗口（小时）

    Returns:
        int: 刷屏记录数
    """
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM firewall_spam_log "
                "WHERE user_id = ? "
                "  AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours'".format(
                    hours
                ),
                (user_id,),
            ).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def clear_spam_log(user_id=None):
    """清除刷屏日志记录。

    Args:
        user_id: 如果提供，只清除该用户的记录；否则清除全部
    """
    try:
        with get_db() as conn:
            if user_id:
                conn.execute(
                    "DELETE FROM firewall_spam_log WHERE user_id = ?",
                    (user_id,),
                )
            else:
                conn.execute("DELETE FROM firewall_spam_log")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 自动封禁（可疑操作限流）
# ---------------------------------------------------------------------------


def auto_ban(ip_address, action, reason=''):
    """按配置自动封禁可疑操作来源 IP（登录/注册/邮箱/找回密码异常）。

    同时满足以下全部条件才会执行封禁：
    1. 全局总开关 AUTO_BAN_ENABLED 开启
    2. 该操作对应的子开关开启
    3. IP 不在防火墙白名单中
    4. IP 当前未被封禁

    封禁时长取 AUTO_BAN_DURATION_MINUTES（分钟，0 = 永久）。

    Args:
        ip_address: 来源 IP
        action: 操作类型，取值 login / register / email / forgot_password
        reason: 自定义封禁原因（为空时自动生成）

    Returns:
        (banned: bool, message: str)
    """
    from config import get_config_value, AUTO_BAN_ENABLED, AUTO_BAN_DURATION_MINUTES

    if not get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED):
        return False, '自动封禁总开关未开启'

    action_key = AUTO_BAN_ACTION_SETTINGS.get(action)
    if action_key and not get_config_value(action_key, True):
        return False, f'「{action}」操作的自动封禁未开启'

    ip = (ip_address or '').strip()
    if is_whitelisted(ip):
        log('DEBUG', 'Firewall', '自动封禁跳过白名单 IP', ip=ip, action=action)
        return False, '该 IP 在防火墙白名单中，跳过自动封禁'

    if not validate_ip(ip):
        return False, '无效的 IP 地址'

    banned, _ = is_banned(ip)
    if banned:
        return False, '该 IP 已在封禁列表中'

    try:
        duration_minutes = int(
            get_config_value('AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES)
        )
    except (ValueError, TypeError):
        duration_minutes = AUTO_BAN_DURATION_MINUTES

    # ---- 屡教不改检测 ----
    permanent_after = int(get_config_value('AUTO_BAN_PERMANENT_AFTER', 0) or 0)
    offense_hours = int(get_config_value('AUTO_BAN_OFFENSE_WINDOW_HOURS', 24) or 24)

    if permanent_after > 0:
        now = time.time()
        with _auto_ban_offenses_lock:
            rec = _auto_ban_offenses.get(ip)
            if rec and now - rec[1] <= offense_hours * 3600:
                rec[0] += 1
            else:
                rec = [1, now]
                _auto_ban_offenses[ip] = rec
            offense_count = rec[0]

        if offense_count >= permanent_after:
            # 达到阈值 → 永久封禁，清空记录
            with _auto_ban_offenses_lock:
                _auto_ban_offenses.pop(ip, None)
            duration_minutes = 0  # 将触发下面的 0 → None 转换
            reason = f'自动封禁：{action} 操作异常（屡次触发，永久封禁）'

    # 推送操作上下文（被 ban_ip 内的 record_ban_detail 自动拾取）
    push_ban_context(
        action_source='auto_ban',
        matched_text=f'action={action}',
    )

    success, message = ban_ip(
        ip_address=ip,
        reason=reason or f'自动封禁：{action} 操作异常',
        banned_by=SYSTEM_BANNER_ID,
        duration_minutes=duration_minutes if duration_minutes > 0 else None,
    )
    if success:
        log(
            'Security', '自动封禁生效', ip=ip, action=action,
            duration_minutes=duration_minutes or '永久',
        )
    return success, message


def prune_auto_ban_offenses():
    """清理过期的自动封禁违规记录（超过窗口时间则清除）。"""
    from config import get_config_value
    offense_hours = int(get_config_value('AUTO_BAN_OFFENSE_WINDOW_HOURS', 24) or 24)
    now = time.time()
    cutoff = now - offense_hours * 3600
    with _auto_ban_offenses_lock:
        expired = [ip for ip, rec in _auto_ban_offenses.items() if rec[1] < cutoff]
        for ip in expired:
            del _auto_ban_offenses[ip]


# ---------------------------------------------------------------------------
# 可疑访问拦截（攻击特征命中）
# ---------------------------------------------------------------------------


def ban_suspicious_ip(ip_address, attack_type, matched=''):
    """拦截到可疑访问（SQL 注入/XSS 等攻击特征）时按配置自动封禁来源 IP。

    使用独立的配置键（SUSPICIOUS_BLOCK_*），总开关、各攻击类型子开关与封禁时长
    均可在管理后台热更新。

    Args:
        ip_address: 来源 IP
        attack_type: 攻击类型
        matched: 命中的特征片段

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
        log('DEBUG', 'Firewall', '可疑访问拦截跳过白名单 IP', ip=ip, attack=attack_type)
        return False, '该 IP 在防火墙白名单中，跳过自动封禁'

    if not validate_ip(ip):
        return False, '无效的 IP 地址'

    banned, _ = is_banned(ip)
    if banned:
        return False, '该 IP 已在封禁列表中'

    try:
        duration_minutes = int(
            get_config_value(
                'SUSPICIOUS_BLOCK_DURATION_MINUTES',
                SUSPICIOUS_BLOCK_DURATION_MINUTES,
            )
        )
    except (ValueError, TypeError):
        duration_minutes = SUSPICIOUS_BLOCK_DURATION_MINUTES

    reason = f'可疑访问拦截：{attack_type} 攻击'
    if matched:
        reason += f'（命中：{matched}）'

    # 推送攻击上下文（被 ban_ip 内的 record_ban_detail 自动拾取）
    push_ban_context(
        attack_type=attack_type,
        matched_text=matched,
        action_source='suspicious',
    )

    success, message = ban_ip(
        ip_address=ip,
        reason=reason,
        banned_by=SYSTEM_BANNER_ID,
        duration_minutes=duration_minutes if duration_minutes > 0 else None,
    )
    if success:
        log(
            'Security', '可疑访问自动封禁生效', ip=ip, attack=attack_type,
            duration_minutes=duration_minutes or '永久',
        )
    return success, message


# ---------------------------------------------------------------------------
# IP 警告系统（供其他路由调用，记录 IP 的违规行为）
# ---------------------------------------------------------------------------


def add_warning(ip_address, warning_text):
    """给 IP 添加一条警告记录。

    警告不影响请求处理，仅用于累积违规次数供管理员追溯。
    警告过多可在管理面板中查看。

    Args:
        ip_address: IP 地址
        warning_text: 警告内容描述

    Returns:
        int: 该 IP 在 24 小时内的累计警告次数
    """
    ip = (ip_address or '').strip()
    if not ip:
        return 0
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO firewall_warnings (ip_address, warning, created_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (ip, warning_text),
            )
        return get_warning_count(ip, hours=24)
    except Exception as exc:
        log('WARNING', 'Firewall', f'添加警告记录失败: {exc}', ip=ip)
        return 0


def get_warnings(ip_address, hours=24):
    """获取 IP 在指定小时内的警告列表。

    Args:
        ip_address: IP 地址
        hours: 时间窗口（小时），默认 24 小时

    Returns:
        list[dict]: 警告记录列表（含 id, warning, created_at）
    """
    ip = (ip_address or '').strip()
    if not ip:
        return []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, warning, "
                "       strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at "
                "FROM firewall_warnings "
                "WHERE ip_address = ? "
                "  AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours' "
                "ORDER BY created_at DESC".format(hours),
                (ip,),
            ).fetchall()
            return [
                {'id': r[0], 'warning': r[1], 'created_at': r[2]}
                for r in rows
            ]
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询警告记录失败: {exc}', ip=ip)
        return []


def get_warning_count(ip_address, hours=24):
    """获取 IP 在指定小时内的累计警告次数。

    Args:
        ip_address: IP 地址
        hours: 时间窗口（小时）

    Returns:
        int: 警告次数
    """
    ip = (ip_address or '').strip()
    if not ip:
        return 0
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM firewall_warnings "
                "WHERE ip_address = ? "
                "  AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours'".format(
                    hours
                ),
                (ip,),
            ).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def get_all_warnings(hours=24):
    """获取所有 IP 在指定小时内的警告汇总。

    Returns:
        list[dict]: 警告记录列表（含 ip_address, warning, created_at, count）
    """
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT ip_address, warning, "
                "       strftime('%%Y-%%m-%%d %%H:%%M:%%S', MAX(created_at)) AS created_at, "
                "       COUNT(*) AS cnt "
                "FROM firewall_warnings "
                "WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours' "
                "GROUP BY ip_address, warning "
                "ORDER BY created_at DESC".format(hours),
            ).fetchall()
            return [
                {
                    'ip_address': r[0], 'warning': r[1],
                    'created_at': r[2], 'count': r[3],
                }
                for r in rows
            ]
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询全部警告记录失败: {exc}')
        return []


def clear_warnings(ip_address):
    """清除 IP 的所有警告记录。

    Args:
        ip_address: IP 地址
    """
    ip = (ip_address or '').strip()
    if not ip:
        return
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM firewall_warnings WHERE ip_address = ?",
                (ip,),
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 账号白名单管理
# ---------------------------------------------------------------------------


def get_account_whitelist():
    """获取所有账号白名单。"""
    return get_account_whitelist_db()


def is_account_whitelisted(user_id):
    """检查账号是否在白名单中。"""
    return is_account_whitelisted_db(user_id)


def whitelist_account(user_id, note=''):
    """添加账号到白名单。"""
    if not user_id or user_id <= 0:
        return False, '无效的用户 ID'
    if whitelist_account_db(user_id, note):
        log('DEBUG', 'Firewall', '账号白名单添加', user_id=user_id)
        return True, f'已将用户 {user_id} 加入白名单'
    return False, '添加账号白名单失败（可能已存在）'


def unwhitelist_account(user_id):
    """从白名单移除账号。"""
    if not user_id or user_id <= 0:
        return False, '无效的用户 ID'
    unwhitelist_account_db(user_id)
    log('DEBUG', 'Firewall', '账号白名单移除', user_id=user_id)
    return True, f'已将用户 {user_id} 移出白名单'


# ---------------------------------------------------------------------------
# 封禁详情查询
# ---------------------------------------------------------------------------


def get_ban_detail_service(ban_id):
    """查询单条封禁的详细信息（含操作人用户名解析）。"""
    detail = get_ban_detail(ban_id)
    if detail is None:
        return None
    # 解析封禁操作人用户名
    if detail.get('banned_by'):
        try:
            from core.db import get_db as get_sqlite_db
            conn = get_sqlite_db()
            row = conn.execute(
                "SELECT username FROM users WHERE id = ?",
                (detail['banned_by'],),
            ).fetchone()
            detail['banned_by_name'] = row[0] if row else f"用户{detail['banned_by']}"
            conn.close()
        except Exception:
            detail['banned_by_name'] = f"用户{detail['banned_by']}"
    else:
        detail['banned_by_name'] = '系统'
    return detail


# ---------------------------------------------------------------------------
# 手工封禁推送上下文
# ---------------------------------------------------------------------------


def ban_ip_manual(ip_address, reason, banned_by, duration_minutes=None):
    """管理员手动封禁 IP（自动设置 action_source=manual）。"""
    push_ban_context(action_source='manual')
    return ban_ip(
        ip_address=ip_address, reason=reason,
        banned_by=banned_by, duration_minutes=duration_minutes,
    )


def ban_account_manual(user_id, reason, banned_by, duration_minutes=None):
    """管理员手动封禁账号（自动设置 action_source=manual）。"""
    push_ban_context(action_source='manual')
    return ban_account(
        user_id=user_id, reason=reason,
        banned_by=banned_by, duration_minutes=duration_minutes,
    )