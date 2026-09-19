"""DDoS 攻击检测 —— 单位时间窗口内统计每个 IP 的请求数，超阈值自动封禁。

设计要点（防误判）：
  1. 静态资源不计入：所有 /static/* 路径跳过计数
  2. 媒体资源不计入：音频/视频/直播流等大数据量路径跳过计数
     （如 /uploads/music/*, /uploads/live/*, /music/play/* 等）
  3. 公共文件不计入：/public-files/* 跳过计数
  4. 浏览器图标不计入：/favicon.ico 跳过计数
  5. 检测强度可配（低/中/高），对应不同阈值
  6. 屡教不改升级（24h 内多次触发转永久封禁）
"""

import time
from collections import deque

from core.firewall.service import (
    ban_ip,
    is_banned,
    is_whitelisted,
    SYSTEM_BANNER_ID,
)
from core.firewall.database import get_db, push_ban_context
from core.system.logger import log

# DDoS 检测强度预设：单位检测窗口（秒）内允许的最大请求数
DDOS_INTENSITY_PRESETS = {
    'low': 300,      # 宽松，只拦明显洪泛
    'medium': 150,   # 中等，平衡误判与拦截
    'high': 80,      # 严格，对突发敏感
}

# 固定检测窗口（秒）
DDOS_WINDOW_SECONDS = 10

# 不计入 DDoS 计数的路径前缀（完整匹配的 startswith 列表）
SKIP_PATHS = (
    '/static/',
    '/uploads/music/',
    '/uploads/live/',
    '/public-files/',
    '/favicon.ico',
    '/robots.txt',
    '/sitemap.xml',
    '/music/play/',
    '/music/download/',
)

# 不计入 DDoS 计数的扩展名（媒体 & 静态资源）
SKIP_EXTENSIONS = (
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma',
    '.mp4', '.webm', '.avi', '.mkv', '.mov', '.flv',
    '.m3u8', '.ts', '.m4s',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
    '.pdf', '.zip', '.rar',
)


def _should_skip(path):
    """判断路径是否应跳过 DDoS 计数（防误判）。"""
    if not path:
        return True
    if path.startswith(SKIP_PATHS):
        return True
    # 检查文件扩展名
    for ext in SKIP_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


class DDoSDetector:
    """DDoS 攻击检测器。

    线程安全：_counters 和 _offenses 由外部 _state_lock 保护。
    使用方式：由防火墙后台监控线程定时清理过期计数。
    """

    def __init__(self):
        self._counters = {}   # ip -> deque[timestamp, ...]
        self._offenses = {}   # ip -> [count, last_time]
        self._state_lock = __import__('threading').Lock()

    def record(self, ip, path, enabled, intensity):
        """记录一个请求计数。如果超过阈值，触发封禁。

        Args:
            ip: 客户端 IP
            path: 请求路径
            enabled: DDoS 防护是否开启
            intensity: 检测强度（low/medium/high）

        Returns:
            (banned: bool, message: str)
        """
        if not enabled:
            return False, ''
        if not ip:
            return False, ''
        if _should_skip(path):
            return False, ''

        threshold = DDOS_INTENSITY_PRESETS.get(
            intensity, DDOS_INTENSITY_PRESETS['medium'],
        )
        now = time.time()

        with self._state_lock:
            q = self._counters.get(ip)
            if q is None:
                q = deque()
                self._counters[ip] = q
            q.append(now)

            # 移除窗口外的旧记录
            while q and now - q[0] > DDOS_WINDOW_SECONDS:
                q.popleft()

            if len(q) < threshold:
                return False, ''

            # 超阈值 → 封禁，同时清空计数避免窗口内重复触发
            self._counters.pop(ip, None)

        # 阈值检查通过后执行封禁（持有锁可能导致死锁，释放锁后再执行）
        return self._ban_ddos(ip, threshold)

    def _ban_ddos(self, ip, threshold):
        """DDoS 封禁：检查白名单 / 是否已封禁 / 屡教不改升级。"""
        if is_whitelisted(ip):
            return False, '白名单 IP，跳过'
        banned, _ = is_banned(ip)
        if banned:
            return False, '已在封禁中'

        from config import get_config_value

        # 封禁时长配置
        ban_minutes = int(get_config_value('DDOS_GUARD_BAN_MINUTES', 30) or 30)
        permanent_after = int(get_config_value('DDOS_GUARD_PERMANENT_AFTER', 3) or 3)
        offense_hours = int(get_config_value('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24) or 24)

        # 屡教不改检测
        now = time.time()
        with self._state_lock:
            rec = self._offenses.get(ip)
            if rec and now - rec[1] <= offense_hours * 3600:
                rec[0] += 1
            else:
                rec = [1, now]
                self._offenses[ip] = rec
            offense_count = rec[0]

        permanent = offense_count >= permanent_after

        if permanent:
            reason = 'DDoS 攻击（屡次触发，永久封禁）'
            duration_minutes = None
        else:
            reason = (
                f'DDoS 攻击（{DDOS_WINDOW_SECONDS} 秒内请求超过 '
                f'{threshold} 次，封禁 {ban_minutes} 分钟）'
            )
            duration_minutes = ban_minutes if ban_minutes > 0 else None

        # 推送 DDoS 上下文（被 ban_ip 内的 record_ban_detail 自动拾取）
        push_ban_context(
            action_source='ddos',
            matched_text=f'threshold={threshold}, window={DDOS_WINDOW_SECONDS}s',
        )

        success, message = ban_ip(
            ip_address=ip,
            reason=reason,
            banned_by=SYSTEM_BANNER_ID,
            duration_minutes=duration_minutes,
        )

        if success:
            # 记录 DDoS 封禁日志
            try:
                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO firewall_ddos_log "
                        "(ip_address, action, threshold, count) "
                        "VALUES (?, ?, ?, ?)",
                        (ip, 'banned', threshold, offense_count),
                    )
            except Exception:
                pass
            log('Security', 'DDoS 防护：自动封禁',
                ip=ip, threshold=threshold, window=DDOS_WINDOW_SECONDS,
                permanent=permanent, offense_count=offense_count)

        return success, message

    def prune(self, config_getter):
        """清理过期的计数与违规记录。

        Args:
            config_getter: 配置读取函数，接收 (key, default) 返回 value
        """
        now = time.time()
        with self._state_lock:
            # 清理超过 2 倍窗口仍无活动的计数
            stale = [
                ip for ip, q in self._counters.items()
                if not q or now - q[-1] > DDOS_WINDOW_SECONDS * 2
            ]
            for ip in stale:
                self._counters.pop(ip, None)

            # 清理超过违规窗口的违规记录
            offense_hours = int(
                config_getter('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24) or 24
            )
            stale2 = [
                ip for ip, rec in self._offenses.items()
                if now - rec[1] > offense_hours * 3600
            ]
            for ip in stale2:
                self._offenses.pop(ip, None)

    @property
    def stats(self):
        """返回当前 DDoS 统计信息（监控用）。"""
        with self._state_lock:
            return {
                'active_ips': len(self._counters),
                'offense_ips': len(self._offenses),
                'total_counters': sum(len(q) for q in self._counters.values()),
            }