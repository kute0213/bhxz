"""
定时备份调度器。

每天在 BACKUP_SCHEDULED_TIME 指定的时间自动执行数据库备份。
使用统一定时调度器（core/scheduler.py）实现，不阻塞主进程。
支持热重载：通过 get_config_value() 读取最新配置。
"""

import datetime
import threading

from config import get_config_value
from core.logger import log
from core.scheduler import Scheduler


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
        # 统一定时调度器：每天 BACKUP_SCHEDULED_TIME 触发一次（时间点模式）
        self._scheduler = Scheduler(
            name='backup-scheduler',
            action=self._action,
            run_at=lambda: get_config_value('BACKUP_SCHEDULED_TIME', '03:00'),
            run_immediately=False,
            tick=30,
        )

    def start(self):
        """启动定时备份调度器（后台线程）。"""
        if not self._scheduler.start():
            return
        scheduled_time = get_config_value('BACKUP_SCHEDULED_TIME', '03:00')
        log('INFO', 'BackupScheduler', f'已启动，每日 {scheduled_time} 自动备份')

    def stop(self):
        """停止调度器。"""
        self._scheduler.stop()

    def _action(self):
        """时间点命中时执行：当天已有成功定时备份则跳过，否则触发备份。"""
        if self._already_backed_up_today():
            return
        self._do_backup()

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
