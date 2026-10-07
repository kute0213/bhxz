"""
/uploads/ 全量数据备份服务 —— 极限压缩打包为 zip。

功能：
- 将 /uploads/ 文件夹下的所有内容压缩为 zip（ZIP_DEFLATED, level 9）
- 额外写入数据库一致快照：SQLite 主站库（uploads/db/site.db）与
  DuckDB 防火墙库（uploads/db/firewall.duckdb）
- 自动清理过期备份（保留 MAX_BACKUPS 份，支持热重载）
- 记录备份历史到 db_backups 表
- 提供进度回调接口（供前端进度条展示）
- 后台线程执行，不阻塞主进程

备份类型：
- scheduled: 定时自动备份
- manual: 管理员手动触发
"""

import os
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime

from config import (
    UPLOAD_DIR,
    BACKUP_FILENAME_FORMAT,
    get_config_value,
    get_uploads_backup_dir,
)
from core.system.logger import log


# 备份时需要跳过的文件后缀：
#   - SQLite / DuckDB 的 WAL / SHM / journal 等临时文件（正在写入，内容不一致）
#   - DuckDB 主库文件：DuckDB 运行期对 .duckdb 持有独占锁，Windows 下读取会
#     Permission denied（Errno 13），无法直接复制
# 数据库文件不走「原始文件复制」：一律由下方 _snapshot_* 生成一致快照后写入，
# 这样 WAL 中已提交但未合并的数据不会丢失，也不会出现「陈旧 WAL 覆盖主库」。
_SKIP_BACKUP_SUFFIXES = (
    '-wal', '-shm', '-journal',           # SQLite 临时文件
    '.duckdb', '.duckdb.wal', '.duckdb.tmp',  # DuckDB 主库与临时文件
)

# 数据库目录（uploads/db）：整目录交给快照逻辑处理，不在通用遍历中复制原始文件
_DB_DIR = os.path.join(UPLOAD_DIR, 'db')


def _should_skip_backup_file(fname: str) -> bool:
    """判断文件是否属于使用中/临时文件（数据库原始文件），备份时跳过。"""
    return fname.endswith(_SKIP_BACKUP_SUFFIXES)


def _zip_arcname(path: str) -> str:
    """把物理路径转换为备份 zip 内的相对路径（保留 uploads/ 前缀）。"""
    return os.path.relpath(path, os.path.dirname(UPLOAD_DIR))


def _snapshot_sqlite(dest_path: str) -> None:
    """用 SQLite 在线备份 API 生成一致快照。

    在线备份会自动完成 checkpoint：WAL 中「已提交但尚未合并进主库」的数据
    会一并写入快照，因此快照本身就是完整、可独立恢复的单文件数据库。
    不再单独存放 site.db-wal / site.db-shm —— 那是运行期临时文件，与主库
    版本不匹配时会被 SQLite 回放，反而损坏恢复出来的数据。
    """
    from core.db import get_db
    get_db().backup_to(dest_path)


def _snapshot_duckdb(dest_path: str) -> None:
    """用 DuckDB 引擎导出防火墙库的一致快照。

    DuckDB 运行期对主库文件持有独占锁，直接复制文件在 Windows 上会
    Permission denied；这里通过 ATTACH + COPY FROM DATABASE 让 DuckDB 自己
    导出，跨平台可用，且包含全部表结构与数据。
    """
    from services.firewall.service.database import get_db as get_fw_db

    if os.path.exists(dest_path):
        os.remove(dest_path)
    # DuckDB 的 ATTACH 不支持参数占位符，路径需转义单引号
    safe_path = dest_path.replace("'", "''")
    with get_fw_db() as conn:
        db_name = conn.execute('SELECT current_database()').fetchone()[0]
        conn.execute(f"ATTACH '{safe_path}' AS __backup_snapshot")
        try:
            conn.execute(f'COPY FROM DATABASE {db_name} TO __backup_snapshot')
        finally:
            conn.execute('DETACH __backup_snapshot')


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
        backup_path = os.path.join(get_uploads_backup_dir(), backup_name)

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

        tmp_dir = tempfile.mkdtemp(prefix='bhxz_backup_db_')
        try:
            # 阶段 1: 准备
            self._report_progress(5, '准备备份...', progress_callback)
            os.makedirs(get_uploads_backup_dir(), exist_ok=True)

            backup_name = datetime.now().strftime(BACKUP_FILENAME_FORMAT)
            backup_path = os.path.join(get_uploads_backup_dir(), backup_name)

            # 更新记录中的路径
            self._update_backup_record(backup_id, backup_name=backup_name, backup_path=backup_path)

            # 阶段 2: 统计文件数量（用于进度计算，跳过数据库原始文件）
            self._report_progress(10, '统计文件...', progress_callback)
            total_files = 0
            for dirpath, dirnames, filenames in os.walk(UPLOAD_DIR):
                if os.path.normpath(dirpath) == os.path.normpath(_DB_DIR):
                    continue
                total_files += sum(1 for f in filenames if not _should_skip_backup_file(f))
            if total_files == 0:
                total_files = 1  # 避免除零

            # 阶段 3: 极限压缩打包
            self._report_progress(20, f'正在压缩 {total_files} 个文件...', progress_callback)
            processed = 0
            skipped = 0

            with zipfile.ZipFile(
                backup_path, 'w',
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as zf:
                for dirpath, dirnames, filenames in os.walk(UPLOAD_DIR):
                    # 数据库目录整体交给快照逻辑，不复制运行期的原始文件
                    dirnames[:] = [
                        d for d in dirnames
                        if os.path.normpath(os.path.join(dirpath, d)) != os.path.normpath(_DB_DIR)
                    ]
                    for fname in filenames:
                        # 跳过 SQLite/DuckDB 的 WAL/SHM/临时文件与加锁的 DuckDB 主库
                        if _should_skip_backup_file(fname):
                            skipped += 1
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

                # 阶段 3.5: 数据库一致快照（SQLite 在线备份 + DuckDB 引擎导出）
                self._report_progress(76, '正在写入数据库快照...', progress_callback)
                self._write_db_snapshots(zf, tmp_dir)

            if skipped:
                log('INFO', 'BackupManager', f'已跳过 {skipped} 个使用中/临时文件（SQLite/DuckDB WAL 与 DuckDB 主库）')

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
            shutil.rmtree(tmp_dir, ignore_errors=True)

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

    def _write_db_snapshots(self, zf, tmp_dir):
        """把数据库一致快照写入备份 zip。

        覆盖两个库：
          - 主站 SQLite（uploads/db/site.db）：在线备份 API 导出，WAL 中已提交
            的数据一并落进快照；
          - 防火墙 DuckDB（uploads/db/firewall.duckdb）：引擎级导出。
        单个库失败只记 WARNING，不使整个备份失败（避免一个库的问题导致
        其余数据也拿不到）。
        """
        from config import DB_PATH

        targets = [(DB_PATH, _snapshot_sqlite, 'SQLite 主站库')]

        try:
            from services.firewall.service.database import DB_PATH as FW_DB_PATH
            if os.path.exists(FW_DB_PATH):
                targets.append((FW_DB_PATH, _snapshot_duckdb, 'DuckDB 防火墙库'))
        except Exception as e:
            log('WARNING', 'BackupManager', f'防火墙数据库不可用，跳过其快照: {e}')

        for src_path, snapshot, label in targets:
            arcname = _zip_arcname(src_path)
            tmp_path = os.path.join(tmp_dir, os.path.basename(src_path))
            try:
                snapshot(tmp_path)
                zf.write(tmp_path, arcname)
                log('INFO', 'BackupManager',
                    f'已写入数据库快照 {label} {arcname}（{os.path.getsize(tmp_path)} 字节）')
            except Exception as e:
                log('WARNING', 'BackupManager', f'数据库快照写入失败 {label} {arcname}: {e}')

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