"""日志自动清除服务。

后台线程定期检查各日志表的记录数量，超过上限时自动删除最旧的记录。
支持热重载：通过 config.get_config_value() 读取最新配置。
"""

import threading
import time

from config import get_config_value
from core.db import get_db


# 各日志表与其上限的映射（动态读取配置，支持热重载）
_LOG_TABLE_CONFIGS = [
    ('access_logs', 'MAX_ACCESS_LOGS'),
    ('cmd_run_logs', 'MAX_CMD_LOGS'),
    ('scheduled_task_logs', 'MAX_TASK_LOGS'),
]


class LogCleaner:
    """日志清理器，单例模式。"""

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
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name='log-cleaner', daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _get_cleanup_interval(self) -> int:
        """获取当前日志清理间隔（秒）。"""
        return get_config_value('LOG_CLEANUP_INTERVAL', 300)

    def _get_log_tables(self):
        """获取日志表与上限的映射（支持热重载）。"""
        result = []
        for table, key in _LOG_TABLE_CONFIGS:
            max_count = get_config_value(key, 500)
            result.append((table, max_count))
        return result

    def _run_loop(self):
        # 启动时先等待一个间隔，避免与初始化竞争
        while not self._stop_event.wait(self._get_cleanup_interval()):
            try:
                self._clean_all()
            except Exception as e:
                print(f'[LogCleaner] 清理异常: {e}', flush=True)

    def _clean_all(self):
        """检查所有日志表并清理超限记录。"""
        conn = get_db()
        try:
            for table, max_count in self._get_log_tables():
                self._clean_table(conn, table, max_count)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _clean_table(conn, table: str, max_count: int):
        """清理单个表中超限的旧记录。"""
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        total = row['c'] if row else 0
        if total <= max_count:
            return

        excess = total - max_count
        conn.execute(
            f"DELETE FROM {table} WHERE id IN "
            f"(SELECT id FROM {table} ORDER BY id ASC LIMIT ?)",
            (excess,),
        )
        print(f'[LogCleaner] {table}: 删除 {excess} 条旧记录 (剩余 {max_count})', flush=True)

    def clean_once(self):
        """手动触发一次清理。"""
        self._clean_all()


# 全局单例
log_cleaner = LogCleaner()
