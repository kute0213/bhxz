"""防火墙 DuckDB 引擎 —— 独立高性能数据库。

设计原则：
  - 使用 DuckDB 文件数据库存放所有防火墙数据
  - 独立于主站 SQLite 数据库，互不影响
  - 文件路径：db/firewall.duckdb
  - 线程安全：锁保护围绕「with get_db()」上下文，每个 with 块串行化
  - 自动建表：首次使用时创建
"""

import os
import threading

import duckdb

from core.system.logger import log

DB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'db',
)
DB_PATH = os.path.join(DB_DIR, 'firewall.duckdb')

_conn = None
_conn_lock = threading.Lock()

# ---------------------------------------------------------------------------
# DDL：建表语句（DuckDB 语法）
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = r"""
CREATE SEQUENCE IF NOT EXISTS seq_firewall_bans START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_warnings START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_ddos_log START 1;

CREATE TABLE IF NOT EXISTS firewall_bans (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_bans'),
    ip_address VARCHAR NOT NULL,
    reason VARCHAR DEFAULT '',
    banned_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_firewall_bans_ip ON firewall_bans(ip_address);
CREATE INDEX IF NOT EXISTS idx_firewall_bans_expires ON firewall_bans(expires_at);

CREATE TABLE IF NOT EXISTS firewall_whitelist (
    ip_address VARCHAR PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS firewall_warnings (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_warnings'),
    ip_address VARCHAR NOT NULL,
    warning TEXT DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_firewall_warnings_ip ON firewall_warnings(ip_address);
CREATE INDEX IF NOT EXISTS idx_firewall_warnings_time ON firewall_warnings(created_at);

CREATE TABLE IF NOT EXISTS firewall_ddos_log (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_ddos_log'),
    ip_address VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    threshold INTEGER DEFAULT 0,
    count INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_firewall_ddos_time ON firewall_ddos_log(created_at);

CREATE TABLE IF NOT EXISTS firewall_config (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_dir():
    os.makedirs(DB_DIR, exist_ok=True)


class _DuckDBConnection:
    """线程安全的 DuckDB 连接包装器。

    锁在整个 with 块期间持有，确保每次只有一个线程操作 DuckDB。
    DuckDB 是单写者模型，这种模式最安全。
    """

    def __init__(self, conn, lock):
        self._conn = conn
        self._lock = lock

    def execute(self, sql, params=None):
        if params is not None:
            if isinstance(params, (list, tuple)):
                return self._conn.execute(sql, params)
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def fetchall(self):
        return self._conn.fetchall()

    def fetchone(self):
        return self._conn.fetchone()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._conn.commit()
        finally:
            self._lock.release()


def get_db():
    """获取线程安全的 DuckDB 连接包装器。

    用法：
        with get_db() as conn:
            conn.execute('INSERT INTO ...')
            rows = conn.execute('SELECT ...').fetchall()
    """
    global _conn
    if _conn is None:
        with _conn_lock:
            if _conn is None:
                _ensure_dir()
                _conn = duckdb.connect(DB_PATH)
                _conn.execute("SET threads TO 2")
                _conn.execute("SET memory_limit = '256MB'")
                for stmt in CREATE_TABLES_SQL.split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            _conn.execute(stmt + ';')
                        except Exception as e:
                            log('WARNING', 'FirewallDB', f'建表警告: {e}')
                log('INFO', 'FirewallDB', '防火墙数据库初始化完成',
                    path=DB_PATH)
    return _DuckDBConnection(_conn, _conn_lock)


def close_db():
    """关闭 DuckDB 连接。"""
    global _conn
    with _conn_lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None


def vacuum():
    """回收 DuckDB 存储空间。"""
    try:
        with get_db() as conn:
            conn.execute("VACUUM;")
        return True
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'VACUUM 失败: {exc}')
        return False