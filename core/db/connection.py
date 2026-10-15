"""数据库连接层 —— SQLite 连接封装，开启 WAL 模式。

实现要点：
- 使用 Python 内置 sqlite3，开启 WAL 模式 + 外键约束，充分发挥 SQLite 特性：
  并发读写（WAL）、崩溃安全（WAL + synchronous=NORMAL）、在线备份（backup API）
- **每线程一条连接**（thread-local）：彻底消除「多线程共享单条连接」导致的一类
  并发问题，从根源上保证并发安全：
    * 同一连接被多线程并发使用会触发
      `sqlite3.InterfaceError: bad parameter or other API misuse` /
      `Recursive use of cursors not allowed`；
    * 一条连接上的多条语句会在不同线程间交错，导致事务边界错乱
      （甲线程的 COMMIT 会把乙线程尚未提交的语句一并提交）。
  每线程独立连接后，各线程的语句与事务天然隔离，互不干扰。
- WAL 模式下读与写互不阻塞（多读 + 单写），配合 `busy_timeout` 处理写锁争用，
  高并发读写都能得到正确的排队与重试，而不是退化成全局串行。
- 保持原有接口不变：get_db() 返回可用的连接对象，
  支持 execute / executemany / executescript / commit / rollback / close / cursor，
  行对象支持 keys() 与 ['列名'] 访问。
- `with get_db() as conn:` 会开启一个真正的（延迟）事务：块内多条语句要么整体
  提交、要么整体回滚，得到原子性；嵌套使用时只在最外层提交/回滚。
"""

import os
import sqlite3
import threading

from config import DB_PATH
from core.system.logger import log, log_fatal


# ---------------------------------------------------------------------------
# 线程本地连接管理
# ---------------------------------------------------------------------------

_tls = threading.local()          # 每线程持有 conn / generation / 事务嵌套深度
_registry = set()                 # 已创建的全部连接（仅用于关闭/检查点）
_registry_lock = threading.Lock()
_generation = 0                   # 连接代次；reset/关闭时 +1，令旧连接失效
_wal_recovery_logged = False


def _recover_pending_wal():
    """记录上次异常退出残留的 WAL 文件，交给 SQLite 自动重放恢复（仅记录一次）。

    ⚠️ 绝对不能删除 site.db-wal / site.db-shm。
    WAL 里保存的是「已经 commit 成功、但还没合并进主库」的数据，
    直接删除等同于丢数据。此前这里会无条件删除这两个文件，
    导致「公共建筑审核通过后重启服务器，审核状态又变回待审核」——
    因为 UPDATE ... status='approved' 提交后数据仍在 WAL 中，
    进程一旦非正常结束（强杀 / 崩溃 / 看门狗重启），下次启动就被删掉了。

    正确做法：什么都不删。SQLite 打开数据库时会自动重放 WAL 完成恢复，
    在最后一个连接关闭时也会自动 checkpoint 并清理 WAL。
    """
    global _wal_recovery_logged
    if _wal_recovery_logged:
        return
    _wal_recovery_logged = True
    wal = DB_PATH + '-wal'
    if not os.path.isfile(wal):
        return
    try:
        size = os.path.getsize(wal)
    except OSError:
        size = -1
    log('INFO', 'DB', f'检测到上次未合并的 WAL（{size} 字节），由 SQLite 自动重放恢复，不做删除')


def _create_connection():
    """创建并配置一条 SQLite 连接。"""
    # 确保数据库所在目录存在
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    # 连接前先记录（绝不删除）残留 WAL，具体恢复由 SQLite 自动完成
    _recover_pending_wal()
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        isolation_level=None,   # 自动提交模式；事务由 with get_db() 显式 BEGIN 控制
    )
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _current_connection():
    """返回当前线程的连接（不存在或已失效则新建）。"""
    conn = getattr(_tls, 'conn', None)
    if conn is None or getattr(_tls, 'generation', -1) != _generation:
        conn = _create_connection()
        _tls.conn = conn
        _tls.generation = _generation
        _tls.depth = 0
        try:
            _tls.conn.execute('SELECT 1')
        except sqlite3.Error:
            pass
        with _registry_lock:
            _registry.add(conn)
        log('INFO', 'DB', f'线程新建立数据库连接（当前活跃连接数 {len(_registry)}）')
    return conn


def get_db():
    """获取当前线程的数据库连接（线程安全）。

    用法一（推荐：块内多条语句原子提交/回滚）：
        with get_db() as conn:
            conn.execute(...)

    用法二（直接调用，单条语句自动提交）：
        conn = get_db()
        conn.execute(...)
        conn.commit()
        conn.close()
    """
    try:
        return _DBConnection(_current_connection())
    except sqlite3.OperationalError as e:
        raise _fatal_connect_error(e)


def _fatal_connect_error(e):
    msg = str(e)
    if '锁定' in msg or 'locked' in msg.lower():
        log_fatal('CRITICAL', 'DB', '数据库被锁定，无法建立连接', error=msg)
    else:
        log_fatal('CRITICAL', 'DB', '数据库连接失败', path=DB_PATH, error=msg)
    return e


class _DBConnection:
    """连接包装器：为 `with` 块提供事务语义，其余方法直接代理到底层连接。

    - `with` 块：进入最外层时开启延迟事务（BEGIN），退出时提交（或异常回滚）。
      嵌套使用时只在最外层提交/回滚，支持块内互相调用。
    - 直接调用方法（不经 `with`）：底层连接为自动提交模式，单条语句即提交。
    """

    __slots__ = ('_inner',)

    def __init__(self, inner):
        self._inner = inner

    # ---- with 语句支持：真实事务 ----
    def __enter__(self):
        depth = getattr(_tls, 'depth', 0)
        if depth == 0 and not self._inner.in_transaction:
            self._inner.execute('BEGIN')
        _tls.depth = depth + 1
        return self._inner

    def __exit__(self, exc_type, exc_val, exc_tb):
        depth = max(0, getattr(_tls, 'depth', 1) - 1)
        _tls.depth = depth
        if depth == 0:
            try:
                if exc_type is None:
                    self._inner.commit()
                else:
                    self._inner.rollback()
            except sqlite3.Error:
                pass
        return False

    # ---- 代理方法 ----
    def execute(self, sql, params=None):
        if params is None:
            return self._inner.execute(sql)
        return self._inner.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self._inner.executemany(sql, seq_of_params)

    def executescript(self, script):
        return self._inner.executescript(script)

    def commit(self):
        # 无活动事务时为 no-op（sqlite3 的 commit 语义），可安全调用
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        # 线程本地连接随线程复用，不在此释放；由 flush_and_close_all() 统一关闭
        pass

    def cursor(self):
        return self._inner.cursor()

    def backup_to(self, target_path):
        """使用 SQLite 在线备份 API 将数据库备份到指定文件。

        在线备份不受文件锁影响，可安全用于 Windows 等平台。
        """
        target = sqlite3.connect(target_path)
        try:
            self._inner.backup(target)
        finally:
            target.close()

    # ---- 兼容属性 ----
    @property
    def row_factory(self):
        return self._inner.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._inner.row_factory = value

    @property
    def in_transaction(self):
        return self._inner.in_transaction

    def __getattr__(self, name):
        # 其余属性/方法透明代理到底层连接（保持兼容）
        return getattr(self._inner, name)


def _invalidate_all(*, close=True):
    """令所有已创建的连接失效；可选地关闭它们。返回被关闭的连接列表。"""
    global _generation
    with _registry_lock:
        _generation += 1
        conns = list(_registry)
        _registry.clear()
    # 清理调用线程自身的 thread-local 引用，其余线程会在下次 get_db() 时自动重建
    if getattr(_tls, 'conn', None) is not None:
        _tls.conn = None
    if close:
        for c in conns:
            try:
                c.rollback()
            except sqlite3.Error:
                pass
            try:
                c.close()
            except sqlite3.Error:
                pass
    return conns


def reset_connection():
    """关闭并重置全部数据库连接。

    用于数据库恢复等场景：恢复会替换磁盘上的数据库文件，
    旧连接句柄继续使用可能导致数据不一致，需重新建立连接。
    所有线程会在下次 get_db() 时自动重建连接。
    """
    _invalidate_all(close=True)
    log('INFO', 'DB', '数据库连接已全部重置')


def flush_and_close_all():
    """关闭所有连接并把 WAL 合并落盘（用于服务器优雅退出）。

    先关闭全部连接（未提交事务回滚），再用一条临时连接执行
    `wal_checkpoint(TRUNCATE)`，确保已提交数据全部合并进主库文件。
    """
    _invalidate_all(close=True)
    try:
        conn = _create_connection()
        try:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log('WARNING', 'DB', f'关闭前 WAL 检查点失败: {exc}')
    log('INFO', 'DB', '全部数据库连接已关闭，WAL 已合并')
