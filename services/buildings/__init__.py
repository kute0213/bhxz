"""公共建筑业务服务：查询/搜索、标签、收藏。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 或数据结构。
标签与收藏规则与「大喇叭音频」保持一致，便于前端复用交互。
"""

from datetime import datetime

from core.db import get_db

# 列表分页大小：每次加载 10 条，前端点击「加载更多」再取下一页
PAGE_SIZE = 10

# 标签限制：最多 10 个，每个不超过 12 字
MAX_TAGS = 10
MAX_TAG_LEN = 12


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------------------
# 标签处理
# ---------------------------------------------------------------------------


def normalize_tags(raw):
    """将逗号（中英文）分隔的标签串规范化为逗号分隔字符串。

    去重、去空、限制数量与单个长度，与音乐标签规则保持一致。
    """
    if not raw:
        return ''
    parts = str(raw).replace('，', ',').split(',')
    seen = []
    for part in parts:
        tag = part.strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LEN:
            tag = tag[:MAX_TAG_LEN]
        if tag not in seen:
            seen.append(tag)
        if len(seen) >= MAX_TAGS:
            break
    return ','.join(seen)


def get_all_tags():
    """汇总所有已通过建筑的标签，按出现频次倒序返回（供筛选展示）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT tags FROM public_buildings "
            "WHERE status = 'approved' AND tags IS NOT NULL AND tags != ''"
        ).fetchall()

    counter = {}
    for row in rows:
        for tag in (row['tags'] or '').split(','):
            tag = tag.strip()
            if tag:
                counter[tag] = counter.get(tag, 0) + 1
    return [
        {'name': name, 'count': count}
        for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ---------------------------------------------------------------------------
# 查询 / 搜索
# ---------------------------------------------------------------------------


def list_buildings(search=None, tag=None, page=1, page_size=PAGE_SIZE,
                   author_id=None, my_mode=False):
    """分页查询公共建筑。

    Args:
        search: 关键词，匹配标题与标签（模糊）
        tag: 精确标签过滤
        page: 页码（从 1 开始）
        page_size: 每页条数
        author_id: 指定作者（我的建筑）
        my_mode: 我的建筑模式（显示全部状态，按更新时间排序）

    Returns:
        (items, has_more)：items 为建筑 dict 列表，has_more 表示是否还有下一页
    """
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or PAGE_SIZE), 50))
    offset = (page - 1) * page_size

    conditions = []
    params = []

    if my_mode and author_id is not None:
        conditions.append('b.author_id = ?')
        params.append(author_id)
    else:
        conditions.append("b.status = 'approved'")

    if search:
        like = f'%{search.strip()}%'
        conditions.append('(b.title LIKE ? OR b.tags LIKE ?)')
        params.extend([like, like])

    if tag:
        # 精确标签匹配：以逗号包裹避免「abc」误匹配「abcd」
        conditions.append("(',' || b.tags || ',') LIKE ?")
        params.append(f'%,{tag.strip()},%')

    where = ' AND '.join(conditions) if conditions else '1=1'

    if my_mode and author_id is not None:
        order = 'b.updated_at DESC, b.id DESC'
    else:
        order = 'favorite_count DESC, b.published_at DESC, b.id DESC'

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT b.*, u.username AS author_name,
                   (SELECT COUNT(*) FROM building_favorites f
                    WHERE f.building_id = b.id) AS favorite_count
            FROM public_buildings b
            LEFT JOIN users u ON b.author_id = u.id
            WHERE {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            (*params, page_size + 1, offset),
        ).fetchall()

    items = [dict(r) for r in rows]
    has_more = len(items) > page_size
    return items[:page_size], has_more


def get_building(building_id):
    """获取单个建筑（含作者名与收藏数）。"""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT b.*, u.username AS author_name,
                   (SELECT COUNT(*) FROM building_favorites f
                    WHERE f.building_id = b.id) AS favorite_count
            FROM public_buildings b
            LEFT JOIN users u ON b.author_id = u.id
            WHERE b.id = ?
            """,
            (building_id,),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# 收藏
# ---------------------------------------------------------------------------


def toggle_favorite(user_id, building_id):
    """收藏 / 取消收藏建筑。返回 (success, message, is_favorited, favorite_count)。

    仅已审核通过的建筑可被收藏；重复收藏自动取消。
    """
    building = get_building(building_id)
    if not building:
        return False, '建筑不存在', False, 0
    if building['status'] != 'approved':
        return False, '仅可收藏已审核通过的建筑', False, building.get('favorite_count', 0)

    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM building_favorites WHERE user_id = ? AND building_id = ?",
            (user_id, building_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM building_favorites WHERE user_id = ? AND building_id = ?",
                (user_id, building_id),
            )
            is_fav = False
            message = '已取消收藏'
        else:
            conn.execute(
                "INSERT INTO building_favorites (building_id, user_id, created_at) VALUES (?, ?, ?)",
                (building_id, user_id, _now()),
            )
            is_fav = True
            message = '已收藏'

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM building_favorites WHERE building_id = ?",
            (building_id,),
        ).fetchone()
        count = count_row['c'] if count_row else 0
    return True, message, is_fav, count


def get_favorite_ids(user_id, building_ids=None):
    """获取用户已收藏的建筑 ID 集合（列表页标记收藏状态用）。"""
    if not user_id:
        return set()
    with get_db() as conn:
        if building_ids:
            placeholders = ','.join('?' for _ in building_ids)
            rows = conn.execute(
                f"SELECT building_id FROM building_favorites "
                f"WHERE user_id = ? AND building_id IN ({placeholders})",
                (user_id, *building_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT building_id FROM building_favorites WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {int(r['building_id']) for r in rows}


# ---------------------------------------------------------------------------
# 标签编辑
# ---------------------------------------------------------------------------


def set_tags(building_id, user_id, is_admin, raw_tags):
    """设置建筑标签（作者本人或管理员可操作）。返回 (success, message, tags)。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT author_id FROM public_buildings WHERE id = ?",
            (building_id,),
        ).fetchone()
        if not row:
            return False, '建筑不存在', ''
        if row['author_id'] != user_id and not is_admin:
            return False, '无权修改此建筑的标签', ''

        tags = normalize_tags(raw_tags)
        conn.execute(
            "UPDATE public_buildings SET tags = ?, updated_at = ? WHERE id = ?",
            (tags, _now(), building_id),
        )
        return True, '标签已保存', tags
