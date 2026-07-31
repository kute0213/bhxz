"""邮箱验证码服务 —— 生成、存储、验证（带过期时间，内存存储）。"""

import random
import re
import string
import time
import threading
from datetime import datetime

from .service import email_service
from .templates import verification_code as build_code_html


def normalize_email(email: str) -> str:
    """规范化邮箱：清除不可见字符 + 全角转半角 + 去首尾空格 + 转小写。"""
    # 清除零宽空格、BOM 等不可见字符
    email = re.sub(r'[\u200b\u200c\u200d\ufeff\u2060\u180e]', '', email)
    # 全角字符 -> 半角（如 ＠ -> @，． -> .，０-９ -> 0-9）
    result = []
    for ch in email:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(' ')
        else:
            result.append(ch)
    return ''.join(result).strip().lower()


class EmailCodeService:
    """邮箱验证码管理器（单例，内存存储，自动过期清理）。

    安全特性：
    - 内存存储验证码，不持久化
    - 60 秒发送冷却时间，防止恶意刷邮件
    - 5 分钟过期，超时自动失效
    - verify() 验证成功后立即删除，防止重放
    - 后台线程定期清理过期项，避免内存泄漏
    """

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
        # 启动后台清理线程，每 5 分钟清理一次过期验证码，避免内存泄漏
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, name='email-code-cleanup', daemon=True
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self):
        """后台线程：定期清理过期验证码，避免内存泄漏。"""
        while True:
            time.sleep(300)  # 5 分钟
            try:
                self.cleanup_expired()
            except Exception as e:
                print(f'[EmailCode] 清理过期验证码失败: {e}', flush=True)

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

        # 异步发送邮件（HTML 使用统一模板，移动端自适应）
        subject = f'[{purpose}] 验证码: {code}'
        body = (
            f'您好！\n\n'
            f'您的{purpose}验证码为: {code}\n\n'
            f'验证码有效期为 {self._expire_seconds // 60} 分钟，请尽快使用。\n'
            f'如果这不是您本人的操作，请忽略此邮件。\n'
        )
        html = build_code_html(code, purpose, self._expire_seconds // 60)
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
