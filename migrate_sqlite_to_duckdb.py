"""
一次性数据迁移脚本：将 SQLite 数据库 (site.db) 迁移到 DuckDB (site.duckdb)。

使用方法：
    python migrate_sqlite_to_duckdb.py

迁移完成后请删除此脚本。

迁移流程：
1. 检查 SQLite 数据库是否存在
2. 创建 DuckDB 数据库及表结构（使用 core/database.py 的 init_db）
3. 逐表迁移数据，自动重置序列起始值
4. 验证迁移结果（行数对比）
5. 输出迁移统计
"""

import os
import sys
import sqlite3
from datetime import datetime

# 确保项目根目录在 path 中
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_ROOT)

import duckdb
from config import DB_PATH as DUCKDB_PATH

SQLITE_PATH = os.path.join(APP_ROOT, 'site.db')

# 需要迁移的表（按依赖顺序排列）
TABLES = [
    'users',
    'mod_intros',
    'polls',
    'poll_options',
    'poll_votes',
    'board_topics',
    'board_replies',
    'access_logs',
    'cmd_commands',
    'scheduled_tasks',
    'scheduled_task_logs',
    'cmd_run_logs',
]


def check_sqlite_db():
    """检查 SQLite 数据库是否存在。"""
    if not os.path.exists(SQLITE_PATH):
        print(f'[错误] 找不到 SQLite 数据库: {SQLITE_PATH}')
        return False
    return True


def init_duckdb():
    """初始化 DuckDB 数据库（建表）。"""
    print('[迁移] 初始化 DuckDB 数据库...')
    from core.database import init_db
    init_db()
    print('[迁移] DuckDB 数据库初始化完成')


def get_sqlite_table_info(sqlite_conn, table):
    """获取 SQLite 表的列信息。"""
    cursor = sqlite_conn.execute(f'PRAGMA table_info({table})')
    return cursor.fetchall()


def get_sqlite_row_count(sqlite_conn, table):
    """获取 SQLite 表的行数。"""
    cursor = sqlite_conn.execute(f'SELECT COUNT(*) FROM {table}')
    return cursor.fetchone()[0]


def migrate_table(sqlite_conn, duckdb_conn, table):
    """迁移单张表的数据。"""
    print(f'[迁移] 正在迁移表 {table}...', end=' ', flush=True)

    # 获取 SQLite 表结构
    cols = get_sqlite_table_info(sqlite_conn, table)
    col_names = [c[1] for c in cols]

    # 获取所有数据
    sqlite_cursor = sqlite_conn.execute(f'SELECT * FROM {table}')
    rows = sqlite_cursor.fetchall()
    total = len(rows)

    if total == 0:
        print('空表，跳过')
        return 0

    # 先清空 DuckDB 表中的旧数据（init_db 可能已创建默认数据）
    try:
        duckdb_conn.execute(f'DELETE FROM {table}')
    except Exception as e:
        print(f' (警告: 清空旧数据失败: {e})', end='')

    # 构建 INSERT 语句（用 ? 占位符）
    placeholders = ','.join(['?' for _ in col_names])
    col_list = ','.join(col_names)
    insert_sql = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'

    # 批量插入
    batch_size = 500
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        duckdb_conn.executemany(insert_sql, batch)
        inserted += len(batch)

    # 重置序列到 max(id) + 1
    # DuckDB 不支持 setval() 和 ALTER SEQUENCE ... RESTART WITH ...
    # 方案：ALTER TABLE DROP DEFAULT -> DROP SEQUENCE -> CREATE SEQUENCE -> ALTER TABLE SET DEFAULT
    try:
        max_id_row = duckdb_conn.execute(f'SELECT MAX(id) FROM {table}').fetchone()
        if max_id_row and max_id_row[0] is not None:
            max_id = max_id_row[0]
            next_id = max_id + 1
            seq_name = f'{table}_id_seq'
            duckdb_conn.execute(f'ALTER TABLE {table} ALTER id DROP DEFAULT')
            duckdb_conn.execute(f'DROP SEQUENCE {seq_name}')
            duckdb_conn.execute(f'CREATE SEQUENCE {seq_name} START {next_id}')
            duckdb_conn.execute(
                f"ALTER TABLE {table} ALTER id SET DEFAULT nextval('{seq_name}')"
            )
    except Exception as e:
        print(f' (警告: 重置序列失败: {e})', end='')

    print(f'完成 ({inserted} 行)')
    return inserted


def verify_migration(sqlite_conn, duckdb_conn):
    """验证迁移结果。"""
    print('\n[验证] 对比表行数...')
    all_ok = True
    for table in TABLES:
        try:
            sqlite_count = get_sqlite_row_count(sqlite_conn, table)
        except Exception:
            continue
        try:
            row = duckdb_conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()
            duckdb_count = row[0]
        except Exception:
            duckdb_count = -1

        status = '✓' if sqlite_count == duckdb_count else '✗'
        if sqlite_count != duckdb_count:
            all_ok = False
        print(f'  {status} {table}: SQLite={sqlite_count}, DuckDB={duckdb_count}')

    return all_ok


def main():
    print('=' * 60)
    print('  SQLite → DuckDB 数据迁移脚本')
    print('=' * 60)
    print(f'  SQLite 源: {SQLITE_PATH}')
    print(f'  DuckDB 目标: {DUCKDB_PATH}')
    print()

    if not check_sqlite_db():
        sys.exit(1)

    if os.path.exists(DUCKDB_PATH):
        print(f'[警告] DuckDB 数据库已存在: {DUCKDB_PATH}')
        answer = input('是否继续迁移到现有数据库？(y/N): ').strip().lower()
        if answer != 'y':
            print('已取消。')
            sys.exit(0)

    # 连接 SQLite
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    # 初始化 DuckDB
    init_duckdb()

    # 连接 DuckDB
    duckdb_conn = duckdb.connect(DUCKDB_PATH)

    # 逐表迁移
    start_time = datetime.now()
    total_rows = 0

    print()
    for table in TABLES:
        # 检查表是否在 SQLite 中存在
        try:
            sqlite_conn.execute(f'SELECT 1 FROM {table} LIMIT 1')
        except sqlite3.OperationalError:
            print(f'[迁移] 表 {table} 在 SQLite 中不存在，跳过')
            continue

        try:
            count = migrate_table(sqlite_conn, duckdb_conn, table)
            total_rows += count
        except Exception as e:
            print(f'[错误] 迁移表 {table} 失败: {e}')
            import traceback
            traceback.print_exc()

    # 验证
    print()
    all_ok = verify_migration(sqlite_conn, duckdb_conn)

    # 统计
    elapsed = (datetime.now() - start_time).total_seconds()
    print()
    print('=' * 60)
    print(f'  迁移完成')
    print(f'  迁移表数: {len(TABLES)}')
    print(f'  迁移总行数: {total_rows}')
    print(f'  耗时: {elapsed:.2f} 秒')
    print(f'  验证结果: {"全部通过" if all_ok else "存在不一致"}')
    print('=' * 60)

    if all_ok:
        print('\n[提示] 迁移成功！请删除此脚本后启动应用。')
    else:
        print('\n[警告] 存在数据不一致，请检查上述对比结果。')

    sqlite_conn.close()
    duckdb_conn.close()


if __name__ == '__main__':
    main()
