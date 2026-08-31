"""
定时备份调度器。

每天在 BACKUP_SCHEDULED_TIME 指定的时间自动执行数据库备份。
使用后台线程 + 睡眠等待实现，不阻塞主进程。
支持热重载：通过 get_config_value() 读取最新配置。
"""

import threading
import time
import datetime

from config import get_config_value
from services.logger import log


class BackupScheduler:
    """每日定时备份调度器（单例）。"""

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
        self._last_backup_date = None  # 记录上次备份日期，避免重复触发

    def start(self):
        """启动定时备份调度器（后台线程）。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name='backup-scheduler',
            daemon=True,
        )
        self._thread.start()
        scheduled_time = get_config_value('BACKUP_SCHEDULED_TIME', '03:00')
        log('INFO', 'BackupScheduler', f'已启动，每日 {scheduled_time} 自动备份')

    def stop(self):
        """停止调度器。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run_loop(self):
        """后台线程主循环。"""
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log('ERROR', 'BackupScheduler', f'调度异常: {e}')
            self._stop_event.wait(30)

    def _tick(self):
        """检查是否到达备份时间。"""
        now = datetime.datetime.now()
        scheduled_time = get_config_value('BACKUP_SCHEDULED_TIME', '03:00')
        target_h, target_m = self._parse_time(scheduled_time)

        # 判断当前时间是否在目标时间的 1 分钟窗口内
        if now.hour == target_h and now.minute == target_m and now.second < 30:
            today_str = now.strftime('%Y-%m-%d')
            if self._last_backup_date != today_str:
                if not self._already_backed_up_today():
                    self._last_backup_date = today_str
                    self._do_backup()

    def _parse_time(self, time_str):
        """解析 HH:MM 格式时间字符串。"""
        try:
            parts = time_str.strip().split(':')
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return max(0, min(23, h)), max(0, min(59, m))
        except Exception:
            return 3, 0

    def _already_backed_up_today(self):
        """检查今天是否已经有成功的定时备份。"""
        from core.db import get_db
        today = datetime.date.today().strftime('%Y-%m-%d')
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM db_backups "
                "WHERE backup_type = 'scheduled' AND status = 'success' "
                "AND started_at LIKE ?",
                (f'{today}%',),
            ).fetchone()
            return row[0] > 0
        except Exception:
            return False
        finally:
            conn.close()

    def _do_backup(self):
        """执行定时备份。"""
        from .manager import BackupManager
        log('INFO', 'BackupScheduler', '开始定时自动备份...')
        backup_id, thread = BackupManager().start_backup(
            backup_type='scheduled',
            progress_callback=None,
        )
        if backup_id is None:
            log('INFO', 'BackupScheduler', '已有备份在执行，跳过本次')
