#!/usr/bin/env python3
"""数据库迁移脚本：DuckDB (site.duckdb) → SQLite (site.db)。

用法：
    python scripts/migrate_db.py

流程：
1. 检查旧 DuckDB 数据库是否存在（不存在则跳过）
2. 检查 duckdb 依赖是否已安装（迁移完成后可移除）
3. 在 SQLite 中初始化新 schema（复用 init_db）
4. 逐表复制数据（跳过已删除的 CMD 控制台相关表）
5. 校验迁移结果并输出统计

注意：
- 迁移前请先备份 site.duckdb
- 迁移完成后会自动重命名旧库为 site.duckdb.bak（可手动删除）
"""

import os
import shutil
import sys

# 项目根目录
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_ROOT)

from config import DB_PATH  # noqa: E402

DUCKDB_PATH = os.path.join(APP_ROOT, 'site.duckdb')

# 需要迁移的数据表（CMD 控制台相关表已随功能删除，不迁移）
TABLES = [
    'users',
    'mod_intros',
    'db_backups',
    'settings',
    'public_paths',
    'server_guides',
    'guide_edit_bans',
    'broadcast_logs',
    'discussion_categories',
    'discussion_topics',
    'discussion_replies',
    'music',
    'music_favorites',
    'backgrounds',
    'game_account_bindings',
    'game_account_registrations',
    'game_account_bans',
]


def _get_duckdb_tables(conn):
    """获取 DuckDB 中的全部表名。"""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
    ).fetchall()
    return {row[0] for row in rows}


def migrate():
    if not os.path.isfile(DUCKDB_PATH):
        print('未找到旧数据库 site.duckdb，无需迁移。')
        return 0

    if os.path.isfile(DB_PATH):
        print(f'目标数据库已存在: {DB_PATH}')
        print('为避免覆盖现有数据，请先手动删除 site.db 后再运行迁移。')
        return -1

    try:
        import duckdb
    except ImportError:
        print('缺少 duckdb 依赖，无法读取旧数据库。')
        print('请先安装：pip install duckdb')
        print('然后重新运行本脚本。')
        return -1

    print('=' * 60)
    print(' 数据库迁移：DuckDB → SQLite')
    print('=' * 60)
    print(f'旧库: {DUCKDB_PATH}')
    print(f'新库: {DB_PATH}')
    print()

    # 1. 初始化 SQLite schema
    print('[1/4] 初始化 SQLite 表结构...')
    from core.db import init_db
    init_db()
    print('  -> 表结构初始化完成')

    # 2. 打开旧库，逐表复制
    print('[2/4] 复制数据...')
    old_conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    new_conn = __import__('sqlite3').connect(DB_PATH)
    try:
        old_tables = _get_duckdb_tables(old_conn)
        total = 0
        for table in TABLES:
            if table not in old_tables:
                print(f'  -> 跳过 {table}（旧库中不存在）')
                continue
            rows = old_conn.execute(f'SELECT * FROM "{table}"').fetchall()
            cols = [desc[0] for desc in old_conn.description]
            if not rows:
                print(f'  -> {table}: 0 行')
                continue
            # init_db 可能在空库中预置了默认数据（如 admin 用户、默认模组介绍），
            # 复制前先清空目标表，避免主键冲突
            new_conn.execute(f'DELETE FROM "{table}"')
            placeholders = ', '.join(['?'] * len(cols))
            col_sql = ', '.join(f'"{c}"' for c in cols)
            new_conn.executemany(
                f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', rows
            )
            total += len(rows)
            print(f'  -> {table}: {len(rows)} 行')
        new_conn.commit()
        print(f'  -> 共迁移 {total} 行')
    finally:
        old_conn.close()
        new_conn.close()

    # 3. 校验
    print('[3/4] 校验迁移结果...')
    import sqlite3
    check_conn = sqlite3.connect(DB_PATH)
    try:
        for table in TABLES:
            count = check_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            print(f'  -> {table}: {count} 行')
    finally:
        check_conn.close()

    # 4. 备份旧库并输出提示
    print('[4/4] 备份旧数据库...')
    backup_path = DUCKDB_PATH + '.bak'
    shutil.move(DUCKDB_PATH, backup_path)
    print(f'  -> 旧库已重命名为: {backup_path}（确认无误后可手动删除）')
    if os.path.exists(DUCKDB_PATH + '.wal'):
        shutil.move(DUCKDB_PATH + '.wal', backup_path + '.wal')

    print()
    print('迁移完成！SQLite 数据库已启用 WAL 模式。')
    return 0


if __name__ == '__main__':
    sys.exit(migrate())
