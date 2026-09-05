"""讨论区业务服务 - 分类管理。"""

import datetime

from core.db import get_db
from core.logger import log


def get_categories():
    """获取所有分类。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM discussion_categories ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_category_dict():
    """获取 {id: name} 映射。"""
    cats = get_categories()
    return {c['id']: c['name'] for c in cats}


def create_category(name, slug, admin_user, ip_address):
    """创建分类。返回 (success, message)。"""
    if not name or not slug:
        return False, '请填写分类名称和别名'
    conn = get_db()
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO discussion_categories (name, slug, created_at) VALUES (?, ?, ?)",
            (name, slug, now)
        )
        conn.commit()
        log('Admin', '创建讨论分类', admin_user=admin_user['username'], name=name, slug=slug, ip=ip_address)
        return True, '分类已创建'
    except Exception:
        conn.rollback()
        return False, '创建失败，别名可能已存在'
    finally:
        conn.close()


def delete_category(cat_id, admin_user, ip_address):
    """删除分类。返回 (success, message)。"""
    if not cat_id:
        return False, '参数错误'
    conn = get_db()
    try:
        conn.execute("DELETE FROM discussion_categories WHERE id = ?", (cat_id,))
        conn.commit()
        log('Admin', '删除讨论分类', admin_user=admin_user['username'], category_id=cat_id, ip=ip_address)
        return True, '分类已删除'
    except Exception:
        conn.rollback()
        return False, '删除失败'
    finally:
        conn.close()


def get_categories_with_counts():
    """获取分类列表（含帖子数）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM discussion_topics t WHERE t.category_id = c.id) AS topic_count "
            "FROM discussion_categories c ORDER BY c.sort_order ASC, c.id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()