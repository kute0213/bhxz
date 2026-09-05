"""简单内存频率限制器（每 IP 滑动窗口，线程安全），支持 IP+UA 组合 key 与 atexit 持久化。"""

import time
import threading
import atexit
import json
import os
from collections import defaultdict

from services.ip import get_client_ip

_STATE_PATH = '/tmp/ratelimit_state.json'


class RateLimiter:
    """基于滑动窗口的 IP+UA 频率限制器。

    用法:
        limiter = RateLimiter(max_requests=10, window=60)
        if not limiter.check(get_client_ip(), request.headers.get('User-Agent', '')):
            return "请求过于频繁", 429
    """

    def __init__(self, max_requests: int = 5, window: int = 60, name: str = ''):
        self._max_requests = max_requests
        self._window = window
        self._name = name or f'limiter_{id(self)}'
        self._records: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _make_key(self, ip: str, user_agent: str = '') -> str:
        """将 IP 和 User-Agent 组合为内部 key。"""
        ua = user_agent.strip() if user_agent else ''
        if ua:
            return f"{ip}|{ua}"
        return ip

    def check(self, ip: str, user_agent: str = '') -> bool:
        """检查 IP+UA 组合是否超过限制。返回 True 表示允许通过，False 表示被限流。"""
        key = self._make_key(ip, user_agent)
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            records = self._records[key]
            # 清理过期记录
            while records and records[0] < cutoff:
                records.pop(0)
            if len(records) >= self._max_requests:
                return False
            records.append(now)
        return True

    def cleanup_expired(self):
        """清理所有过期的记录，防止内存泄漏。"""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            expired_keys = []
            for key, records in self._records.items():
                while records and records[0] < cutoff:
                    records.pop(0)
                if not records:
                    expired_keys.append(key)
            for key in expired_keys:
                del self._records[key]

    def save_state(self):
        """将当前状态持久化到文件。"""
        try:
            state = {
                'max_requests': self._max_requests,
                'window': self._window,
                'name': self._name,
                'records': {k: list(v) for k, v in self._records.items()},
            }
            with self._lock:
                data = json.dumps(state, ensure_ascii=False)
            with open(_STATE_PATH, 'w', encoding='utf-8') as f:
                f.write(data)
        except Exception:
            pass

    @classmethod
    def load_state(cls, instance: 'RateLimiter'):
        """从文件恢复状态到实例。"""
        try:
            if not os.path.isfile(_STATE_PATH):
                return
            with open(_STATE_PATH, 'r', encoding='utf-8') as f:
                data = f.read()
            if not data:
                return
            state = json.loads(data)
            with instance._lock:
                instance._records = defaultdict(list, {
                    k: list(v) for k, v in state.get('records', {}).items()
                })
        except Exception:
            pass


# 预置限流器实例
register_limiter = RateLimiter(max_requests=5, window=60, name='register')      # 注册：每 IP 每分钟 5 次
login_limiter = RateLimiter(max_requests=10, window=60, name='login')            # 登录：每 IP 每分钟 10 次
email_limiter = RateLimiter(max_requests=3, window=60, name='email')             # 邮箱验证码：每 IP 每分钟 3 次
forgot_password_limiter = RateLimiter(max_requests=3, window=60, name='forgot_password') # 找回密码：每 IP 每分钟 3 次

# 启动时恢复持久化状态
for _limiter in (register_limiter, login_limiter, email_limiter, forgot_password_limiter):
    RateLimiter.load_state(_limiter)

# 注册 atexit 持久化回调
def _save_all():
    for _limiter in (register_limiter, login_limiter, email_limiter, forgot_password_limiter):
        _limiter.save_state()

atexit.register(_save_all)