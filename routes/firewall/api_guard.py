"""API 防火墙 —— 接口调用频率限制（默认每 IP 每分钟 60 次）。

设计要点：
  - 计数完全由防火墙内存缓存维护（O(1)，零数据库开销），不写 DuckDB
  - 固定窗口计数：窗口长度默认 60 秒，窗口内超过阈值即「封禁 API」
  - 封禁期间该 IP 的所有 API 请求返回 429 JSON；窗口结束自动解除
  - 用户刷新页面（发起一次普通页面请求）会立即清空该 IP 的 API 计数与封禁，
    即「到达限制后封禁 API，但刷新后即可继续调用」
  - 阈值、窗口、总开关均可在管理后台 → 系统设置中热更新

使用方式（由 core/middleware.py 的请求钩子统一调用）：
    from routes.firewall.api_guard import guard_api_request
    resp = guard_api_request()   # 允许通过返回 None，被限制返回 Flask 响应
"""

import threading
import time

from core.system.logger import log

# ---------------------------------------------------------------------------
# 内存计数（防火墙内存缓存层）
# ---------------------------------------------------------------------------

_lock = threading.Lock()
# {ip: {'count': int, 'window_start': float, 'blocked_until': float}}
_counters = {}

# 上次全量清理时间（防止内存无限增长）
_last_prune = 0.0
_PRUNE_INTERVAL = 60.0


def _now():
    return time.monotonic()


def _get_limit():
    """读取当前 API 限流配置：返回 (enabled, limit, window_seconds)。"""
    from config import get_config_value
    enabled = bool(get_config_value('API_RATE_LIMIT_ENABLED', True))
    try:
        limit = int(get_config_value('API_RATE_LIMIT_PER_MINUTE', 60) or 60)
    except (ValueError, TypeError):
        limit = 60
    if limit <= 0:
        enabled = False
    try:
        window = int(get_config_value('API_RATE_LIMIT_WINDOW_SECONDS', 60) or 60)
    except (ValueError, TypeError):
        window = 60
    if window <= 0:
        window = 60
    return enabled, limit, window


def _prune_locked(now, window):
    """清理长时间无活动且已过窗口的计数（调用方需持有 _lock）。"""
    global _last_prune
    if now - _last_prune < _PRUNE_INTERVAL:
        return
    _last_prune = now
    stale = [
        ip for ip, rec in _counters.items()
        if now - rec.get('window_start', 0) > window * 2
        and now > rec.get('blocked_until', 0)
    ]
    for ip in stale:
        _counters.pop(ip, None)


def check_api_rate_limit(ip):
    """登记一次 API 调用并检查是否超限。

    Args:
        ip: 客户端 IP

    Returns:
        (allowed: bool, remaining: int, retry_after: int)
        - allowed=False 表示该 IP 已被限流（封禁 API）
        - retry_after 为建议的重试等待秒数
    """
    enabled, limit, window = _get_limit()
    if not enabled or not ip:
        return True, limit, 0

    now = _now()
    with _lock:
        _prune_locked(now, window)
        rec = _counters.get(ip)
        if rec is None:
            rec = {'count': 0, 'window_start': now, 'blocked_until': 0.0}
            _counters[ip] = rec

        # 窗口已结束 → 重置计数与封禁
        if now - rec['window_start'] >= window:
            rec['count'] = 0
            rec['window_start'] = now
            rec['blocked_until'] = 0.0

        # 仍处于封禁期
        if rec['blocked_until'] and now < rec['blocked_until']:
            retry_after = max(1, int(rec['blocked_until'] - now) + 1)
            return False, 0, retry_after

        rec['count'] += 1
        if rec['count'] > limit:
            # 超过阈值 → 封禁至本窗口结束
            rec['blocked_until'] = rec['window_start'] + window
            retry_after = max(1, int(rec['blocked_until'] - now) + 1)
            log('Security', 'API 调用超限，防火墙封禁 API',
                ip=ip, count=rec['count'], limit=limit, window=window)
            return False, 0, retry_after

        remaining = max(0, limit - rec['count'])
        return True, remaining, 0


def reset_api_limit(ip):
    """清空指定 IP 的 API 计数与封禁（页面刷新时调用）。

    用户刷新页面后即可继续调用 API。
    """
    if not ip:
        return
    with _lock:
        _counters.pop(ip, None)


def get_api_stats():
    """返回当前 API 限流统计（供管理面板展示）。"""
    now = _now()
    with _lock:
        active = len(_counters)
        blocked = sum(
            1 for rec in _counters.values()
            if rec.get('blocked_until', 0) and now < rec['blocked_until']
        )
    return {'tracked_ips': active, 'blocked_ips': blocked}


# ---------------------------------------------------------------------------
# Flask 集成：请求守卫
# ---------------------------------------------------------------------------

# 明确视为 API 的路径前缀
API_PATH_PREFIXES = ('/api/',)


def is_api_request(request):
    """判断当前请求是否为 API 请求（需要接入 API 防火墙）。

    判定规则（满足任一即可）：
      1. 路径以 /api/ 开头
      2. 携带 X-Requested-With: XMLHttpRequest（AJAX）
      3. Accept 明确要求 application/json（且非浏览器导航）
    """
    path = request.path or ''
    if path.startswith(API_PATH_PREFIXES):
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '') or ''
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    return False


def guard_api_request():
    """对当前 API 请求执行防火墙限流。

    允许通过返回 None；被限制返回 Flask JSON 响应（429）。
    非 API 请求不做任何处理。
    """
    from flask import request, jsonify

    from core.shared.ip import get_client_ip
    from routes.firewall.service import is_whitelisted

    if not is_api_request(request):
        return None

    ip = get_client_ip()
    # 白名单 IP 与本地回环不受 API 限流
    if not ip or is_whitelisted(ip):
        return None

    allowed, remaining, retry_after = check_api_rate_limit(ip)
    if allowed:
        return None

    resp = jsonify({
        'success': False,
        'message': f'API 调用过于频繁，请稍后重试（每 {_get_limit()[2]} 秒最多 '
                   f'{_get_limit()[1]} 次）。',
        'code': 'rate_limited',
        'retry_after': retry_after,
    })
    resp.status_code = 429
    resp.headers['Retry-After'] = str(retry_after)
    return resp
