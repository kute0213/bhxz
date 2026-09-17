"""防火墙统一业务服务 —— 封禁 IP、白名单管理、警告系统、自动封禁。

为所有路由模块提供统一、安全的调用接口：
    from core.firewall import ban_ip, unban_ip, is_banned, ...

设计要点：
  - 所有写操作通过 DuckDB 持久化，同时失效内存缓存
  - 白名单 IP 在任何封禁操作中都会被跳过
  - 所有函数公开、线程安全、异常安全（内部 catch 一切异常）
"""

import ipaddress
import threading
import time
from datetime import datetime, timedelta
from core.firewall.database import get_db
from core.system.logger import log

# 封禁缓存 TTL（秒）
CACHE_TTL = 30
_ban_cache = {'ts': 0.0, 'banned': {}}
_ban_cache_lock = threading.Lock()

# 白名单缓存 TTL（秒）
WHITELIST_CACHE_TTL = 10
_whitelist_cache = {'ts': 0.0, 'data': []}
_whitelist_cache_lock = threading.Lock()

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
# 内部缓存
# ---------------------------------------------------------------------------

def _invalidate_cache():
    """使封禁缓存失效（下次检查时重新加载）。"""
    with _ban_cache_lock:
        _ban_cache['ts'] = 0.0


def _invalidate_whitelist_cache():
    """使白名单缓存失效。"""
    with _whitelist_cache_lock:
        _whitelist_cache['ts'] = 0.0


def _refresh_ban_cache():
    """刷新封禁缓存。"""
    cleanup_expired()
    banned = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT ip_address, reason FROM firewall_bans "
                "WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP"
            ).fetchall()
            for row in rows:
                banned[row[0]] = row[1] or ''
    except Exception as exc:
        log('WARNING', 'Firewall', f'刷新封禁缓存失败: {exc}')
    # 注意：_refresh_ban_cache 总是在 _ban_cache_lock 已持有的上下文中调用
    #（见 is_banned 与 get_banned_ips），因此这里不重复获取锁以避免死锁
    _ban_cache['banned'] = banned
    _ban_cache['ts'] = time.time()


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
    """获取防火墙白名单列表（合并 config.py FIREWALL_WHITELIST + DuckDB 运行时白名单）。

    config.py 中定义的白名单作为启动时基线（如默认 112.82.136.172），
    DuckDB firewall_whitelist 表存储通过管理后台等运行时添加的白名单，
    两者共同生效。
    """
    from config import FIREWALL_WHITELIST as CONFIG_WHITELIST

    with _whitelist_cache_lock:
        if time.time() - _whitelist_cache['ts'] > WHITELIST_CACHE_TTL:
            try:
                with get_db() as conn:
                    rows = conn.execute(
                        "SELECT ip_address FROM firewall_whitelist"
                    ).fetchall()
                duckdb_whitelist = [row[0] for row in rows]
                merged = list(CONFIG_WHITELIST) + duckdb_whitelist
                # 去重（保留顺序）
                seen = set()
                whitelist = []
                for ip in merged:
                    if ip not in seen:
                        seen.add(ip)
                        whitelist.append(ip)
                _whitelist_cache['data'] = whitelist
                _whitelist_cache['ts'] = time.time()
            except Exception as exc:
                log('WARNING', 'Firewall', f'刷新白名单缓存失败: {exc}')
        return list(_whitelist_cache['data'])


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
    return ip in get_whitelist()


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
                (ip,)
            )
    except Exception as exc:
        return False, f'添加白名单失败: {exc}'
    _invalidate_whitelist_cache()
    log('INFO', 'Firewall', '白名单添加', ip=ip)
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
                (ip,)
            )
    except Exception as exc:
        return False, f'移除白名单失败: {exc}'
    _invalidate_whitelist_cache()
    log('INFO', 'Firewall', '白名单移除', ip=ip)
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
                expires_at = (datetime.now() + timedelta(minutes=mins)).strftime('%Y-%m-%d %H:%M:%S')
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

            conn.execute(
                "INSERT INTO firewall_bans (ip_address, reason, banned_by, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (ip, reason, banned_by, now, expires_at),
            )
    except Exception as exc:
        log('ERROR', 'Firewall', f'创建封禁失败: {exc}', ip=ip)
        return False, '创建封禁失败'

    _invalidate_cache()
    duration_text = '永久' if expires_at is None else f'{duration_minutes} 分钟'
    log('INFO', 'Firewall', 'IP 封禁创建',
        ip=ip, banned_by=banned_by, duration=duration_text)
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
    _invalidate_cache()
    log('INFO', 'Firewall', 'IP 封禁解除', ban_id=ban_id, ip=ip_address)
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
    _invalidate_cache()
    log('INFO', 'Firewall', 'IP 封禁解除（按 IP）', ip=ip)
    return True, f'已解除 {ip} 的封禁'


def is_banned(ip_address):
    """检查 IP 是否被封禁。

    白名单内的 IP 恒返回未封禁（即使存在历史封禁记录也不生效）。
    带 30 秒进程内缓存，适合每请求调用。

    Returns:
        (banned: bool, reason: str)
    """
    if not ip_address:
        return False, ''
    if is_whitelisted(ip_address):
        return False, ''
    with _ban_cache_lock:
        if time.time() - _ban_cache['ts'] > CACHE_TTL:
            _refresh_ban_cache()
        if ip_address in _ban_cache['banned']:
            return True, _ban_cache['banned'].get(ip_address, '')
        # CIDR 段匹配（如 192.168.0.0/24）
        for banned_ip, reason in _ban_cache['banned'].items():
            if '/' in banned_ip:
                try:
                    if ipaddress.ip_address(ip_address) in ipaddress.ip_network(banned_ip, strict=False):
                        return True, reason
                except ValueError:
                    pass
        return False, ''


def get_bans():
    """查询所有有效封禁。"""
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
            result = []
            for row in rows:
                result.append({
                    'id': row[0],
                    'ip_address': row[1],
                    'reason': row[2],
                    'banned_by': row[3],
                    'created_at': row[4],
                    'expires_at': row[5],
                })
            return result
    except Exception as exc:
        log('WARNING', 'Firewall', f'查询封禁列表失败: {exc}')
        return []


def get_ban(ban_id):
    """查询单条封禁记录。"""
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
                    'id': row[0],
                    'ip_address': row[1],
                    'reason': row[2],
                    'banned_by': row[3],
                    'created_at': row[4],
                    'expires_at': row[5],
                }
        return None
    except Exception:
        return None


def get_banned_ips():
    """获取全部有效封禁 IP（内存缓存，供防火墙快速同步黑名单镜像）。

    Returns:
        dict: {ip_address: reason}
    """
    with _ban_cache_lock:
        if time.time() - _ban_cache['ts'] > CACHE_TTL:
            _refresh_ban_cache()
        return dict(_ban_cache['banned'])


def cleanup_expired():
    """清理已过期的临时封禁。"""
    try:
        with get_db() as conn:
            result = conn.execute(
                "DELETE FROM firewall_bans "
                "WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP"
            )
            deleted = result.fetchone()
            # DuckDB 的 DELETE 返回的是结果集，不是 rowcount
            # 我们需要用另一种方式获取删除数量
    except Exception as exc:
        log('WARNING', 'Firewall', f'清理过期封禁失败: {exc}')


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
        log('INFO', 'Firewall', '自动封禁跳过白名单 IP', ip=ip, action=action)
        return False, '该 IP 在防火墙白名单中，跳过自动封禁'

    if not validate_ip(ip):
        return False, '无效的 IP 地址'

    banned, _ = is_banned(ip)
    if banned:
        return False, '该 IP 已在封禁列表中'

    try:
        duration_minutes = int(get_config_value('AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES))
    except (ValueError, TypeError):
        duration_minutes = AUTO_BAN_DURATION_MINUTES

    success, message = ban_ip(
        ip_address=ip,
        reason=reason or f'自动封禁：{action} 操作异常',
        banned_by=SYSTEM_BANNER_ID,
        duration_minutes=duration_minutes if duration_minutes > 0 else None,
    )
    if success:
        log('Security', '自动封禁生效', ip=ip, action=action,
            duration_minutes=duration_minutes or '永久')
    return success, message


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
    from config import get_config_value, SUSPICIOUS_BLOCK_ENABLED, SUSPICIOUS_BLOCK_DURATION_MINUTES

    if not get_config_value('SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED):
        return False, '可疑访问拦截总开关未开启'

    action_key = SUSPICIOUS_ACTION_SETTINGS.get(attack_type)
    if action_key and not get_config_value(action_key, True):
        return False, f'「{attack_type}」类型拦截未开启'

    ip = (ip_address or '').strip()
    if is_whitelisted(ip):
        log('INFO', 'Firewall', '可疑访问拦截跳过白名单 IP', ip=ip, attack=attack_type)
        return False, '该 IP 在防火墙白名单中，跳过自动封禁'

    if not validate_ip(ip):
        return False, '无效的 IP 地址'

    banned, _ = is_banned(ip)
    if banned:
        return False, '该 IP 已在封禁列表中'

    try:
        duration_minutes = int(get_config_value(
            'SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES))
    except (ValueError, TypeError):
        duration_minutes = SUSPICIOUS_BLOCK_DURATION_MINUTES

    reason = f'可疑访问拦截：{attack_type} 攻击'
    if matched:
        reason += f'（命中：{matched}）'

    success, message = ban_ip(
        ip_address=ip,
        reason=reason,
        banned_by=SYSTEM_BANNER_ID,
        duration_minutes=duration_minutes if duration_minutes > 0 else None,
    )
    if success:
        log('Security', '可疑访问自动封禁生效', ip=ip, attack=attack_type,
            duration_minutes=duration_minutes or '永久')
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
                "  AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours'".format(hours),
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
                {'ip_address': r[0], 'warning': r[1], 'created_at': r[2], 'count': r[3]}
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