"""数据库 schema 初始化 —— 建表、迁移、默认数据。"""

import hashlib
from datetime import datetime

from core.db.connection import get_db, _split_sql_script


def _sync_sequence(conn, table_name):
    """同步序列到表中最大 ID + 1，防止序列与数据脱节导致 Duplicate key。

    DuckDB 限制较多：
    - 不支持 ALTER SEQUENCE
    - 不支持 DROP SEQUENCE ... CASCADE（会破坏表的 DEFAULT 依赖）
    
    解决方案：循环调用 nextval 推进序列指针，直到超过表中最大 ID。
    不使用临时表方案，避免复杂 DDL 导致兼容性问题。
    """
    seq_name = f"{table_name}_id_seq"
    try:
        row = conn.execute(f"SELECT MAX(id) FROM {table_name}").fetchone()
        max_id = row[0] if row and row[0] is not None else 0
        if max_id <= 0:
            return

        advanced = False
        while True:
            seq_row = conn.execute(f"SELECT nextval('{seq_name}')").fetchone()
            next_val = seq_row[0] if seq_row else 1
            if next_val > max_id:
                break
            advanced = True

        if advanced:
            print(f'[DB] 序列 {seq_name} 已同步到 {max_id + 1}', flush=True)
    except Exception:
        pass


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
                task_type VARCHAR DEFAULT 'shell',
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
        ('scripts', '''
            CREATE SEQUENCE IF NOT EXISTS scripts_id_seq START 1;
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY DEFAULT nextval('scripts_id_seq'),
                name VARCHAR NOT NULL,
                description VARCHAR DEFAULT '',
                content VARCHAR DEFAULT '',
                script_type VARCHAR NOT NULL DEFAULT 'miniscript',
                sort_order INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
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
        # 系统设置表（用于管理后台在线编辑配置）
        ('settings', '''
            CREATE SEQUENCE IF NOT EXISTS settings_id_seq START 1;
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY DEFAULT nextval('settings_id_seq'),
                key VARCHAR UNIQUE NOT NULL,
                value VARCHAR DEFAULT '',
                description VARCHAR DEFAULT '',
                updated_at VARCHAR NOT NULL
            )
        '''),
        # 公开文件/目录映射表
        ('public_paths', '''
            CREATE SEQUENCE IF NOT EXISTS public_paths_id_seq START 1;
            CREATE TABLE IF NOT EXISTS public_paths (
                id INTEGER PRIMARY KEY DEFAULT nextval('public_paths_id_seq'),
                url_path VARCHAR UNIQUE NOT NULL,
                local_path VARCHAR NOT NULL,
                is_directory INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at VARCHAR NOT NULL
            )
        '''),
        # 服务器指南表
        ('server_guides', '''
            CREATE SEQUENCE IF NOT EXISTS server_guides_id_seq START 1;
            CREATE TABLE IF NOT EXISTS server_guides (
                id INTEGER PRIMARY KEY DEFAULT nextval('server_guides_id_seq'),
                title VARCHAR NOT NULL,
                slug VARCHAR UNIQUE NOT NULL,
                summary VARCHAR DEFAULT '',
                content VARCHAR NOT NULL DEFAULT '',
                cover_image VARCHAR DEFAULT '',
                author_id INTEGER NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                is_pinned INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL,
                published_at VARCHAR DEFAULT NULL,
                rejected_reason VARCHAR DEFAULT ''
            )
        '''),
        # 指南编辑封禁表
        ('guide_edit_bans', '''
            CREATE SEQUENCE IF NOT EXISTS guide_edit_bans_id_seq START 1;
            CREATE TABLE IF NOT EXISTS guide_edit_bans (
                id INTEGER PRIMARY KEY DEFAULT nextval('guide_edit_bans_id_seq'),
                user_id INTEGER DEFAULT NULL,
                ip_address VARCHAR DEFAULT NULL,
                banned_by INTEGER NOT NULL,
                reason VARCHAR DEFAULT '',
                created_at VARCHAR NOT NULL,
                expires_at VARCHAR DEFAULT NULL
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

    # ---- 同步序列：防止手动删除数据后序列与表数据脱节 ----
    for table_name, _ in tables:
        try:
            _sync_sequence(conn, table_name)
        except Exception as e:
            print(f'[DB] 同步序列 {table_name} 失败: {e}', flush=True)
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
    add_column_if_not_exists('scheduled_tasks', 'task_type', "VARCHAR DEFAULT 'shell'")
    add_column_if_not_exists('scheduled_tasks', 'script_id', 'INTEGER DEFAULT NULL')
    # 定时任务改为引用 cmd_commands 表中的快捷命令
    add_column_if_not_exists('scheduled_tasks', 'command_id', 'INTEGER DEFAULT NULL')

    # ---- 迁移：scripts 表添加 content 列（数据库存储） ----
    try:
        from services.script_store import ensure_table
        ensure_table()
    except Exception as e:
        print(f'[DB] 迁移 scripts 表失败: {e}', flush=True)

    # ---- 默认管理员（仅在系统中没有任何管理员时才创建） ----
    cursor.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin = 1")
    admin_row = cursor.fetchone()
    if admin_row and admin_row[0] == 0:
        cursor.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            ('admin', hashlib.sha256('admin1324'.encode('utf-8')).hexdigest(), 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()

    # ---- 默认模组介绍（仅在表为空时批量插入，使用 INSERT OR IGNORE） ----
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
                "INSERT OR IGNORE INTO mod_intros (icon, title, content, created_at) VALUES (?, ?, ?, ?)",
                (icon, title, content, now)
            )
        conn.commit()

    conn.close()
