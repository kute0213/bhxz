"""全站搜索业务服务：跨「公共建筑 / 服务器指南 / 大喇叭音频 / 讨论帖子」聚合搜索。

所有函数为 Flask 无关的纯业务逻辑，返回统一结构的结果数据。
每类结果的条数由系统设置 SEARCH_PER_PAGE 控制，调用方传入的参数一律被忽略。
"""

from core.db import get_db
from config import get_page_size
from services.music.constants import STATUS_PUBLIC

# 搜索类别标识
KIND_ALL = 'all'
KIND_BUILDINGS = 'buildings'
KIND_GUIDES = 'guides'
KIND_MUSIC = 'music'
KIND_TOPICS = 'topics'

# 可供单独筛选的类别（不含 all）
VALID_KINDS = (KIND_BUILDINGS, KIND_GUIDES, KIND_MUSIC, KIND_TOPICS)

# 关键词最大长度（超出截断，避免异常超长查询）
MAX_KEYWORD_LEN = 60


def search_limit() -> int:
    """每类搜索结果条数，由系统设置 SEARCH_PER_PAGE 控制（API 无法覆盖）。"""
    return get_page_size('SEARCH_PER_PAGE', 5)


def normalize_kind(kind) -> str:
    """规范化类别参数，非法值一律回退为 all。"""
    kind = (kind or '').strip().lower()
    return kind if kind in VALID_KINDS else KIND_ALL


def _like(keyword):
    return f'%{keyword}%'


def _search_buildings(conn, like, limit):
    """搜索已审核通过的公共建筑（标题 / 标签 / 描述）。"""
    where = (
        "b.status = 'approved' AND (b.title LIKE ? OR b.tags LIKE ? OR b.description LIKE ?)"
    )
    params = (like, like, like)
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM public_buildings b WHERE {where}", params
    ).fetchone()['c']
    rows = conn.execute(
        f"""
        SELECT b.id, b.title, b.tags, b.description, b.warp_name, u.username AS author_name
        FROM public_buildings b
        LEFT JOIN users u ON b.author_id = u.id
        WHERE {where}
        ORDER BY b.published_at DESC, b.id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    items = [{
        'id': r['id'],
        'title': r['title'] or '',
        'desc': r['description'] or '',
        'tags': r['tags'] or '',
        'warp_name': r['warp_name'] or '',
        'author_name': r['author_name'] or '未知',
    } for r in rows]
    return items, total


def _search_guides(conn, like, limit):
    """搜索已审核通过的服务器指南（标题 / 摘要 / 正文）。"""
    where = "g.status = 'approved' AND (g.title LIKE ? OR g.summary LIKE ? OR g.content LIKE ?)"
    params = (like, like, like)
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM server_guides g WHERE {where}", params
    ).fetchone()['c']
    rows = conn.execute(
        f"""
        SELECT g.id, g.title, g.summary, g.content, u.username AS author_name
        FROM server_guides g
        LEFT JOIN users u ON g.author_id = u.id
        WHERE {where}
        ORDER BY g.is_pinned DESC, g.title ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    items = [{
        'id': r['id'],
        'title': r['title'] or '',
        'desc': r['summary'] or (r['content'] or '')[:120],
        'author_name': r['author_name'] or '未知',
    } for r in rows]
    return items, total


def _search_music(conn, like, limit):
    """搜索已公开的大喇叭音频（名称 / 标签）。"""
    where = "status = ? AND (title LIKE ? OR tags LIKE ?)"
    params = (STATUS_PUBLIC, like, like)
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM music WHERE {where}", params
    ).fetchone()['c']
    rows = conn.execute(
        f"""
        SELECT id, title, tags, username, created_at
        FROM music
        WHERE {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    items = [{
        'id': r['id'],
        'title': r['title'] or '',
        'desc': '',
        'tags': r['tags'] or '',
        'author_name': r['username'] or '未知',
        'created_at': r['created_at'] or '',
    } for r in rows]
    return items, total


def _search_topics(conn, like, limit):
    """搜索讨论帖子（标题 / 正文）。"""
    where = "(t.title LIKE ? OR t.content LIKE ?)"
    params = (like, like)
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM discussion_topics t WHERE {where}", params
    ).fetchone()['c']
    rows = conn.execute(
        f"""
        SELECT t.id, t.title, t.content, t.created_at,
               c.name AS category_name, u.username AS author_name
        FROM discussion_topics t
        JOIN users u ON t.user_id = u.id
        LEFT JOIN discussion_categories c ON t.category_id = c.id
        WHERE {where}
        ORDER BY t.is_pinned DESC, t.updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    items = [{
        'id': r['id'],
        'title': r['title'] or '',
        'desc': (r['content'] or '')[:120],
        'category_name': r['category_name'] or '',
        'author_name': r['author_name'] or '未知',
    } for r in rows]
    return items, total


# 类别 → 搜索函数映射
_HANDLERS = {
    KIND_BUILDINGS: _search_buildings,
    KIND_GUIDES: _search_guides,
    KIND_MUSIC: _search_music,
    KIND_TOPICS: _search_topics,
}


def search(keyword):
    """执行全站搜索，返回 (keyword, results, counts)。

    - keyword：清洗后的关键词（最多 MAX_KEYWORD_LEN 字）
    - results：各类别命中的前 N 条记录（每类条数由 SEARCH_PER_PAGE 控制）
    - counts：各类别命中的总数（用于分类标签上的计数）

    关键词为空时不查询数据库，直接返回空结果。
    """
    kw = (keyword or '').strip()[:MAX_KEYWORD_LEN]
    results = {k: [] for k in VALID_KINDS}
    counts = {k: 0 for k in VALID_KINDS}
    if not kw:
        return kw, results, counts

    like = _like(kw)
    limit = search_limit()
    conn = get_db()
    try:
        for kind, handler in _HANDLERS.items():
            items, total = handler(conn, like, limit)
            results[kind] = items
            counts[kind] = total
    finally:
        conn.close()
    return kw, results, counts
