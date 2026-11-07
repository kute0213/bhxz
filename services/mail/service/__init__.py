"""SMTP 邮件发送服务（后台线程异步发送，不阻塞主请求）。

发送失败时把邮件写入数据库重试队列（见 ``services.mail.retry``），
由全局定时任务每 60 秒扫描重发，最多 10 次。
"""

import queue
import threading

from core.system.logger import log_module, register_module_log

from services.mail.delivery import deliver, is_email_enabled
from services.mail.retry import record_failure

register_module_log('email')

# 发送队列容量（队列满时丢弃，避免阻塞调用方）
QUEUE_SIZE = 500


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
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
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
            log_module('email', 'WARNING', 'Email', '队列已满，丢弃邮件')

    def is_enabled(self) -> bool:
        """邮件功能是否启用。"""
        return is_email_enabled()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

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
                log_module('email', 'ERROR', 'Email', f'发送循环异常: {e}')

        # 停止前清空队列
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item:
                    self._send_one(item)
            except queue.Empty:
                break

    def _send_one(self, item: dict):
        """发送单封邮件：失败时写入数据库重试队列，由定时任务重发。"""
        if not self.is_enabled():
            return

        try:
            deliver(item)
            log_module('email', 'INFO', 'Email', f"已发送: {item['to']} <- {item['subject']}")
        except Exception as e:
            log_module('email', 'ERROR', 'Email',
                       f"发送失败，已加入重试队列 ({item.get('to')}): {type(e).__name__}: {e}")
            record_failure(item.get('to', ''), item.get('subject', ''),
                           item.get('body', ''), item.get('html'), e)


# 全局单例
email_service = EmailService()
