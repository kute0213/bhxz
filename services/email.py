"""SMTP 邮件发送服务（基于 yagmail，后台线程异步发送，不阻塞主请求）。"""

import threading
import queue
from datetime import datetime

from config import get_config_value


class EmailService:
    """异步邮件发送器（单例）。

    将邮件放入队列由后台线程发送，不阻塞 HTTP 请求。
    所有 SMTP 参数通过 get_config_value 动态读取，支持热重载。
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
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._thread = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name='email-sender', daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def send(self, to: str, subject: str, body: str, html: str = None):
        """将邮件加入队列（非阻塞，队列满时丢弃）。"""
        try:
            self._queue.put_nowait({
                'to': to,
                'subject': subject,
                'body': body,
                'html': html,
            })
        except queue.Full:
            print('[Email] 队列已满，丢弃邮件', flush=True)

    def is_enabled(self) -> bool:
        """邮件功能是否启用。"""
        return get_config_value('EMAIL_ENABLED', False)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _get_yagmail_client(self):
        """构建 yagmail 客户端（每次发送时读取最新配置，支持热重载）。"""
        import yagmail

        host = get_config_value('SMTP_HOST', '')
        port = get_config_value('SMTP_PORT', 465)
        user = get_config_value('SMTP_USER', '')
        password = get_config_value('SMTP_PASSWORD', '')
        sender = get_config_value('SMTP_SENDER_NAME', '') or '滨海小镇'

        if not host or not user or not password:
            return None

        return yagmail.SMTP(
            user=user,
            password=password,
            host=host,
            port=port,
            smtp_starttls=get_config_value('SMTP_STARTTLS', False),
            smtp_ssl=get_config_value('SMTP_SSL', True),
            smtp_set_debug_level=0,
        ), sender

    def _run_loop(self):
        """后台线程：从队列取邮件并发送。"""
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=5)
                if item is None:
                    break
                self._send_one(item)
            except queue.Empty:
                continue
            except Exception as e:
                print(f'[Email] 发送循环异常: {e}', flush=True)

        # 停止前清空队列
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item:
                    self._send_one(item)
            except queue.Empty:
                break

    def _send_one(self, item: dict):
        """发送单封邮件（含异常处理）。"""
        if not self.is_enabled():
            return

        try:
            result = self._get_yagmail_client()
            if result is None:
                print('[Email] SMTP 配置不完整，跳过发送', flush=True)
                return
            client, sender = result

            contents = [item.get('html') or item.get('body', '')]
            client.send(
                to=item['to'],
                subject=item['subject'],
                contents=contents,
                headers={'From': sender},
            )
            print(f"[Email] 已发送: {item['to']} <- {item['subject']}", flush=True)
        except Exception as e:
            print(f"[Email] 发送失败 ({item.get('to')}): {e}", flush=True)


# 全局单例
email_service = EmailService()
