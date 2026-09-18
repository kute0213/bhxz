"""防火墙 DuckDB 引擎 —— 独立高性能数据库 + 内存缓存层。

设计原则：
  - DuckDB 文件数据库存放所有持久化数据
  - 内存缓存层提供 O(1) 热查询，每 1 秒由监控线程同步
  - 文件路径：db/firewall.duckdb，独立于主站 SQLite 数据库
  - 线程安全：连接锁 + 缓存读写锁分离
"""

import os
import threading
import time

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
# 内存缓存 —— 所有防火墙热路径查询走此缓存，避免每秒查 DuckDB
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache = {
    'banned_ips': {},           # {ip: reason}
    'banned_ips_ts': 0.0,      # 上次同步时间戳
    'banned_accounts': {},      # {user_id: reason}
    'banned_accounts_ts': 0.0,
    'whitelist': set(),         # {ip, ...}
    'whitelist_ts': 0.0,
}


def invalidate_cache():
    """使所有内存缓存失效（下次访问时强制重载）。"""
    with _cache_lock:
        _cache['banned_ips_ts'] = 0.0
        _cache['banned_accounts_ts'] = 0.0
        _cache['whitelist_ts'] = 0.0


def invalidate_ip_cache():
    with _cache_lock:
        _cache['banned_ips_ts'] = 0.0


def invalidate_account_cache():
    with _cache_lock:
        _cache['banned_accounts_ts'] = 0.0


def invalidate_whitelist_cache():
    with _cache_lock:
        _cache['whitelist_ts'] = 0.0


def sync_ip_bans_to_cache():
    """从 DuckDB 同步有效 IP 封禁到内存缓存。"""
    try:
        banned = {}
        safe = {'127.0.0.1', '::1', 'localhost'}
        with get_db() as conn:
            rows = conn.execute(
                "SELECT ip_address, reason FROM firewall_bans "
                "WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP"
            ).fetchall()
        for row in rows:
            if row[0] not in safe:
                banned[row[0]] = row[1] or ''
        with _cache_lock:
            _cache['banned_ips'] = banned
            _cache['banned_ips_ts'] = time.monotonic()
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'同步 IP 封禁缓存失败: {exc}')


def sync_account_bans_to_cache():
    """从 DuckDB 同步有效账号封禁到内存缓存。"""
    try:
        banned = {}
        with get_db() as conn:
            rows = conn.execute(
                "SELECT user_id, reason FROM firewall_account_bans "
                "WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP"
            ).fetchall()
        for row in rows:
            banned[row[0]] = row[1] or ''
        with _cache_lock:
            _cache['banned_accounts'] = banned
            _cache['banned_accounts_ts'] = time.monotonic()
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'同步账号封禁缓存失败: {exc}')


def sync_whitelist_to_cache():
    """从 config.py 和 DuckDB 同步白名单到内存缓存。"""
    try:
        from config import FIREWALL_WHITELIST as CONFIG_WHITELIST
        safe = {'127.0.0.1', '::1', 'localhost'}
        whitelist = set(safe)
        whitelist.update(CONFIG_WHITELIST)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT ip_address FROM firewall_whitelist"
            ).fetchall()
        for row in rows:
            whitelist.add(row[0])
        with _cache_lock:
            _cache['whitelist'] = whitelist
            _cache['whitelist_ts'] = time.monotonic()
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'同步白名单缓存失败: {exc}')


def sync_all_to_cache():
    """一次同步所有缓存（供监控线程每秒调用）。"""
    sync_ip_bans_to_cache()
    sync_account_bans_to_cache()
    sync_whitelist_to_cache()


def is_ip_banned_cache(ip: str) -> tuple:
    """内存缓存查询 IP 封禁状态。返回 (banned: bool, reason: str)。"""
    banned_map = _cache['banned_ips']
    if ip in banned_map:
        return True, banned_map[ip]
    # CIDR 匹配（如 192.168.0.0/24）
    for banned_ip, reason in banned_map.items():
        if '/' in banned_ip:
            try:
                import ipaddress
                if ipaddress.ip_address(ip) in ipaddress.ip_network(banned_ip, strict=False):
                    return True, reason
            except ValueError:
                pass
    return False, ''


def is_account_banned_cache(user_id: int) -> tuple:
    """内存缓存查询账号封禁状态。返回 (banned: bool, reason: str)。"""
    banned_map = _cache['banned_accounts']
    if user_id in banned_map:
        return True, banned_map[user_id]
    return False, ''


def is_whitelisted_cache(ip: str) -> bool:
    """内存缓存查询白名单状态。"""
    return ip in _cache['whitelist']

# ---------------------------------------------------------------------------
# DDL：建表语句（DuckDB 语法）
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = r"""
CREATE SEQUENCE IF NOT EXISTS seq_firewall_bans START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_account_bans START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_warnings START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_ddos_log START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_spam_log START 1;

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

CREATE TABLE IF NOT EXISTS firewall_account_bans (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_account_bans'),
    user_id INTEGER NOT NULL,
    reason VARCHAR DEFAULT '',
    banned_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_firewall_account_bans_user ON firewall_account_bans(user_id);
CREATE INDEX IF NOT EXISTS idx_firewall_account_bans_expires ON firewall_account_bans(expires_at);

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

CREATE TABLE IF NOT EXISTS firewall_spam_log (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_spam_log'),
    user_id INTEGER NOT NULL,
    content_type VARCHAR NOT NULL,
    content_preview VARCHAR DEFAULT '',
    action VARCHAR NOT NULL DEFAULT 'flag',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_firewall_spam_log_user ON firewall_spam_log(user_id);
CREATE INDEX IF NOT EXISTS idx_firewall_spam_log_time ON firewall_spam_log(created_at);

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
    """线程安全的 DuckDB 连接包装器。"""

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
                log('INFO', 'FirewallDB', '防火墙数据库初始化完成', path=DB_PATH)
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