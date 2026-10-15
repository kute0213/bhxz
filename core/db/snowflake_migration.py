"""雪花 ID 迁移 —— 把历史自增 ID 统一迁移为雪花 ID（服务器自检时触发）。

背景：全站所有非用户表主键改为雪花算法统一生成（见 core/shared/snowflake.py）。
历史数据里已经确定的（自增）ID 需在「服务器自检」阶段一次性改为雪花 ID，
且要满足：

* **等同于当前时刻同时发布**：迁移按原记录顺序逐条调用 next_id()，
  时间戳为迁移当时的毫秒、序列号递增，迁移完成后这些 ID 看起来就像
  「刚刚同一时刻按顺序发布」的雪花 ID；
* **顺序不变**：按旧 ID 升序重分配，新 ID 单调递增，ORDER BY id 的语义不变；
* **关联关系不变**：父子表外键（如评论 → 建筑、收藏 → 音频）随父表 ID 同步重映射；
* **幂等**：通过比对是否存在历史 ID 判断是否已完成；迁移在单事务内完成，
  要么整体成功要么整体回滚，不会出现半迁移状态。

注意：用户表（users）保持自增 ID 不变，其它表引用用户的那一列（user_id /
author_id / sender_id 等）无需改动。本模块只处理「非用户表主键」。
"""

import sqlite3

from core.db.connection import get_db
from core.shared.snowflake import is_snowflake_id, next_id
from core.system.logger import log

# 需要迁移「自身主键」的非用户表（按父子依赖顺序排列，父表在前）
_OWN_ID_TABLES = (
    'public_buildings',
    'server_guides',
    'music',
    'backgrounds',
    'mod_intros',
    'db_backups',
    'settings',
    'public_paths',
    'guide_edit_bans',
    'broadcast_logs',
    'game_account_registrations',
    'game_account_bans',
    'game_server_ban_applications',
    'building_comments',
    'building_reports',
    'building_favorites',
    'guide_favorites',
)

# 引用「其它非用户表」主键的外键列： (子表, 外键列, 父表)
# 用户相关列（user_id / author_id / ...）不在其中——users 保持自增不变。
_FK_REMAPS = (
    ('music_favorites', 'music_id', 'music'),
    ('building_comments', 'building_id', 'public_buildings'),
    ('building_reports', 'building_id', 'public_buildings'),
    ('building_favorites', 'building_id', 'public_buildings'),
    ('guide_favorites', 'guide_id', 'server_guides'),
)


def _min_id(conn, table):
    """返回表内最小主键；表不存在或无数据返回 None。"""
    try:
        row = conn.execute(f'SELECT MIN(id) AS m FROM {table}').fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return row['m']


def _has_legacy_ids(conn, table):
    """判断表中是否存在历史自增 ID（存在即需迁移）。"""
    m = _min_id(conn, table)
    return m is not None and not is_snowflake_id(m)


def migrate_legacy_ids():
    """执行雪花 ID 迁移（幂等）。返回实际迁移的记录数。"""
    conn = get_db()

    legacy_tables = [t for t in _OWN_ID_TABLES if _has_legacy_ids(conn, t)]
    if not legacy_tables:
        log('INFO', 'DB', '雪花 ID 自检：无历史自增 ID 需要迁移')
        return 0

    log('INFO', 'DB', f'雪花 ID 自检：检测到 {len(legacy_tables)} 张表含历史 ID，开始迁移')

    # 迁移期间关闭外键约束（同一事务内先改父表 ID 再改子表外键，
    # 若开启外键会因中间态不一致而报错）；迁移完成后恢复。
    conn.execute('PRAGMA foreign_keys=OFF')
    migrated = 0
    try:
        with get_db() as c:
            mappings = {}
            for table in _OWN_ID_TABLES:
                rows = c.execute(f'SELECT id FROM {table} ORDER BY id').fetchall()
                if not rows:
                    mappings[table] = {}
                    continue
                if table not in legacy_tables:
                    mappings[table] = {}
                    continue
                updates = []
                mapping = {}
                for r in rows:
                    old = r['id']
                    new = next_id()
                    mapping[old] = new
                    updates.append((new, old))
                c.executemany(f'UPDATE {table} SET id = ? WHERE id = ?', updates)
                mappings[table] = mapping
                migrated += len(updates)

            # 父表 ID 已重分配后，同步重映射子表外键，保证关联关系不变
            for child, col, parent in _FK_REMAPS:
                mapping = mappings.get(parent) or {}
                if not mapping:
                    continue
                updates = [(new, old) for old, new in mapping.items()]
                if updates:
                    c.executemany(
                        f'UPDATE {child} SET {col} = ? WHERE {col} = ?', updates
                    )
    except Exception:
        conn.execute('PRAGMA foreign_keys=ON')
        raise
    conn.execute('PRAGMA foreign_keys=ON')

    log('INFO', 'DB', f'雪花 ID 迁移完成：共重分配 {migrated} 条记录')
    return migrated
