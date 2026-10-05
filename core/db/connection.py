"""数据库连接层 —— SQLite 连接封装，开启 WAL 模式。

实现要点：
- 使用 Python 内置 sqlite3，开启 WAL 模式 + 外键约束，充分发挥 SQLite 特性：
  并发读写（WAL）、崩溃安全（WAL + synchronous=NORMAL）、在线备份（backup API）
- 保持原有接口不变：get_db() 返回线程安全的连接对象，
  支持 execute / executemany / executescript / commit / rollback / close / cursor，
  行对象支持 keys() 与 ['列名'] 访问
- 单例共享连接 + 可重入锁，保证多线程读写安全
"""

import os
import sqlite3
import threading

from config import DB_PATH
from core.system.logger import log, log_fatal


def _recover_pending_wal():
    """记录上次异常退出残留的 WAL 文件，交给 SQLite 自动重放恢复。

    ⚠️ 绝对不能删除 site.db-wal / site.db-shm。
    WAL 里保存的是「已经 commit 成功、但还没合并进主库」的数据，
    直接删除等同于丢数据。此前这里会无条件删除这两个文件，
    导致「公共建筑审核通过后重启服务器，审核状态又变回待审核」——
    因为 UPDATE ... status='approved' 提交后数据仍在 WAL 中，
    进程一旦非正常结束（强杀 / 崩溃 / 看门狗重启），下次启动就被删掉了。

    正确做法：什么都不删。SQLite 打开数据库时会自动重放 WAL 完成恢复，
    在最后一个连接关闭时也会自动 checkpoint 并清理 WAL。
    """
    wal = DB_PATH + '-wal'
    if not os.path.isfile(wal):
        return
    try:
        size = os.path.getsize(wal)
    except OSError:
        size = -1
    log('INFO', 'DB', f'检测到上次未合并的 WAL（{size} 字节），由 SQLite 自动重放恢复，不做删除')


def _create_connection():
    """创建并配置 SQLite 连接。"""
    # 确保数据库所在目录存在
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    # 连接前先记录（绝不删除）残留 WAL，具体恢复由 SQLite 自动完成
    _recover_pending_wal()
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
        isolation_level=None,  # 自动提交模式
    )
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


# ---------------------------------------------------------------------------
# 单例连接 + 线程锁
# ---------------------------------------------------------------------------

_conn = None
_conn_lock = threading.RLock()  # 可重入锁，支持嵌套调用
_init_lock = threading.Lock()


def get_db():
    """获取数据库连接（单例共享，自动加锁）。

    用法一（推荐，自动提交/回滚）：
        with get_db() as conn:
            conn.execute(...)

    用法二（直接调用，用完记得 commit）：
        conn = get_db()
        conn.execute(...)
        conn.commit()
        conn.close()
    """
    global _conn
    if _conn is None:
        with _init_lock:
            if _conn is None:
                log('INFO', 'DB', '正在连接数据库...')
                try:
                    _conn = _create_connection()
                    log('INFO', 'DB', '数据库连接成功', path=DB_PATH, mode='WAL')
                except Exception as e:
                    log_fatal('CRITICAL', 'DB', '无法打开数据库，服务器无法启动',
                              path=DB_PATH, error=str(e))
                    raise
    return _ThreadSafeConnection(_conn, _conn_lock)


class _ThreadSafeConnection:
    """线程安全的连接包装器。

    - 直接调用方法时自动获取/释放锁（每次调用单独加锁）
    - with 语句块内持有锁，适合批量操作
    """

    def __init__(self, inner_conn, lock):
        self._inner = inner_conn
        self._lock = lock

    # ---- with 语句支持 ----
    def __enter__(self):
        self._lock.acquire()
        return self._inner

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._inner.commit()
            else:
                self._inner.rollback()
        finally:
            self._lock.release()
        return False

    # ---- 代理方法（每次调用单独加锁） ----
    def execute(self, sql, params=None):
        with self._lock:
            if params is None:
                return self._inner.execute(sql)
            return self._inner.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        with self._lock:
            return self._inner.executemany(sql, seq_of_params)

    def executescript(self, script):
        with self._lock:
            return self._inner.executescript(script)

    def commit(self):
        with self._lock:
            return self._inner.commit()

    def rollback(self):
        with self._lock:
            return self._inner.rollback()

    def close(self):
        # 单例连接不真正关闭
        pass

    def cursor(self):
        with self._lock:
            return self._inner.cursor()

    def backup_to(self, target_path):
        """使用 SQLite 在线备份 API 将数据库备份到指定文件。

        在线备份不受文件锁影响，可安全用于 Windows 等平台。
        """
        with self._lock:
            target = sqlite3.connect(target_path)
            try:
                self._inner.backup(target)
            finally:
                target.close()

    @property
    def row_factory(self):
        return self._inner.row_factory

    @row_factory.setter
    def row_factory(self, value):
        with self._lock:
            self._inner.row_factory = value


def reset_connection():
    """关闭并重置全局数据库连接。

    用于数据库恢复等场景：恢复会替换磁盘上的数据库文件，
    旧连接句柄继续使用可能导致数据不一致，需重新建立连接。
    """
    global _conn
    with _conn_lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
