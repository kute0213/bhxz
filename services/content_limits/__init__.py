"""待审核内容上限业务逻辑。

从 core/helpers.py 下沉到业务层：待审核内容上限属于业务规则，不属于基础设施，
故不再放在核心层。

规则：管理员豁免；普通用户受「总量上限 + 单类型上限」双重限制，
任一上限设为 0 表示不限制，取「先达到者」。
"""

from core.db import get_db
from config import get_config_value

# 各类未通过内容的统计信息：类型键 -> (表名, 用户列, 未通过条件, 单独上限配置键, 显示名)
_PENDING_TYPES = {
    'building':   ('public_buildings', 'author_id', "status = 'pending'", 'MAX_PENDING_BUILDING', '公共建筑'),
    'guide':      ('server_guides',    'author_id', "status != 'approved'", 'MAX_PENDING_GUIDE', '服务器指南'),
    'music':      ('music',            'user_id',   'status = 1',         'MAX_PENDING_MUSIC', '大喇叭音频'),
    'background': ('backgrounds',      'user_id',   'status = 0',         'MAX_PENDING_BACKGROUND', '背景图片'),
}


def check_pending_limit(user, content_type=None) -> tuple:
    """检查用户的待审核内容是否达到上限（总量上限 + 单类型上限）。

    管理员豁免。返回 (allowed: bool, message: str)。

    content_type 为 _PENDING_TYPES 的键（building/guide/music/background）时，
    额外校验该类型的单独上限；总量与单类型上限取「先达到者」。
    任一上限设为 0 表示不限制。
    """
    if user.get('is_admin'):
        return True, ''

    conn = get_db()
    try:
        counts = {}
        for key, (table, user_col, condition, _, _) in _PENDING_TYPES.items():
            row = conn.execute(
                f'SELECT COUNT(*) AS c FROM {table} WHERE {user_col} = ? AND {condition}',
                (user['id'],),
            ).fetchone()
            counts[key] = row['c'] if row else 0
    finally:
        conn.close()

    # 总量上限
    total_limit = int(get_config_value('MAX_PENDING_CONTENT', 5) or 0)
    if total_limit > 0 and sum(counts.values()) >= total_limit:
        return False, f'您未通过审核的内容已达上限（共 {total_limit} 个），请等待现有内容审核通过后再发布'

    # 单类型上限
    if content_type in _PENDING_TYPES:
        _, _, _, limit_key, label = _PENDING_TYPES[content_type]
        limit = int(get_config_value(limit_key, 0) or 0)
        if limit > 0 and counts[content_type] >= limit:
            return False, f'您的{label}未通过数量（含草稿）已达上限（{limit} 个），请等待现有内容审核通过后再创建'

    return True, ''
