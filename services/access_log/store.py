"""访问日志 DuckDB 存储 —— 独立数据库文件，随抓取会话创建与删除。

访问日志与主站 SQLite、防火墙 DuckDB 完全隔离：抓取开启时创建
``uploads/db/access_logs.duckdb``，取消抓取后连同 WAL 一起删除。

所有读写共用同一条连接，并用可重入锁串行化，避免 DuckDB 单连接并发限制。
"""

import os
import threading

from config import APP_ROOT

DB_DIR = os.path.join(APP_ROOT, 'uploads', 'db')
DB_PATH = os.path.join(DB_DIR, 'access_logs.duckdb')

# 查询列顺序与 query_recent() 返回的字典键一一对应
COLUMNS = (
    'id', 'captured_at', 'ip', 'method', 'path', 'query_string',
    'status', 'duration_ms', 'user_id', 'username', 'user_agent', 'referer',
)

_conn = None
_conn_lock = threading.RLock()

_CREATE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS access_logs (
        id BIGINT PRIMARY KEY,
        captured_at TIMESTAMP NOT NULL,
        ip VARCHAR DEFAULT '',
        method VARCHAR DEFAULT '',
        path VARCHAR DEFAULT '',
        query_string VARCHAR DEFAULT '',
        status INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        user_id INTEGER DEFAULT 0,
        username VARCHAR DEFAULT '',
        user_agent VARCHAR DEFAULT '',
        referer VARCHAR DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_access_logs_time ON access_logs(captured_at)",
)

_INSERT_SQL = (
    "INSERT INTO access_logs "
    "(id, captured_at, ip, method, path, query_string, status, duration_ms, "
    " user_id, username, user_agent, referer) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_SELECT_RECENT_SQL = (
    "SELECT id, strftime('%Y-%m-%d %H:%M:%S', captured_at), ip, method, path, "
    "       query_string, status, duration_ms, user_id, username, user_agent, referer "
    "FROM access_logs ORDER BY id DESC LIMIT ?"
)


def _remove_files():
    """删除数据库主文件与 WAL / 临时文件（不存在时忽略）。"""
    for suffix in ('', '.wal', '.tmp'):
        try:
            os.remove(DB_PATH + suffix)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def open_store():
    """创建全新的访问日志数据库并打开连接（开启抓取时调用）。"""
    global _conn
    with _conn_lock:
        if _conn is not None:
            return
        import duckdb
        os.makedirs(DB_DIR, exist_ok=True)
        # 每次开启都是全新会话：清掉上一次异常退出可能残留的文件
        _remove_files()
        conn = duckdb.connect(DB_PATH)
        conn.execute("SET threads TO 2")
        conn.execute("SET memory_limit = '256MB'")
        for statement in _CREATE_STATEMENTS:
            conn.execute(statement)
        try:
            conn.execute('CHECKPOINT')
        except Exception:
            pass
        _conn = conn


def insert_many(entries):
    """批量写入访问记录，entries 为 capture 层构造的字典列表。

    Returns:
        bool: 数据库未打开时返回 False，否则写入并返回 True。
    """
    if not entries:
        return True
    rows = [
        (
            e['id'], e['_ts'], e['ip'], e['method'], e['path'],
            e['query_string'], e['status'], e['duration_ms'],
            e['user_id'], e['username'], e['user_agent'], e['referer'],
        )
        for e in entries
    ]
    with _conn_lock:
        if _conn is None:
            return False
        _conn.executemany(_INSERT_SQL, rows)
    return True


def query_recent(limit):
    """读取最近 limit 条访问记录（按时间正序返回，供 SSE 历史快照）。"""
    with _conn_lock:
        if _conn is None:
            return []
        rows = _conn.execute(_SELECT_RECENT_SQL, (limit,)).fetchall()
    return [dict(zip(COLUMNS, row)) for row in reversed(rows)]


def db_size():
    """返回数据库文件（含 WAL）当前占用字节数。"""
    total = 0
    for suffix in ('', '.wal'):
        try:
            total += os.path.getsize(DB_PATH + suffix)
        except OSError:
            pass
    return total


def _close_locked():
    global _conn
    if _conn is None:
        return
    try:
        _conn.execute('CHECKPOINT')
    except Exception:
        pass
    try:
        _conn.close()
    except Exception:
        pass
    _conn = None


def close_store():
    """关闭数据库连接（不删除文件）。"""
    with _conn_lock:
        _close_locked()


def delete_store():
    """关闭连接并删除数据库文件（取消抓取时调用）。"""
    with _conn_lock:
        _close_locked()
        _remove_files()
