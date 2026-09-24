"""防火墙 DuckDB 引擎 —— 独立高性能数据库 + 内存缓存层。

设计原则：
  - DuckDB 文件数据库存放所有持久化数据
  - 内存缓存层提供 O(1) 热查询，每 1 秒由监控线程同步
  - 文件路径：db/firewall.duckdb，独立于主站 SQLite 数据库
  - 线程安全：连接锁 + 缓存读写锁分离
"""

import os
import queue
import threading
import time
from datetime import datetime

import duckdb

from core.system.logger import log

DB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'uploads', 'db',
)
DB_PATH = os.path.join(DB_DIR, 'firewall.duckdb')

_conn = None
_conn_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 单写入线程 + 写队列 —— 所有 DuckDB 写入统一由一个线程按顺序执行
#
# 设计目标（防锁 + 高性能）：
#   - 绝不允许多线程同时写入 DuckDB（DuckDB 单连接不支持并发写）
#   - 所有写操作进入 FIFO 队列，由唯一写入线程顺序执行
#   - 相邻的「即发即忘」写操作合并为一个事务批量提交，减少 I/O 次数
#   - 需要返回结果的写操作（如 INSERT ... RETURNING id）同步等待写入完成
# ---------------------------------------------------------------------------

_write_queue = queue.Queue()
_writer_thread = None
_writer_started = False
_writer_start_lock = threading.Lock()

# 批量提交上限：单次事务最多合并的写操作数
_WRITE_BATCH_MAX = 64
# 写入线程空闲等待时间（秒）：超时后强制刷新未提交的批量写
_WRITE_FLUSH_TIMEOUT = 0.5


def _start_writer():
    """惰性启动唯一写入线程（线程安全，仅启动一次）。"""
    global _writer_thread, _writer_started
    if _writer_started:
        return
    with _writer_start_lock:
        if _writer_started:
            return
        _writer_started = True
        _writer_thread = threading.Thread(
            target=_writer_loop, name='fw-writer', daemon=True,
        )
        _writer_thread.start()
        log('INFO', 'FirewallDB', '防火墙单写入线程已启动')


def _execute_batch(batch):
    """在连接锁保护下执行一批写操作（一个事务）并提交。"""
    conn = get_db()
    try:
        with conn:
            for sql, params in batch:
                if params is None:
                    conn.execute(sql)
                else:
                    conn.execute(sql, params)
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'批量写入失败: {exc}')
        raise


def _writer_loop():
    """唯一写入线程主循环：按顺序执行写队列，合并批量提交。"""
    pending = []  # [(sql, params), ...]

    def flush():
        if pending:
            batch = list(pending)
            pending.clear()
            _execute_batch(batch)

    while True:
        try:
            item = _write_queue.get(timeout=_WRITE_FLUSH_TIMEOUT)
        except queue.Empty:
            # 空闲：刷新未提交的批量写
            try:
                flush()
            except Exception:
                pending.clear()
            continue

        if item is None:  # 退出哨兵
            try:
                flush()
            except Exception:
                pass
            return

        sql, params, event, holder, fetch = item
        if event is not None:
            # 同步写：先提交已有批量，再单独执行并提交，最后通知等待者
            try:
                flush()
            except Exception:
                pass
            try:
                conn = get_db()
                with conn:
                    result = conn.execute(sql, params) if params is not None else conn.execute(sql)
                    if fetch == 'one':
                        holder['result'] = result.fetchone()
                    elif fetch == 'all':
                        holder['result'] = result.fetchall()
            except Exception as exc:
                holder['error'] = exc
            finally:
                event.set()
        else:
            # 即发即忘：加入批量
            pending.append((sql, params))
            if len(pending) >= _WRITE_BATCH_MAX:
                try:
                    flush()
                except Exception:
                    pending.clear()


def submit_write(sql, params=None):
    """提交一个「即发即忘」写操作（异步，不等待结果）。

    写操作由唯一写入线程按顺序执行，与相邻写操作合并提交。
    """
    _start_writer()
    _write_queue.put((sql, params, None, None, None))


def execute_write(sql, params=None, fetch=None, timeout=5.0):
    """提交一个写操作并同步等待其完成（用于需要返回值的写）。

    Args:
        sql: SQL 语句
        params: 参数（tuple/list/dict）
        fetch: None（不需要结果）/ 'one' / 'all'
        timeout: 最长等待秒数

    Returns:
        fetch 为 'one' 时返回单行（tuple），'all' 返回全部行；否则返回 True。
        失败时返回 None（并记录日志）。
    """
    _start_writer()
    event = threading.Event()
    holder = {}
    _write_queue.put((sql, params, event, holder, fetch))
    if not event.wait(timeout):
        log('WARNING', 'FirewallDB', '写入等待超时', sql=sql[:60])
        return None
    if holder.get('error') is not None:
        log('WARNING', 'FirewallDB', f'写入失败: {holder["error"]}', sql=sql[:60])
        return None
    if fetch in ('one', 'all'):
        return holder.get('result')
    return True


def flush_writes(timeout=5.0):
    """刷新写队列（等待所有已入队的写操作落盘），用于关闭前收尾。"""
    if not _writer_started:
        return
    done = threading.Event()
    _write_queue.put(('SELECT 1', None, done, {}, None))
    done.wait(timeout)


def stop_writer():
    """停止写入线程（尽力刷新后退出）。"""
    global _writer_started, _writer_thread
    if not _writer_started:
        return
    try:
        flush_writes()
    except Exception:
        pass
    _write_queue.put(None)
    _writer_started = False
    _writer_thread = None


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
    """内存缓存查询 IP 封禁状态。返回 (banned: bool, reason: str)。

    缓存尚未同步（如服务刚启动、监控线程未就绪）时主动同步一次，
    保证冷启动与测试环境下查询结果正确。
    """
    if _cache['banned_ips_ts'] == 0.0:
        sync_ip_bans_to_cache()
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
    if _cache['banned_accounts_ts'] == 0.0:
        sync_account_bans_to_cache()
    banned_map = _cache['banned_accounts']
    if user_id in banned_map:
        return True, banned_map[user_id]
    return False, ''


def is_whitelisted_cache(ip: str) -> bool:
    """内存缓存查询白名单状态。"""
    if _cache['whitelist_ts'] == 0.0:
        sync_whitelist_to_cache()
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
CREATE SEQUENCE IF NOT EXISTS seq_firewall_ban_details START 1;
CREATE SEQUENCE IF NOT EXISTS seq_firewall_content_injections START 1;

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

CREATE TABLE IF NOT EXISTS firewall_account_whitelist (
    user_id INTEGER PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note VARCHAR DEFAULT ''
);

CREATE TABLE IF NOT EXISTS firewall_ban_details (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_ban_details'),
    ban_id INTEGER NOT NULL,
    ban_type VARCHAR NOT NULL DEFAULT 'ip',
    ip_address VARCHAR DEFAULT '',
    reason TEXT DEFAULT '',
    banned_by INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    user_agent TEXT DEFAULT '',
    request_path TEXT DEFAULT '',
    request_method VARCHAR DEFAULT '',
    referer TEXT DEFAULT '',
    attack_type VARCHAR DEFAULT '',
    matched_text TEXT DEFAULT '',
    action_source VARCHAR DEFAULT 'manual',
    request_headers TEXT DEFAULT '',
    query_string TEXT DEFAULT '',
    request_body_preview TEXT DEFAULT '',
    action_ip VARCHAR DEFAULT '',
    action_username VARCHAR DEFAULT '',
    additional_info TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ban_details_ban_id ON firewall_ban_details(ban_id);
CREATE INDEX IF NOT EXISTS idx_ban_details_created ON firewall_ban_details(created_at);

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

CREATE TABLE IF NOT EXISTS firewall_content_injections (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_firewall_content_injections'),
    user_id INTEGER NOT NULL,
    content_type VARCHAR NOT NULL DEFAULT '',
    injection_type VARCHAR NOT NULL DEFAULT '',
    content_preview VARCHAR DEFAULT '',
    ip_address VARCHAR DEFAULT '',
    matched_pattern VARCHAR DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_content_inj_user ON firewall_content_injections(user_id);
CREATE INDEX IF NOT EXISTS idx_content_inj_time ON firewall_content_injections(created_at);
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


# ---------------------------------------------------------------------------
# 过期时间堆 —— 按时间排序，逐个清理，避免全表扫描
# ---------------------------------------------------------------------------

import heapq

_expiry_heap = []
_expiry_heap_lock = threading.Lock()


def push_expiry(expires_at_str: str, ban_type: str, ban_id: int):
    """将封禁的过期时间推入堆。

    Args:
        expires_at_str: DuckDB CURRENT_TIMESTAMP 格式字符串 'YYYY-MM-DD HH:MM:SS'
        ban_type: 'ip' 或 'account'
        ban_id: 对应封禁表的 id
    """
    if not expires_at_str:
        return
    try:
        # 解析为时间戳（秒）
        dt = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
        ts = dt.timestamp()
        with _expiry_heap_lock:
            heapq.heappush(_expiry_heap, (ts, ban_type, ban_id))
    except (ValueError, TypeError):
        pass


def pop_expired(now_ts: float = None) -> list:
    """弹出所有已过期的堆条目。

    Returns:
        list of (ts, ban_type, ban_id) — 所有已过期的条目
    """
    if now_ts is None:
        now_ts = time.time()
    expired = []
    with _expiry_heap_lock:
        while _expiry_heap and _expiry_heap[0][0] <= now_ts:
            expired.append(heapq.heappop(_expiry_heap))
    return expired


def load_expiry_heap():
    """启动时从 DuckDB 重建过期堆。"""
    global _expiry_heap
    try:
        heap = []
        with get_db() as conn:
            # IP bans
            rows = conn.execute(
                "SELECT id, expires_at FROM firewall_bans "
                "WHERE expires_at IS NOT NULL"
            ).fetchall()
            for row in rows:
                bid, expires = row
                if expires:
                    try:
                        dt = datetime.strptime(str(expires), '%Y-%m-%d %H:%M:%S')
                        heap.append((dt.timestamp(), 'ip', bid))
                    except ValueError:
                        pass
        with _expiry_heap_lock:
            _expiry_heap = heap
            heapq.heapify(_expiry_heap)
        log('INFO', 'FirewallDB', f'过期堆已重建，共 {len(heap)} 条目')
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'重建过期堆失败: {exc}')


def remove_from_expiry_heap(ban_type: str, ban_id: int):
    """从过期堆中移除指定条目（惰性过滤：标记删除由 monitor 过滤）。

    由于 heap 不支持常规删除，采用惰性方式：在清理时检查记录是否仍有效。
    此函数保留用于 future 优化。
    """
    pass  # 惰性处理：实际删除由 _cleanup_expired_bans 在查询时验证


# ---------------------------------------------------------------------------
# 封禁详情记录 —— 自动记录每次封禁的完整上下文
# ---------------------------------------------------------------------------

# 线程本地存储：用于从 WSGI 层传递封禁上下文到 service 层
_thread_ban_ctx = threading.local()


def push_ban_context(**kwargs):
    """将封禁上下文推入当前线程（由 WSGI 门禁/DDoS 检测器在封禁前调用）。

    不需要额外参数的模块无需感知此函数，记录由 ban_ip/ban_account 自动完成。
    """
    ctx = getattr(_thread_ban_ctx, 'context', {})
    ctx.update({k: v for k, v in kwargs.items() if v})
    _thread_ban_ctx.context = ctx


def pop_ban_context():
    """弹出并返回当前线程的封禁上下文。"""
    ctx = getattr(_thread_ban_ctx, 'context', {})
    if ctx:
        _thread_ban_ctx.context = {}
    return ctx


def record_ban_detail(
    ban_id, ban_type='ip', ip_address='', reason='', banned_by=0,
    created_at=None, expires_at=None,
    **extra
):
    """记录封禁详细信息到 firewall_ban_details 表。

    结合自动收集的请求上下文（push_ban_context 传入 + 自动采集）和显式参数。
    失败不影响主封禁流程。

    Args:
        ban_id: 封禁记录 ID
        ban_type: 'ip' 或 'account'
        ip_address: 被封 IP
        reason: 封禁原因
        banned_by: 操作人 ID
        created_at: 封禁创建时间
        expires_at: 过期时间
        extra: 额外的 key=value 存入 additional_info JSON
    """
    # 从线程本地收集上下文（WSGI/DDOS 层推入的请求信息）
    thread_ctx = pop_ban_context()
    # 尝试从 Flask 请求上下文自动收集
    try:
        from flask import request as _flask_req
        if _flask_req:
            thread_ctx.setdefault('user_agent', _flask_req.headers.get('User-Agent', ''))
            thread_ctx.setdefault('request_path', _flask_req.path)
            thread_ctx.setdefault('request_method', _flask_req.method)
            thread_ctx.setdefault('referer', _flask_req.headers.get('Referer', ''))
            thread_ctx.setdefault('action_ip', _flask_req.remote_addr or '')
            qs = _flask_req.query_string
            if qs:
                thread_ctx.setdefault('query_string', qs.decode('utf-8', 'ignore'))
            try:
                from flask import session
                thread_ctx.setdefault('action_username', session.get('username', ''))
            except Exception:
                pass
            try:
                import json
                hdrs = {}
                for k, v in _flask_req.headers:
                    if len(json.dumps(hdrs)) > 3000:
                        break
                    hdrs[k] = v
                thread_ctx.setdefault('request_headers', json.dumps(hdrs, ensure_ascii=False))
            except Exception:
                pass
    except (RuntimeError, Exception):
        pass  # 不在请求上下文中

    # 构造 SQL 参数
    detail_kwargs = {
        'ban_id': ban_id,
        'ban_type': ban_type,
        'ip_address': ip_address or '',
        'reason': reason or '',
        'banned_by': banned_by or 0,
        'created_at': created_at or time.strftime('%Y-%m-%d %H:%M:%S'),
        'expires_at': expires_at,
        'user_agent': thread_ctx.get('user_agent', ''),
        'request_path': thread_ctx.get('request_path', ''),
        'request_method': thread_ctx.get('request_method', ''),
        'referer': thread_ctx.get('referer', ''),
        'attack_type': thread_ctx.get('attack_type', ''),
        'matched_text': thread_ctx.get('matched_text', ''),
        'action_source': thread_ctx.get('action_source', ''),
        'request_headers': thread_ctx.get('request_headers', ''),
        'query_string': thread_ctx.get('query_string', ''),
        'request_body_preview': thread_ctx.get('request_body_preview', ''),
        'action_ip': thread_ctx.get('action_ip', ''),
        'action_username': thread_ctx.get('action_username', ''),
    }
    # additional_info：将 extra 参数及其它额外信息存为 JSON
    try:
        import json as _json
        extra_json = {}
        if extra:
            extra_json.update(extra)
        # 把 thread_ctx 中未映射到列的字段也存进去
        for k, v in thread_ctx.items():
            if k not in detail_kwargs:
                extra_json[k] = str(v)[:500]
        detail_kwargs['additional_info'] = _json.dumps(extra_json, ensure_ascii=False)
    except Exception:
        detail_kwargs['additional_info'] = ''

    try:
        submit_write(
            "INSERT INTO firewall_ban_details "
            "(ban_id, ban_type, ip_address, reason, banned_by, "
            " created_at, expires_at, "
            " user_agent, request_path, request_method, referer, "
            " attack_type, matched_text, action_source, "
            " request_headers, query_string, request_body_preview, "
            " action_ip, action_username, additional_info) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                detail_kwargs['ban_id'],
                detail_kwargs['ban_type'],
                detail_kwargs['ip_address'],
                detail_kwargs['reason'],
                detail_kwargs['banned_by'],
                detail_kwargs['created_at'],
                detail_kwargs['expires_at'],
                detail_kwargs['user_agent'],
                detail_kwargs['request_path'],
                detail_kwargs['request_method'],
                detail_kwargs['referer'],
                detail_kwargs['attack_type'],
                detail_kwargs['matched_text'],
                detail_kwargs['action_source'],
                detail_kwargs['request_headers'],
                detail_kwargs['query_string'],
                detail_kwargs['request_body_preview'],
                detail_kwargs['action_ip'],
                detail_kwargs['action_username'],
                detail_kwargs['additional_info'],
            ),
        )
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'记录封禁详情失败: {exc}', ban_id=ban_id)


def get_ban_detail(ban_id):
    """查询单条封禁的详细信息。

    Args:
        ban_id: 封禁记录 ID

    Returns:
        dict | None: 封禁详情，含所有字段
    """
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id, ban_id, ban_type, ip_address, reason, banned_by, "
                "       strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at, "
                "       CASE WHEN expires_at IS NULL THEN NULL "
                "            ELSE strftime('%Y-%m-%d %H:%M:%S', expires_at) "
                "       END AS expires_at, "
                "       user_agent, request_path, request_method, referer, "
                "       attack_type, matched_text, action_source, "
                "       request_headers, query_string, request_body_preview, "
                "       action_ip, action_username, additional_info "
                "FROM firewall_ban_details "
                "WHERE ban_id = ? ORDER BY id DESC LIMIT 1",
                (ban_id,),
            ).fetchone()
            if not row:
                return None
            return {
                'id': row[0], 'ban_id': row[1], 'ban_type': row[2],
                'ip_address': row[3], 'reason': row[4],
                'banned_by': row[5], 'created_at': row[6], 'expires_at': row[7],
                'user_agent': row[8], 'request_path': row[9],
                'request_method': row[10], 'referer': row[11],
                'attack_type': row[12], 'matched_text': row[13],
                'action_source': row[14], 'request_headers': row[15],
                'query_string': row[16], 'request_body_preview': row[17],
                'action_ip': row[18], 'action_username': row[19],
                'additional_info': row[20],
            }
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'查询封禁详情失败: {exc}', ban_id=ban_id)
        return None


# ---------------------------------------------------------------------------
# 账号白名单管理
# ---------------------------------------------------------------------------


def get_account_whitelist_db():
    """从 DuckDB 查询账号白名单。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT user_id, strftime('%Y-%m-%d %H:%M:%S', created_at) AS created_at, note "
                "FROM firewall_account_whitelist ORDER BY created_at DESC"
            ).fetchall()
            return [
                {'user_id': r[0], 'created_at': r[1], 'note': r[2]}
                for r in rows
            ]
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'查询账号白名单失败: {exc}')
        return []


def is_account_whitelisted_db(user_id):
    """检查账号是否在白名单中。"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT 1 FROM firewall_account_whitelist WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row is not None
    except Exception:
        return False


def whitelist_account_db(user_id, note=''):
    """添加账号白名单。"""
    return execute_write(
        "INSERT INTO firewall_account_whitelist (user_id, note) VALUES (?, ?)",
        (user_id, note),
    ) is not None


def unwhitelist_account_db(user_id):
    """移除账号白名单。"""
    return execute_write(
        "DELETE FROM firewall_account_whitelist WHERE user_id = ?",
        (user_id,),
    ) is not None


# ---------------------------------------------------------------------------
# 发布内容注入记录
# ---------------------------------------------------------------------------

INJECTION_WARNING_LIMIT = 2  # 2 次注入警告后自动封禁
INJECTION_WARNING_WINDOW_HOURS = 24


def record_content_injection(user_id, content_type, injection_type, content_preview, ip_address, matched_pattern):
    """记录一次发布内容注入警告到 DuckDB。

    Returns:
        int: 用户在该时间窗口内的总注入警告次数
    """
    try:
        execute_write(
            "INSERT INTO firewall_content_injections "
            "(user_id, content_type, injection_type, content_preview, ip_address, matched_pattern, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, content_type, injection_type, content_preview[:200], ip_address, matched_pattern),
        )
    except Exception as exc:
        log('WARNING', 'FirewallDB', f'记录内容注入警告失败: {exc}', user_id=user_id)
    return get_user_injection_count(user_id, INJECTION_WARNING_WINDOW_HOURS)


def get_user_injection_count(user_id, hours=INJECTION_WARNING_WINDOW_HOURS):
    """获取用户在指定小时内注入警告次数。"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM firewall_content_injections "
                "WHERE user_id = ? AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{} hours'".format(hours),
                (user_id,),
            ).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0