"""数据库 schema 初始化 —— 建表、迁移、默认数据。"""

import hashlib
from datetime import datetime

from core.db.connection import get_db
from core.logger import log


def init_db():
    """初始化数据库结构和默认数据。"""
    try:
        conn = get_db()
    except Exception as e:
        print(f'[FATAL] init_db: 获取数据库连接失败: {e}', file=__import__('sys').stderr)
        __import__('sys').stderr.flush()
        raise

    cursor = conn.cursor()

    # SQLite 自增主键统一使用 INTEGER PRIMARY KEY AUTOINCREMENT
    tables = [
        ('users', '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT DEFAULT '',
                avatar_key TEXT DEFAULT '',
                is_admin INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        '''),
        ('mod_intros', '''
            CREATE TABLE IF NOT EXISTS mod_intros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icon TEXT NOT NULL DEFAULT 'box',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        '''),
        # 数据库备份记录表
        ('db_backups', '''
            CREATE TABLE IF NOT EXISTS db_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_name TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                backup_type TEXT NOT NULL DEFAULT 'scheduled',
                status TEXT NOT NULL DEFAULT 'running',
                size_bytes INTEGER DEFAULT 0,
                error_message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_seconds REAL DEFAULT 0
            )
        '''),
        # 系统设置表（用于管理后台在线编辑配置）
        ('settings', '''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT DEFAULT '',
                description TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
        '''),
        # 公开文件/目录映射表
        ('public_paths', '''
            CREATE TABLE IF NOT EXISTS public_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_path TEXT UNIQUE NOT NULL,
                local_path TEXT NOT NULL,
                is_directory INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        '''),
        # 服务器指南表
        ('server_guides', '''
            CREATE TABLE IF NOT EXISTS server_guides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                summary TEXT DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                cover_image TEXT DEFAULT '',
                author_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                is_pinned INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT DEFAULT NULL,
                rejected_reason TEXT DEFAULT '',
                rejected_at TEXT DEFAULT NULL
            )
        '''),
        # 指南编辑封禁表
        ('guide_edit_bans', '''
            CREATE TABLE IF NOT EXISTS guide_edit_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER DEFAULT NULL,
                ip_address TEXT DEFAULT NULL,
                banned_by INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT DEFAULT NULL
            )
        '''),
        # IP 封禁表（expires_at 为空 = 永久封禁）
        ('ip_bans', '''
            CREATE TABLE IF NOT EXISTS ip_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                reason TEXT DEFAULT '',
                banned_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT DEFAULT NULL
            )
        '''),
        # 广播邮件日志表
        ('broadcast_logs', '''
            CREATE TABLE IF NOT EXISTS broadcast_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                sender_id INTEGER NOT NULL,
                sender_name TEXT NOT NULL,
                recipient_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        '''),
        # 讨论分类表
        ('discussion_categories', '''
            CREATE TABLE IF NOT EXISTS discussion_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        '''),
        # 讨论帖子表
        ('discussion_topics', '''
            CREATE TABLE IF NOT EXISTS discussion_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category_id INTEGER,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tags TEXT DEFAULT '',
                attachment TEXT,
                is_pinned INTEGER DEFAULT 0,
                is_locked INTEGER DEFAULT 0,
                view_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        '''),
        # 讨论回复表
        ('discussion_replies', '''
            CREATE TABLE IF NOT EXISTS discussion_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                attachment TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        '''),
        # 大喇叭音频表（上传音频转码为 HLS，供游戏内大喇叭播放）
        # status: 0=私有 1=待审核 2=已公开（3=已驳回，仅遗留老数据保留，新驳回直接转为私有）
        ('music', '''
            CREATE TABLE IF NOT EXISTS music (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                title TEXT NOT NULL,
                file_path TEXT DEFAULT '',
                status INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        '''),
        # 大喇叭音频收藏表（联合主键：同一用户对同一音频仅一条收藏记录）
        ('music_favorites', '''
            CREATE TABLE IF NOT EXISTS music_favorites (
                user_id INTEGER NOT NULL,
                music_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, music_id)
            )
        '''),
        # 背景图片表（status: 0=待审核 1=已通过 2=已驳回）
        ('backgrounds', '''
            CREATE TABLE IF NOT EXISTS backgrounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        '''),
        # 游戏账号注册申请表
        ('game_account_registrations', '''
            CREATE TABLE IF NOT EXISTS game_account_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mc_username TEXT NOT NULL,
                encrypted_password TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reject_reason TEXT DEFAULT '',
                reviewed_by INTEGER DEFAULT NULL,
                reviewed_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            )
        '''),
        # 游戏账号封禁表
        ('game_account_bans', '''
            CREATE TABLE IF NOT EXISTS game_account_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mc_username TEXT NOT NULL UNIQUE,
                reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                created_by INTEGER DEFAULT NULL
            )
        '''),
    ]

    for table_name, ddl in tables:
        try:
            cursor.execute(ddl)
        except Exception as e:
            log('ERROR', 'DB', f'创建表 {table_name} 时出错: {e}')

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
                log('ERROR', 'DB', f'添加列 {table}.{column} 失败: {e}')

    # 用户表：邮箱、头像路径、登录失败锁定
    add_column_if_not_exists('users', 'email', "TEXT DEFAULT ''")
    # 用户头像与个性背景只保存本地文件路径，图片内容不写入数据库。
    add_column_if_not_exists('users', 'avatar_key', "TEXT DEFAULT ''")
    add_column_if_not_exists('users', 'login_attempts', 'INTEGER DEFAULT 0')
    add_column_if_not_exists('users', 'locked_until', "TEXT DEFAULT ''")
    # 游戏账号封禁表：添加 user_id 列，支持封禁官网账号申请资格
    add_column_if_not_exists('game_account_bans', 'user_id', 'INTEGER DEFAULT NULL')

    # ---- 大喇叭音频：公开审核机制迁移 ----
    # 老库使用 is_public（0/1）标记公开，新库改用 status（0=私有 1=待审核 2=已公开）
    add_column_if_not_exists('music', 'status', 'INTEGER DEFAULT 0')
    # 大喇叭音频：标签列（逗号分隔，供搜索匹配与卡片展示）
    add_column_if_not_exists('music', 'tags', "TEXT DEFAULT ''")
    # 迁移前先检查 is_public 列是否存在（新库没有此列，跳过迁移）
    try:
        cursor.execute("SELECT is_public FROM music LIMIT 0")
        has_is_public = True
    except Exception:
        has_is_public = False
    if has_is_public:
        try:
            # 历史已公开音频（is_public=1）直接迁移为「已通过」状态，立即在公开列表可见
            cursor.execute("UPDATE music SET status = 2 WHERE status = 0 AND is_public = 1")
            conn.commit()
        except Exception as e:
            log('ERROR', 'DB', f'迁移 music 公开状态失败: {e}')

    # ---- 管理员账号 ----
    # 确保 PRIMARY_ADMIN_USERNAMES 中的所有账号为管理员，
    # 但不会移除其他用户的管理员权限。
    from config import PRIMARY_ADMIN_USERNAMES
    for admin_username in PRIMARY_ADMIN_USERNAMES:
        cursor.execute(
            "SELECT id FROM users WHERE lower(username) = lower(?) LIMIT 1",
            (admin_username,),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (row[0],),
            )
        else:
            # 用户不存在时不自动创建（避免意外创建账号）
            log('INFO', 'DB', f'管理员账号 {admin_username} 尚未注册，跳过')

    # 检查是否至少有一个管理员，若没有任何管理员则创建默认 admin 账号
    cursor.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin = 1")
    admin_count = cursor.fetchone()[0]
    if admin_count == 0:
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

    # ---- 指南拒绝审核：添加 rejected_at 列 ----
    add_column_if_not_exists('server_guides', 'rejected_at', "TEXT DEFAULT NULL")
    # 兼容旧数据：已拒绝但无 rejected_at 的指南，用 updated_at 填充
    try:
        cursor.execute(
            "UPDATE server_guides SET rejected_at = updated_at "
            "WHERE status = 'rejected' AND rejected_at IS NULL"
        )
        conn.commit()
    except Exception as e:
        log('ERROR', 'DB', f'迁移 server_guides.rejected_at 失败: {e}')

    # ---- 背景图片：添加 rejected_at 列（被驳回内容 24 小时后自动清理） ----
    add_column_if_not_exists('backgrounds', 'rejected_at', "TEXT DEFAULT NULL")

    # ---- 彻底删除游戏账号绑定功能：移除旧绑定表 ----
    # 绑定/改密功能已移除，旧库遗留的绑定表不再使用，直接删除。
    try:
        cursor.execute("DROP TABLE IF EXISTS game_account_bindings")
        conn.commit()
        log('INFO', 'DB', '已删除废弃的游戏账号绑定表 game_account_bindings')
    except Exception as e:
        log('ERROR', 'DB', f'删除 game_account_bindings 表失败: {e}')

    conn.close()
