"""
/uploads/ 全量数据备份服务 —— 极限压缩打包为 zip。

功能：
- 将 /uploads/ 文件夹下的所有内容压缩为 zip（ZIP_DEFLATED, level 9）
- 自动清理过期备份（保留 MAX_BACKUPS 份，支持热重载）
- 记录备份历史到 db_backups 表
- 提供进度回调接口（供前端进度条展示）
- 后台线程执行，不阻塞主进程

备份类型：
- scheduled: 定时自动备份
- manual: 管理员手动触发
"""

import os
import threading
import time
import zipfile
from datetime import datetime

from config import (
    UPLOAD_DIR,
    UPLOADS_BACKUP_DIR,
    BACKUP_FILENAME_FORMAT,
    get_config_value,
)
from core.system.logger import log


# ---------------------------------------------------------------------------
# 单例：备份管理器
# ---------------------------------------------------------------------------

class BackupManager:
    """数据备份管理器（单例）。"""

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
        """启动数据备份（后台线程执行）。

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
            name=f'data-backup-{backup_id}',
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
            return [dict(r) for r in rows]
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
        backup_path = os.path.join(UPLOADS_BACKUP_DIR, backup_name)

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
            os.makedirs(UPLOADS_BACKUP_DIR, exist_ok=True)

            backup_name = datetime.now().strftime(BACKUP_FILENAME_FORMAT)
            backup_path = os.path.join(UPLOADS_BACKUP_DIR, backup_name)

            # 更新记录中的路径
            self._update_backup_record(backup_id, backup_name=backup_name, backup_path=backup_path)

            # 阶段 2: 统计文件数量（用于进度计算）
            self._report_progress(10, '统计文件...', progress_callback)
            total_files = 0
            for dirpath, dirnames, filenames in os.walk(UPLOAD_DIR):
                total_files += len(filenames)
            if total_files == 0:
                total_files = 1  # 避免除零

            # 阶段 3: 极限压缩打包
            self._report_progress(20, f'正在压缩 {total_files} 个文件...', progress_callback)
            processed = 0

            with zipfile.ZipFile(
                backup_path, 'w',
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as zf:
                for dirpath, dirnames, filenames in os.walk(UPLOAD_DIR):
                    for fname in filenames:
                        # 跳过 DuckDB/SQLite WAL/SHM 临时文件
                        if fname.endswith('-wal') or fname.endswith('-shm'):
                            continue
                        full_path = os.path.join(dirpath, fname)
                        # zip 内使用相对路径
                        arcname = os.path.relpath(full_path, os.path.dirname(UPLOAD_DIR))
                        try:
                            zf.write(full_path, arcname)
                        except Exception as e:
                            log('WARNING', 'BackupManager', f'压缩文件跳过 {full_path}: {e}')
                        processed += 1
                        if processed % max(1, total_files // 5) == 0:
                            pct = 20 + int(processed / total_files * 55)
                            self._report_progress(pct, f'已压缩 {processed}/{total_files}...', progress_callback)

            size_bytes = os.path.getsize(backup_path)

            # 阶段 4: 验证备份文件
            self._report_progress(80, '验证备份文件...', progress_callback)
            self._verify_backup(backup_path)

            # 阶段 5: 清理旧备份
            self._report_progress(90, '清理过期备份...', progress_callback)
            self._cleanup_old_backups()

            # 阶段 6: 完成
            self._report_progress(100, '备份完成', progress_callback)

            status = 'success'

        except Exception as e:
            error_msg = str(e)
            status = 'failed'
            log('ERROR', 'BackupManager', f'备份失败: {e}')
            import traceback
            traceback.print_exc()
            # 清理不完整的 zip
            if backup_path and os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass

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

    def _verify_backup(self, backup_path):
        """验证 zip 备份文件是否完整可读。"""
        import zipfile
        with zipfile.ZipFile(backup_path, 'r') as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f'备份文件损坏，首个坏文件: {bad}')

    def _cleanup_old_backups(self):
        """删除超出 MAX_BACKUPS 限制的旧备份（文件 + 记录）。支持热重载。"""
        max_backups = get_config_value('MAX_BACKUPS', 30)
        if max_backups <= 0:
            return

        from core.db import get_db
        conn = get_db()
        try:
            # 获取所有备份，按时间倒序
            rows = conn.execute(
                "SELECT id, backup_path, status FROM db_backups ORDER BY id DESC"
            ).fetchall()

            if len(rows) <= max_backups:
                return

            # 超出部分删除
            to_delete = rows[max_backups:]
            for row in to_delete:
                path = row[1] if isinstance(row, (list, tuple)) else row['backup_path']
                bid = row[0] if isinstance(row, (list, tuple)) else row['id']
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    log('ERROR', 'BackupManager', f'删除旧备份文件失败 {path}: {e}')
                try:
                    conn.execute("DELETE FROM db_backups WHERE id = ?", (bid,))
                except Exception as e:
                    log('ERROR', 'BackupManager', f'删除旧备份记录失败 id={bid}: {e}')

            conn.commit()
        finally:
            conn.close()