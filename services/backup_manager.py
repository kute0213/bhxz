"""
数据库备份与优化服务。

功能：
- 备份 DuckDB 数据库文件到 BACKUP_DIR
- 自动清理过期备份（保留 MAX_BACKUPS 份）
- 备份前执行 CHECKPOINT（可选，减少文件大小）
- 备份前清理过期日志（可选）
- 记录备份历史到 db_backups 表
- 提供进度回调接口（供前端进度条展示）
- 后台线程执行，不阻塞主进程

备份类型：
- scheduled: 定时自动备份
- manual: 管理员手动触发
"""

import os
import shutil
import threading
import time
from datetime import datetime

from config import (
    DB_PATH,
    BACKUP_DIR,
    BACKUP_FILENAME_FORMAT,
    MAX_BACKUPS,
    BACKUP_CLEAN_LOGS,
    BACKUP_CHECKPOINT,
)


# ---------------------------------------------------------------------------
# 单例：备份管理器
# ---------------------------------------------------------------------------

class BackupManager:
    """数据库备份管理器（单例）。"""

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
        self._backup_lock = threading.Lock()   # 防止同时执行多个备份
        self._last_backup = None               # 最近一次备份信息
        self._current_progress = None          # 当前备份进度 (0-100)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def start_backup(self, backup_type='manual', progress_callback=None):
        """启动数据库备份（后台线程执行）。

        Args:
            backup_type: 'scheduled' 或 'manual'
            progress_callback: 进度回调函数 callback(percent, message)

        Returns:
            (backup_id, thread)  备份记录 ID 和执行线程
        """
        with self._backup_lock:
            if self._current_progress is not None:
                # 已有备份在执行，拒绝
                return None, None

            self._current_progress = 0
            backup_id = self._create_backup_record(backup_type)

        thread = threading.Thread(
            target=self._run_backup,
            args=(backup_id, backup_type, progress_callback),
            name=f'db-backup-{backup_id}',
            daemon=True,
        )
        thread.start()
        return backup_id, thread

    def get_progress(self):
        """获取当前备份进度 (0-100)，None 表示不在备份。"""
        return self._current_progress

    def get_last_backup(self):
        """获取最近一次备份信息。"""
        return self._last_backup

    def list_backups(self, limit=20):
        """列出备份历史记录。"""
        from core.db import get_db
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM db_backups ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(zip([d[0] for d in conn.cursor().description], r)) if not hasattr(r, 'keys') else dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _create_backup_record(self, backup_type):
        """创建备份记录（状态为 running）。"""
        from core.db import get_db
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        backup_name = datetime.now().strftime(BACKUP_FILENAME_FORMAT)
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO db_backups "
                "(backup_name, backup_path, backup_type, status, started_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (backup_name, backup_path, backup_type, now),
            )
            conn.commit()
            # 获取 ID
            row = conn.execute(
                "SELECT MAX(id) AS id FROM db_backups"
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _update_backup_record(self, backup_id, **kwargs):
        """更新备份记录。"""
        from core.db import get_db
        conn = get_db()
        try:
            fields = ', '.join(f'{k} = ?' for k in kwargs.keys())
            values = list(kwargs.values()) + [backup_id]
            conn.execute(f"UPDATE db_backups SET {fields} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    def _report_progress(self, percent, message, callback):
        """报告进度。"""
        self._current_progress = percent
        if callback:
            try:
                callback(percent, message)
            except Exception:
                pass

    def _run_backup(self, backup_id, backup_type, progress_callback):
        """执行备份的后台线程函数。"""
        start_time = time.time()
        error_msg = None
        backup_path = None
        size_bytes = 0

        try:
            # 阶段 1: 准备
            self._report_progress(5, '准备备份...', progress_callback)
            os.makedirs(BACKUP_DIR, exist_ok=True)

            backup_name = datetime.now().strftime(BACKUP_FILENAME_FORMAT)
            backup_path = os.path.join(BACKUP_DIR, backup_name)

            # 更新记录中的路径
            self._update_backup_record(backup_id, backup_name=backup_name, backup_path=backup_path)

            # 阶段 2: 清理过期日志
            if BACKUP_CLEAN_LOGS:
                self._report_progress(15, '清理过期日志...', progress_callback)
                try:
                    self._clean_logs()
                except Exception as e:
                    print(f'[Backup] 清理日志失败: {e}', flush=True)

            # 阶段 3: CHECKPOINT（合并 WAL 到主文件）
            if BACKUP_CHECKPOINT:
                self._report_progress(30, '执行 CHECKPOINT...', progress_callback)
                try:
                    self._run_checkpoint()
                except Exception as e:
                    print(f'[Backup] CHECKPOINT 失败: {e}', flush=True)

            # 阶段 4: 复制数据库文件
            self._report_progress(50, f'复制数据库文件到 {backup_name}...', progress_callback)

            if not os.path.exists(DB_PATH):
                raise FileNotFoundError(f'数据库文件不存在: {DB_PATH}')

            # 用 shutil.copy2 保留元信息
            file_size = os.path.getsize(DB_PATH)
            shutil.copy2(DB_PATH, backup_path)
            size_bytes = os.path.getsize(backup_path)

            # 阶段 5: 验证备份文件
            self._report_progress(80, '验证备份文件...', progress_callback)
            self._verify_backup(backup_path)

            # 阶段 6: 清理旧备份
            self._report_progress(90, '清理过期备份...', progress_callback)
            self._cleanup_old_backups()

            # 阶段 7: 完成
            self._report_progress(100, '备份完成', progress_callback)

            status = 'success'

        except Exception as e:
            error_msg = str(e)
            status = 'failed'
            print(f'[Backup] 备份失败: {e}', flush=True)
            import traceback
            traceback.print_exc()

        finally:
            elapsed = round(time.time() - start_time, 2)
            finished_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            self._update_backup_record(
                backup_id,
                status=status,
                size_bytes=size_bytes,
                error_message=error_msg,
                finished_at=finished_at,
                duration_seconds=elapsed,
            )

            self._last_backup = {
                'id': backup_id,
                'status': status,
                'backup_path': backup_path,
                'size_bytes': size_bytes,
                'duration_seconds': elapsed,
                'finished_at': finished_at,
            }

            self._current_progress = None

    def _clean_logs(self):
        """触发日志清理（复用 log_cleaner 的逻辑）。"""
        try:
            from services.log_cleaner import LogCleaner
            cleaner = LogCleaner()
            cleaner.clean_once()
        except Exception as e:
            print(f'[Backup] 调用日志清理失败: {e}', flush=True)

    def _run_checkpoint(self):
        """执行 CHECKPOINT，将 WAL 合并到主数据库文件。"""
        import duckdb
        conn = duckdb.connect(DB_PATH)
        try:
            conn.execute('CHECKPOINT')
        finally:
            conn.close()

    def _verify_backup(self, backup_path):
        """验证备份文件是否可读（打开并执行简单查询）。"""
        import duckdb
        conn = duckdb.connect(backup_path, read_only=True)
        try:
            # 查询系统表验证数据库完整性
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        finally:
            conn.close()

    def _cleanup_old_backups(self):
        """删除超出 MAX_BACKUPS 限制的旧备份（文件 + 记录）。"""
        if MAX_BACKUPS <= 0:
            return

        from core.db import get_db
        conn = get_db()
        try:
            # 获取所有备份，按时间倒序
            rows = conn.execute(
                "SELECT id, backup_path, status FROM db_backups ORDER BY id DESC"
            ).fetchall()

            if len(rows) <= MAX_BACKUPS:
                return

            # 超出部分删除
            to_delete = rows[MAX_BACKUPS:]
            for row in to_delete:
                path = row[1] if isinstance(row, (list, tuple)) else row['backup_path']
                bid = row[0] if isinstance(row, (list, tuple)) else row['id']
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    print(f'[Backup] 删除旧备份文件失败 {path}: {e}', flush=True)
                try:
                    conn.execute("DELETE FROM db_backups WHERE id = ?", (bid,))
                except Exception as e:
                    print(f'[Backup] 删除旧备份记录失败 id={bid}: {e}', flush=True)

            conn.commit()
        finally:
            conn.close()
