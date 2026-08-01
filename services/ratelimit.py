"""简单内存频率限制器（每 IP 滑动窗口，线程安全）。"""

import time
import threading
from collections import defaultdict


class RateLimiter:
    """基于滑动窗口的 IP 频率限制器。

    用法:
        limiter = RateLimiter(max_requests=10, window=60)
        if not limiter.check(request.remote_addr):
            return "请求过于频繁", 429
    """

    def __init__(self, max_requests: int = 5, window: int = 60):
        self._max_requests = max_requests
        self._window = window
        self._records: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, ip: str) -> bool:
        """检查 IP 是否超过限制。返回 True 表示允许通过，False 表示被限流。"""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            records = self._records[ip]
            # 清理过期记录
            while records and records[0] < cutoff:
                records.pop(0)
            if len(records) >= self._max_requests:
                return False
            records.append(now)
        return True

    def cleanup_expired(self):
        """清理所有过期的 IP 记录，防止内存泄漏。"""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            expired_ips = []
            for ip, records in self._records.items():
                while records and records[0] < cutoff:
                    records.pop(0)
                if not records:
                    expired_ips.append(ip)
            for ip in expired_ips:
                del self._records[ip]


# 预置限流器实例
register_limiter = RateLimiter(max_requests=5, window=60)      # 注册：每 IP 每分钟 5 次
login_limiter = RateLimiter(max_requests=10, window=60)          # 登录：每 IP 每分钟 10 次
email_limiter = RateLimiter(max_requests=3, window=60)           # 邮箱验证码：每 IP 每分钟 3 次