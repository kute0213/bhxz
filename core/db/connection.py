"""数据库连接层 —— 原生 sqlite3 极简封装，开启 WAL 模式。

采用最直接、最好验证的写法：`get_db()` 每次返回一条**全新的原生 sqlite3 连接**，
调用方自己负责用完 `close()`。没有线程本地连接复用、没有连接包装器、
没有全局连接注册表与代次失效机制——从根源上消除「close() 是空操作、
连接被跨线程复用、全局状态残留」这一整类问题。

标准用法（简洁、无隐式状态）：

    conn = get_db()
    try:
        conn.execute(...)
        conn.commit()          # 写操作需提交
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

需要「块内多条语句整体原子提交/回滚」时用事务上下文管理器：

    with transaction() as conn:
        conn.execute(...)      # 正常退出自动 commit，异常自动 rollback，最后 close

SQLite 配置：
- WAL 日志模式：读写并发（多读 + 单写），崩溃安全
- synchronous=NORMAL：WAL 下性能与安全的平衡点
- foreign_keys=ON：开启外键约束
- busy_timeout=30000：写锁争用时自动等待重试
- 写事务用 BEGIN IMMEDIATE：见 transaction() 说明

多线程写入时序说明（为什么不加应用层写队列也不会写乱）：
    SQLite 本身就是「单写者」数据库——任意时刻只允许一个写事务，
    由 SQLite 用文件锁统一排队。本层在此基础上用 BEGIN IMMEDIATE
    让写事务一开始就独占写锁（而非 DEFERRED 的「先读锁、写时再升级」），
    从而避免两个并发写事务同时持读锁、再抢写锁导致的 SQLITE_BUSY 升级冲突。
    因此：并发写入天然串行、互不打断、不会出现事务边界错乱；
    应用层无需再自建写队列（那反而会引入额外的阻塞与故障面）。
"""

import os
import sqlite3
from contextlib import contextmanager

from config import DB_PATH
from core.system.logger import log, log_fatal

# 残留 WAL 提示只记录一次（每次连接都检测会导致刷屏）
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
    """创建并配置一条全新的原生 SQLite 连接。"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    # 连接前先记录（绝不删除）残留 WAL，具体恢复由 SQLite 自动完成
    _recover_pending_wal()
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        isolation_level=None,   # 自动提交模式；事务由 transaction() 显式 BEGIN 控制
    )
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def get_db():
    """获取一条全新的数据库连接（调用方负责 close）。

    注意：这里不做连接复用——每次调用都会新建一条独立连接，
    用完必须 `conn.close()`。这样每条连接的语句与事务天然隔离，
    不存在多线程共享连接导致的事务边界错乱问题。
    """
    try:
        return _create_connection()
    except sqlite3.OperationalError as e:
        raise _fatal_connect_error(e)


def _fatal_connect_error(e):
    msg = str(e)
    if '锁定' in msg or 'locked' in msg.lower():
        log_fatal('CRITICAL', 'DB', '数据库被锁定，无法建立连接', error=msg)
    else:
        log_fatal('CRITICAL', 'DB', '数据库连接失败', path=DB_PATH, error=msg)
    return e


@contextmanager
def transaction():
    """事务块：全新连接 + 显式 BEGIN IMMEDIATE，正常退出提交、异常回滚、最后关闭。

    块内的多条语句要么整体提交、要么整体回滚，保证原子性；
    无论正常结束、提前 return 还是抛异常，连接都会被关闭。

    为什么用 IMMEDIATE 而不是默认的 DEFERRED：
        默认 BEGIN 只先拿读锁，直到第一条写语句才尝试升级为写锁。
        多线程并发写时，两个事务可能同时持读锁、再同时申请写锁，
        其中一个会拿到 SQLITE_BUSY 而被迫回滚重试——这正是「多线程写入时序问题」的根源。
        BEGIN IMMEDIATE 在事务开始时就申请写锁，由 SQLite 统一排队：
        任意时刻只有一个写事务在推进，其余按 busy_timeout 等待，
        从而做到并发写天然串行、互不打断、不会锁升级冲突。
    """
    conn = _create_connection()
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_to(target_path):
    """使用 SQLite 在线备份 API 把数据库备份到指定文件。

    在线备份会自动完成 checkpoint：WAL 中「已提交但尚未合并进主库」的数据
    会一并写入目标文件，因此目标文件本身就是完整、可独立恢复的单文件数据库。
    在线备份不受文件锁影响，可安全用于 Windows 等平台。
    """
    src = _create_connection()
    try:
        dest = sqlite3.connect(target_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()


def flush_and_close_all():
    """服务器优雅退出：对 WAL 执行 checkpoint，把已提交数据合并进主库。

    每次 get_db() 的连接都由调用方即时关闭，退出时已无连接可关；
    此函数只需一条临时连接执行 `wal_checkpoint(TRUNCATE)`，确保
    「已 commit 但仍在 WAL 中」的数据全部落盘（避免进程被杀后 WAL 残留）。
    """
    checkpoint()
    log('INFO', 'DB', 'WAL 已合并落盘')


def checkpoint():
    """把 WAL 中「已提交但尚未合并进主库」的数据合并落盘（TRUNCATE 模式）。

    可用于优雅退出前、或大批量数据迁移完成后，确保数据进入主库单文件，
    避免长时间只停留在 WAL 中。返回是否成功。
    """
    try:
        conn = _create_connection()
        try:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            conn.close()
        return True
    except sqlite3.Error as exc:
        log('WARNING', 'DB', f'WAL 检查点失败: {exc}')
        return False
