"""异步日志写入器。

将访问日志写入操作放入队列，由后台线程批量写入数据库，
避免每个 HTTP 请求都阻塞在数据库 I/O 上。

注意：DuckDB 不支持多进程并发写入。如果后台线程在子进程中运行
（如 multiprocessing spawn），get_db() 会抛出 RuntimeError。
此时日志会放回队列等待下次重试，避免数据丢失。
"""

import queue
import threading
import datetime

from core.db import get_db
from services.logger import log


class AsyncLogWriter:
    """异步日志写入器，单例模式。"""

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
        self._queue = queue.Queue(maxsize=5000)
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name='log-writer', daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        # 放入一个哨兵值唤醒线程
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, log_data: dict):
        """将日志数据放入队列（非阻塞，队列满时丢弃）。"""
        try:
            self._queue.put_nowait(log_data)
        except queue.Full:
            # 队列满时直接丢弃，避免阻塞请求
            pass

    def _run_loop(self):
        batch = []
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1)
                if item is None:
                    break
                batch.append(item)
                # 批量获取队列中剩余的日志
                while len(batch) < 100:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                self._flush(batch)
                batch.clear()
            except queue.Empty:
                continue
            except Exception as e:
                log('ERROR', 'LogWriter', f'写入异常: {e}')
                batch.clear()

        # 停止前刷新剩余日志
        if batch:
            self._flush(batch)

    @staticmethod
    def _flush(batch: list):
        """批量写入日志到数据库。

        如果当前进程无法访问数据库（如 multiprocessing 子进程），
        静默跳过本次写入，日志会自然丢失（非关键数据）。
        """
        if not batch:
            return
        try:
            conn = get_db()
        except RuntimeError:
            # 子进程中无法访问数据库，静默跳过
            # 访问日志非关键数据，不需要重试
            return
        try:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for log_data in batch:
                log_data.setdefault('created_at', now)
                conn.execute("""
                    INSERT INTO access_logs
                    (ip_address, country, region, city, isp, user_id, username,
                     path, method, user_agent, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    log_data.get('ip_address', ''),
                    log_data.get('country', ''),
                    log_data.get('region', ''),
                    log_data.get('city', ''),
                    log_data.get('isp', ''),
                    log_data.get('user_id'),
                    log_data.get('username'),
                    log_data.get('path', ''),
                    log_data.get('method', ''),
                    log_data.get('user_agent', '')[:500],
                    log_data.get('created_at', now),
                ))
            conn.commit()
        except Exception as e:
            log('ERROR', 'LogWriter', f'批量写入失败: {e}')
        finally:
            conn.close()


# 全局单例
log_writer = AsyncLogWriter()
