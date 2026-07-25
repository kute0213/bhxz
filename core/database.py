"""数据库访问层 —— 基于 DuckDB 实现，提供类 sqlite3 兼容接口。

主要改动：
- 使用 DuckDB 替换 SQLite，性能更高，支持窗口函数、列存等高级特性
- 封装 DuckDBConnection 提供与 sqlite3 相似的接口（row_factory、lastrowid、commit/close 等）
- 使用 SEQUENCE + nextval 模拟 AUTOINCREMENT，INSERT 后通过 currval / MAX(id) 获取 lastrowid
- 每个 get_db() 调用返回独立连接（DuckDB 多连接安全，支持 WAL 模式）
"""

import os
import hashlib
from datetime import datetime

import duckdb

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
            # 从 INSERT 语句中提取表名
            try:
                # INSERT INTO table_name ...
                parts = sql_stripped.split()
                if len(parts) >= 3:
                    table_name = parts[2].strip('`"[]')
                    # 尝试通过序列获取 last id
                    seq_name = f'{table_name}_id_seq'
                    try:
                        row = self._duckdb_conn.execute(
                            f"SELECT currval('{seq_name}')"
                        ).fetchone()
                        if row and row[0] is not None:
                            self._lastrowid = int(row[0])
                    except Exception:
                        # 没有序列的表，用 MAX(id)
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
        # DuckDB 默认启用外键约束，但不支持 ON DELETE CASCADE
        # 级联删除由应用层代码负责处理

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        if value is None:
            self._row_factory = None
        else:
            # DuckDBRow 构造器是 (description, values)
            self._row_factory = value

    def cursor(self):
        return self._cursor

    def execute(self, sql, params=None):
        return self._cursor.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self._cursor.executemany(sql, seq_of_params)

    def executescript(self, script):
        """执行多条 SQL 语句（用 ; 分隔）。"""
        # DuckDB 不直接支持 executescript，逐条执行
        statements = _split_sql_script(script)
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                self._duckdb_conn.execute(stmt)
        return self._cursor

    def commit(self):
        try:
            self._duckdb_conn.commit()
        except Exception:
            # DuckDB 自动提交模式下可能不需要显式 commit
            pass

    def rollback(self):
        try:
            self._duckdb_conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._duckdb_conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
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
# 公共 API
# ---------------------------------------------------------------------------

def get_db():
    """获取数据库连接（独立连接，带行工厂）。

    DuckDB 支持多连接并发访问，每次调用返回独立连接。
    """
    conn = DuckDBConnection(DB_PATH)
    conn.row_factory = _row_factory_duckdbrow
    return conn


# ---------------------------------------------------------------------------
# 数据库初始化（建表 + 默认数据）
# ---------------------------------------------------------------------------

def init_db():
    """初始化数据库结构和默认数据。"""
    conn = get_db()
    cursor = conn.cursor()

    # 为每张表创建 SEQUENCE 和表结构（DuckDB 用 SEQUENCE 模拟 AUTOINCREMENT）
    tables = [
        ('users', '''
            CREATE SEQUENCE IF NOT EXISTS users_id_seq START 1;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY DEFAULT nextval('users_id_seq'),
                username VARCHAR UNIQUE NOT NULL,
                password_hash VARCHAR NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('mod_intros', '''
            CREATE SEQUENCE IF NOT EXISTS mod_intros_id_seq START 1;
            CREATE TABLE IF NOT EXISTS mod_intros (
                id INTEGER PRIMARY KEY DEFAULT nextval('mod_intros_id_seq'),
                icon VARCHAR NOT NULL DEFAULT 'box',
                title VARCHAR NOT NULL,
                content VARCHAR NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('polls', '''
            CREATE SEQUENCE IF NOT EXISTS polls_id_seq START 1;
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY DEFAULT nextval('polls_id_seq'),
                title VARCHAR NOT NULL,
                description VARCHAR,
                is_active INTEGER DEFAULT 1,
                is_multiple INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('poll_options', '''
            CREATE SEQUENCE IF NOT EXISTS poll_options_id_seq START 1;
            CREATE TABLE IF NOT EXISTS poll_options (
                id INTEGER PRIMARY KEY DEFAULT nextval('poll_options_id_seq'),
                poll_id INTEGER NOT NULL,
                option_text VARCHAR NOT NULL,
                vote_count INTEGER DEFAULT 0
            )
        '''),
        ('poll_votes', '''
            CREATE SEQUENCE IF NOT EXISTS poll_votes_id_seq START 1;
            CREATE TABLE IF NOT EXISTS poll_votes (
                id INTEGER PRIMARY KEY DEFAULT nextval('poll_votes_id_seq'),
                poll_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                option_id INTEGER NOT NULL,
                created_at VARCHAR NOT NULL,
                UNIQUE(poll_id, user_id, option_id)
            )
        '''),
        ('board_topics', '''
            CREATE SEQUENCE IF NOT EXISTS board_topics_id_seq START 1;
            CREATE TABLE IF NOT EXISTS board_topics (
                id INTEGER PRIMARY KEY DEFAULT nextval('board_topics_id_seq'),
                user_id INTEGER NOT NULL,
                title VARCHAR NOT NULL,
                description VARCHAR,
                is_active INTEGER DEFAULT 1,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('board_replies', '''
            CREATE SEQUENCE IF NOT EXISTS board_replies_id_seq START 1;
            CREATE TABLE IF NOT EXISTS board_replies (
                id INTEGER PRIMARY KEY DEFAULT nextval('board_replies_id_seq'),
                topic_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('access_logs', '''
            CREATE SEQUENCE IF NOT EXISTS access_logs_id_seq START 1;
            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY DEFAULT nextval('access_logs_id_seq'),
                ip_address VARCHAR NOT NULL,
                country VARCHAR,
                region VARCHAR,
                city VARCHAR,
                isp VARCHAR,
                user_id INTEGER,
                username VARCHAR,
                path VARCHAR NOT NULL,
                method VARCHAR NOT NULL,
                user_agent VARCHAR,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('cmd_commands', '''
            CREATE SEQUENCE IF NOT EXISTS cmd_commands_id_seq START 1;
            CREATE TABLE IF NOT EXISTS cmd_commands (
                id INTEGER PRIMARY KEY DEFAULT nextval('cmd_commands_id_seq'),
                name VARCHAR NOT NULL,
                command VARCHAR NOT NULL,
                description VARCHAR DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL,
                type VARCHAR DEFAULT 'cmd'
            )
        '''),
        ('scheduled_tasks', '''
            CREATE SEQUENCE IF NOT EXISTS scheduled_tasks_id_seq START 1;
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY DEFAULT nextval('scheduled_tasks_id_seq'),
                name VARCHAR NOT NULL,
                command VARCHAR NOT NULL,
                schedule_type VARCHAR NOT NULL DEFAULT 'interval',
                interval_seconds INTEGER DEFAULT 3600,
                execute_at VARCHAR,
                is_enabled INTEGER DEFAULT 1,
                last_run_at VARCHAR,
                next_run_at VARCHAR,
                run_count INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL
            )
        '''),
        ('scheduled_task_logs', '''
            CREATE SEQUENCE IF NOT EXISTS scheduled_task_logs_id_seq START 1;
            CREATE TABLE IF NOT EXISTS scheduled_task_logs (
                id INTEGER PRIMARY KEY DEFAULT nextval('scheduled_task_logs_id_seq'),
                task_id INTEGER,
                task_name VARCHAR,
                command VARCHAR,
                output VARCHAR DEFAULT '',
                exit_code INTEGER,
                success INTEGER DEFAULT 0,
                started_at VARCHAR NOT NULL,
                finished_at VARCHAR,
                duration_seconds DOUBLE DEFAULT 0
            )
        '''),
        ('cmd_run_logs', '''
            CREATE SEQUENCE IF NOT EXISTS cmd_run_logs_id_seq START 1;
            CREATE TABLE IF NOT EXISTS cmd_run_logs (
                id INTEGER PRIMARY KEY DEFAULT nextval('cmd_run_logs_id_seq'),
                command VARCHAR NOT NULL,
                output VARCHAR DEFAULT '',
                exit_code INTEGER,
                success INTEGER DEFAULT 0,
                triggered_by VARCHAR DEFAULT 'manual',
                started_at VARCHAR NOT NULL,
                finished_at VARCHAR,
                duration_seconds DOUBLE DEFAULT 0
            )
        '''),
        # 数据库备份记录表
        ('db_backups', '''
            CREATE SEQUENCE IF NOT EXISTS db_backups_id_seq START 1;
            CREATE TABLE IF NOT EXISTS db_backups (
                id INTEGER PRIMARY KEY DEFAULT nextval('db_backups_id_seq'),
                backup_name VARCHAR NOT NULL,
                backup_path VARCHAR NOT NULL,
                backup_type VARCHAR NOT NULL DEFAULT 'scheduled',
                status VARCHAR NOT NULL DEFAULT 'running',
                size_bytes BIGINT DEFAULT 0,
                error_message VARCHAR,
                started_at VARCHAR NOT NULL,
                finished_at VARCHAR,
                duration_seconds DOUBLE DEFAULT 0
            )
        '''),
    ]

    for table_name, ddl in tables:
        try:
            for stmt in _split_sql_script(ddl):
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)
        except Exception as e:
            print(f'[DB] 创建表 {table_name} 时出错: {e}', flush=True)

    conn.commit()

    # ---- 迁移：检查并添加缺失列（兼容老库） ----
    def add_column_if_not_exists(table, column, definition):
        try:
            cursor.execute(f'SELECT {column} FROM {table} LIMIT 1')
        except Exception:
            try:
                cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
                conn.commit()
            except Exception as e:
                print(f'[DB] 添加列 {table}.{column} 失败: {e}', flush=True)

    add_column_if_not_exists('board_replies', 'attachment', 'VARCHAR DEFAULT NULL')
    add_column_if_not_exists('cmd_commands', 'type', "VARCHAR DEFAULT 'cmd'")

    # ---- 默认管理员 ----
    cursor.execute("SELECT id FROM users WHERE username = ?", ('服主',))
    if not cursor.fetchone():
        admin_hash = hashlib.sha256('admin1324'.encode('utf-8')).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            ('服主', admin_hash, 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()

    # ---- 默认模组介绍 ----
    cursor.execute("SELECT COUNT(*) AS c FROM mod_intros")
    count_row = cursor.fetchone()
    if count_row and count_row[0] == 0:
        default_intros = [
            ('mountain-snow', 'Terralith', '塑造出峡谷、高山等千变万化的地形，等你去揭开每一处的神秘面纱。'),
            ('snowflake', 'SnowySpirit', '让世界被冰雪覆盖，可在冰雪城堡聚会，或在冰湖享受垂钓时光。'),
            ('building-2', 'Towns', '助力搭建宏伟城镇与高耸塔楼，见证文明从萌芽走向繁盛。'),
            ('sofa', 'Macaw 家具', '提供海量精致家具，无论是打造温馨小窝还是豪华宫殿，都能轻松实现。'),
            ('chef-hat', 'FarmersDelight', '体验耕耘收获，烹饪出美味食物，享受田园慢生活。'),
            ('grape', 'letsdo-viney', '种植葡萄酿造美酒，体验田园雅趣，一瓶顶级美酒，需要现实时间的数月哦！'),
            ('store', 'TradingPost', '无需频繁点击村民进行交易，可以直接通过交易站和附近村民交易。'),
            ('circle-dot', 'Waystones', '自由设置传送点，快速穿梭各地，冒险更高效。'),
            ('pickaxe', 'VeinMining', '挖矿砍树连贯进行，战斗时享受超强属性带来的爽感。'),
            ('car', 'Automobility', '亲手打造独特座驾，在赛道上和好友激情飙车。'),
            ('camera', 'Exposure', '记录方块世界美景，制作相册分享精彩。'),
            ('backpack', 'TravelersBackpack', '大容量背包，收纳方便，冒险轻装上阵。'),
        ]
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for icon, title, content in default_intros:
            cursor.execute(
                "INSERT INTO mod_intros (icon, title, content, created_at) VALUES (?, ?, ?, ?)",
                (icon, title, content, now)
            )
        conn.commit()

    conn.close()
