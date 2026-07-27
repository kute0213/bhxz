"""数据库连接层 —— DuckDB 连接、游标、行对象的兼容封装。

由于 DuckDB 在 Windows 上多进程/多连接文件锁问题较严重，
这里采用单例共享连接 + 线程锁的方式，确保同一时间只有一个线程在写数据库。
"""

import duckdb
import threading

from config import DB_PATH


# ---------------------------------------------------------------------------
# DuckDB Row 兼容类：模拟 sqlite3.Row 的行为（支持 keys()、[] 访问）
# ---------------------------------------------------------------------------

class DuckDBRow:
    """模拟 sqlite3.Row 的只读行对象。"""

    __slots__ = ('_keys', '_values')

    def __init__(self, description, values):
        self._keys = tuple(d[0] for d in description)
        self._values = tuple(values)

    def keys(self):
        return list(self._keys)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                idx = self._keys.index(key)
            except ValueError:
                raise KeyError(key)
            return self._values[idx]
        if isinstance(key, int):
            return self._values[key]
        if isinstance(key, slice):
            return self._values[key]
        raise TypeError(f'Invalid key type: {type(key)}')

    def __contains__(self, key):
        return key in self._keys

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._keys)

    def __repr__(self):
        return f'DuckDBRow({dict(zip(self._keys, self._values))})'


# ---------------------------------------------------------------------------
# DuckDB 游标兼容类：模拟 sqlite3.Cursor 的行为
# ---------------------------------------------------------------------------

class DuckDBCursor:
    """模拟 sqlite3.Cursor 的游标对象。"""

    def __init__(self, conn):
        self._conn = conn
        self._duckdb_conn = conn._duckdb_conn
        self._lastrowid = None
        self._rowcount = -1
        self._result = None       # 当前执行结果 (DuckDB PyResult)
        self.description = None   # 列描述符

    def execute(self, sql, params=None):
        """执行单条 SQL 语句。"""
        if params is None:
            result = self._duckdb_conn.execute(sql)
        else:
            result = self._duckdb_conn.execute(sql, list(params))
        self._result = result
        self.description = result.description
        self._rowcount = result.rowcount if hasattr(result, 'rowcount') else -1

        # 检测 INSERT 语句，尝试获取 lastrowid
        sql_stripped = sql.strip().upper()
        if sql_stripped.startswith('INSERT INTO'):
            try:
                parts = sql_stripped.split()
                if len(parts) >= 3:
                    table_name = parts[2].strip('`"[]')
                    seq_name = f'{table_name}_id_seq'
                    try:
                        row = self._duckdb_conn.execute(
                            f"SELECT currval('{seq_name}')"
                        ).fetchone()
                        if row and row[0] is not None:
                            self._lastrowid = int(row[0])
                    except Exception:
                        try:
                            row = self._duckdb_conn.execute(
                                f'SELECT MAX(id) FROM {table_name}'
                            ).fetchone()
                            if row and row[0] is not None:
                                self._lastrowid = int(row[0])
                        except Exception:
                            self._lastrowid = None
            except Exception:
                self._lastrowid = None
        else:
            self._lastrowid = None

        return self

    def executemany(self, sql, seq_of_params):
        """批量执行。"""
        self._duckdb_conn.executemany(sql, [list(p) for p in seq_of_params])
        self._result = None
        self.description = None
        self._lastrowid = None
        self._rowcount = -1
        return self

    def fetchone(self):
        if self._result is None:
            return None
        row = self._result.fetchone()
        if row is None:
            return None
        if self._conn._row_factory is not None:
            return self._conn._row_factory(self.description, row)
        return row

    def fetchall(self):
        if self._result is None:
            return []
        rows = self._result.fetchall()
        if self._conn._row_factory is not None:
            return [self._conn._row_factory(self.description, r) for r in rows]
        return rows

    def fetchmany(self, size=None):
        if self._result is None:
            return []
        if size is None:
            size = 1
        rows = self._result.fetchmany(size)
        if self._conn._row_factory is not None:
            return [self._conn._row_factory(self.description, r) for r in rows]
        return rows

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._rowcount

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


# ---------------------------------------------------------------------------
# DuckDB 连接兼容类：模拟 sqlite3.Connection 的行为
# ---------------------------------------------------------------------------

class DuckDBConnection:
    """模拟 sqlite3.Connection 的连接对象。"""

    def __init__(self, path):
        self._path = path
        self._duckdb_conn = duckdb.connect(database=path, read_only=False)
        self._row_factory = None
        self._cursor = DuckDBCursor(self)

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        if value is None:
            self._row_factory = None
        else:
            self._row_factory = value

    def cursor(self):
        return self._cursor

    def execute(self, sql, params=None):
        return self._cursor.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self._cursor.executemany(sql, seq_of_params)

    def executescript(self, script):
        """执行多条 SQL 语句（用 ; 分隔）。"""
        statements = _split_sql_script(script)
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                self._duckdb_conn.execute(stmt)
        return self._cursor

    def commit(self):
        try:
            self._duckdb_conn.commit()
        except Exception as e:
            try:
                self._duckdb_conn.rollback()
            except Exception:
                pass
            raise

    def rollback(self):
        try:
            self._duckdb_conn.rollback()
        except Exception:
            pass

    def close(self):
        # 单例连接不真正关闭，由应用退出时统一处理
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 单例连接不关闭，只做一次 commit
        try:
            self.commit()
        except Exception:
            pass
        return False


def _row_factory_duckdbrow(description, values):
    return DuckDBRow(description, values)


def _split_sql_script(script):
    """简单的 SQL 脚本分割（按分号分割，忽略字符串内的分号）。"""
    statements = []
    current = []
    in_single = False
    in_double = False
    for ch in script:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ';' and not in_single and not in_double:
            statements.append(''.join(current))
            current = []
            continue
        current.append(ch)
    if current:
        statements.append(''.join(current))
    return statements


# ---------------------------------------------------------------------------
# 单例连接 + 线程锁（解决 Windows 文件占用问题）
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
    """
    global _conn
    if _conn is None:
        with _init_lock:
            if _conn is None:
                _conn = DuckDBConnection(DB_PATH)
                _conn.row_factory = _row_factory_duckdbrow
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
        return self._inner.cursor()

    @property
    def row_factory(self):
        return self._inner.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._inner.row_factory = value
