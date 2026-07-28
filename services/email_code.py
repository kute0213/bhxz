"""邮箱验证码服务 —— 生成、存储、验证（带过期时间，内存存储）。"""

import random
import string
import time
import threading
from datetime import datetime

from services.email import email_service


class EmailCodeService:
    """邮箱验证码管理器（单例，内存存储，自动过期清理）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # {email: {'code': '123456', 'expire': timestamp}}
        self._codes: dict = {}
        self._lock = threading.Lock()
        # 过期时间（秒）
        self._expire_seconds = 300  # 5 分钟
        # 发送间隔限制（秒），防止频繁发送
        self._resend_cooldown = 60

    def _generate_code(self) -> str:
        """生成 6 位数字验证码。"""
        return ''.join(random.choices(string.digits, k=6))

    def can_send(self, email: str) -> tuple:
        """检查是否可以发送验证码（冷却时间限制）。"""
        with self._lock:
            entry = self._codes.get(email)
            if entry:
                elapsed = time.time() - entry.get('sent_at', 0)
                if elapsed < self._resend_cooldown:
                    return False, f'请 {int(self._resend_cooldown - elapsed)} 秒后再试'
            return True, ''

    def send_code(self, email: str, purpose: str = '注册') -> tuple:
        """发送验证码到指定邮箱。

        Returns: (success: bool, message: str)
        """
        # 检查邮件功能是否启用
        if not email_service.is_enabled():
            return False, '邮件功能未启用'

        # 冷却时间检查
        ok, msg = self.can_send(email)
        if not ok:
            return False, msg

        # 生成验证码
        code = self._generate_code()

        # 存储验证码
        now = time.time()
        with self._lock:
            self._codes[email] = {
                'code': code,
                'expire': now + self._expire_seconds,
                'sent_at': now,
            }

        # 异步发送邮件
        subject = f'[{purpose}] 验证码: {code}'
        body = (
            f'您好！\n\n'
            f'您的{purpose}验证码为: {code}\n\n'
            f'验证码有效期为 {self._expire_seconds // 60} 分钟，请尽快使用。\n'
            f'如果这不是您本人的操作，请忽略此邮件。\n'
        )
        html = (
            f'<div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">'
            f'<h2 style="color: #f4d03f;">{purpose}验证码</h2>'
            f'<p>您好！</p>'
            f'<p>您的验证码为:</p>'
            f'<div style="font-size: 32px; font-weight: bold; '
            f'color: #f4d03f; letter-spacing: 8px; '
            f'background: #1a2a1a; padding: 16px; border-radius: 8px; text-align: center; margin: 16px 0;">'
            f'{code}</div>'
            f'<p style="color: #888; font-size: 13px;">'
            f'验证码有效期为 {self._expire_seconds // 60} 分钟，请尽快使用。<br>'
            f'如果这不是您本人的操作，请忽略此邮件。'
            f'</p></div>'
        )
        email_service.send(email, subject, body, html)

        return True, '验证码已发送，请查收邮箱'

    def verify(self, email: str, code: str) -> bool:
        """验证验证码是否正确且未过期。"""
        with self._lock:
            entry = self._codes.get(email)
            if not entry:
                return False
            if time.time() > entry['expire']:
                del self._codes[email]
                return False
            if entry['code'] != code:
                return False
            # 验证成功后删除
            del self._codes[email]
            return True

    def cleanup_expired(self):
        """清理过期的验证码。"""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._codes.items() if now > v['expire']]
            for k in expired:
                del self._codes[k]


# 全局单例
email_code_service = EmailCodeService()
