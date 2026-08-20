"""讨论区业务服务：帖子 CRUD、回复 CRUD、置顶/锁定、分类管理。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

import json
import datetime

from core.db import get_db
from config import get_config_value
from services.logger import log
from services.attachment_service import save_attachments, clean_attachment_json, parse_attachment_json, clean_attachments


PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 帖子列表
# ---------------------------------------------------------------------------

def get_topic_count(category_id=None):
    """获取帖子总数（可选按分类筛选）。"""
    conn = get_db()
    try:
        if category_id:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM discussion_topics WHERE category_id = ?",
                (category_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM discussion_topics").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_topics_page(category_id, page):
    """获取分页帖子列表。"""
    if page < 1:
        page = 1
    total = get_topic_count(category_id)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PAGE_SIZE
    conn = get_db()
    try:
        if category_id:
            rows = conn.execute(
                """SELECT t.*, u.username, u.avatar_key, c.name AS category_name,
                          (SELECT COUNT(*) FROM discussion_replies r WHERE r.topic_id = t.id) AS reply_count
                   FROM discussion_topics t
                   JOIN users u ON t.user_id = u.id
                   LEFT JOIN discussion_categories c ON t.category_id = c.id
                   WHERE t.category_id = ?
                   ORDER BY t.is_pinned DESC, t.updated_at DESC
                   LIMIT ? OFFSET ?""",
                (category_id, PAGE_SIZE, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT t.*, u.username, u.avatar_key, c.name AS category_name,
                          (SELECT COUNT(*) FROM discussion_replies r WHERE r.topic_id = t.id) AS reply_count
                   FROM discussion_topics t
                   JOIN users u ON t.user_id = u.id
                   LEFT JOIN discussion_categories c ON t.category_id = c.id
                   ORDER BY t.is_pinned DESC, t.updated_at DESC
                   LIMIT ? OFFSET ?""",
                (PAGE_SIZE, offset)
            ).fetchall()
        topics = [dict(r) for r in rows]
    finally:
        conn.close()

    return topics, total, total_pages


# ---------------------------------------------------------------------------
# 帖子详情
# ---------------------------------------------------------------------------

def get_topic_detail(topic_id):
    """获取帖子详情（含附件解析和浏览量 +1）。返回 dict 或 None。"""
    conn = get_db()
    try:
        topic = conn.execute(
            """SELECT t.*, u.username, u.avatar_key
               FROM discussion_topics t
               JOIN users u ON t.user_id = u.id
               WHERE t.id = ?""",
            (topic_id,)
        ).fetchone()

        if not topic:
            return None

        topic = dict(topic)

        # 解析附件
        topic['attachment'] = parse_attachment_json(topic.get('attachment'))

        # 增加浏览量
        conn.execute(
            "UPDATE discussion_topics SET view_count = view_count + 1 WHERE id = ?",
            (topic_id,)
        )
        conn.commit()

        # 获取回复统计
        total_replies = conn.execute(
            "SELECT COUNT(*) AS c FROM discussion_replies WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()['c']

        last_reply_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM discussion_replies WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()['max_id']

        cat_dict = get_category_dict()
        topic['category_name'] = cat_dict.get(topic.get('category_id'), '')

        return topic, total_replies, last_reply_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 创建帖子
# ---------------------------------------------------------------------------

def create_topic(user_id, username, title, content, category_id, tags, attachment_files, ip_address):
    """创建帖子。返回 (success, message_or_data)。"""

    if not title or len(title) > 200:
        return False, '标题长度应为 1-200 字符'
    if not content:
        return False, '请输入内容'

    attachment_names = save_attachments(attachment_files)
    attachment_json = json.dumps(attachment_names) if attachment_names else None

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO discussion_topics
               (user_id, category_id, title, content, tags, attachment, is_pinned, is_locked, view_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)""",
            (user_id, category_id, title, content, tags, attachment_json, now, now)
        )
        conn.commit()
        log('Discussion', '发帖成功', user_id=user_id, username=username,
            title=title, category_id=category_id, ip=ip_address)
        return True, '发帖成功'
    except Exception:
        conn.rollback()
        clean_attachment_json(attachment_json)
        log('Discussion', '发帖失败', user_id=user_id, username=username,
            title=title, ip=ip_address)
        return False, '发帖失败，请稍后重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 编辑帖子
# ---------------------------------------------------------------------------

def edit_topic(topic_id, user_id, username, title, content, category_id, tags, ip_address):
    """编辑帖子。返回 (success, message)。"""
    if not title or len(title) > 200:
        return False, '标题长度应为 1-200 字符'
    if not content:
        return False, '请输入内容'

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        conn.execute(
            "UPDATE discussion_topics SET title=?, content=?, category_id=?, tags=?, updated_at=? WHERE id=?",
            (title, content, category_id, tags, now, topic_id)
        )
        conn.commit()
        log('Discussion', '编辑帖子成功', user_id=user_id, username=username,
            topic_id=topic_id, ip=ip_address)
        return True, '编辑成功'
    except Exception:
        conn.rollback()
        log('Discussion', '编辑帖子失败', user_id=user_id, username=username,
            topic_id=topic_id, ip=ip_address)
        return False, '编辑失败，请稍后重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 删除帖子（级联清理回复和附件）
# ---------------------------------------------------------------------------

def delete_topic(topic_id, caller_user_id, is_admin, ip_address):
    """删除帖子及其所有回复。返回 (success, message)。"""
    conn = get_db()
    try:
        topic = conn.execute(
            "SELECT * FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            return False, '帖子不存在'

        if topic['user_id'] != caller_user_id and not is_admin:
            return False, '无权限'

        # 清理帖子附件
        if topic['attachment']:
            clean_attachment_json(topic['attachment'])

        # 清理所有回复附件
        replies = conn.execute(
            "SELECT attachment FROM discussion_replies WHERE topic_id = ?", (topic_id,)
        ).fetchall()
        for r in replies:
            if r['attachment']:
                clean_attachment_json(r['attachment'])

        conn.execute("DELETE FROM discussion_replies WHERE topic_id = ?", (topic_id,))
        conn.execute("DELETE FROM discussion_topics WHERE id = ?", (topic_id,))
        conn.commit()
        log('Discussion', '删除帖子', user_id=caller_user_id, topic_id=topic_id, ip=ip_address)
        return True, '帖子已删除'
    except Exception:
        conn.rollback()
        log('Discussion', '删除帖子失败', user_id=caller_user_id, topic_id=topic_id, ip=ip_address)
        return False, '删除失败'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 回复帖子
# ---------------------------------------------------------------------------

def reply_to_topic(user_id, username, topic_id, content, attachment_files, ip_address):
    """回复帖子。返回 (success, message)。"""
    if not content or len(content) > 10000:
        return False, '内容长度应为 1-10000 字符'

    conn = get_db()
    attachment_names = []
    try:
        topic = conn.execute(
            "SELECT id, is_locked FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            return False, '帖子不存在'
        if topic['is_locked']:
            return False, '帖子已锁定，无法回复'

        attachment_names = save_attachments(attachment_files)
        attachment_json = json.dumps(attachment_names) if attachment_names else None

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO discussion_replies (topic_id, user_id, content, attachment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, user_id, content, attachment_json, now, now)
        )
        conn.execute("UPDATE discussion_topics SET updated_at = ? WHERE id = ?", (now, topic_id))
        conn.commit()
        log('Discussion', '回复帖子', user_id=user_id, username=username,
            topic_id=topic_id, ip=ip_address)
        return True, '回复成功'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        clean_attachments(attachment_names)
        log('Discussion', '回复帖子失败', user_id=user_id, username=username,
            topic_id=topic_id, ip=ip_address)
        return False, '回复失败，请稍后重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 删除回复
# ---------------------------------------------------------------------------

def delete_reply(reply_id, user_id, is_admin, ip_address):
    """删除回复。返回 (success, message)。"""
    conn = get_db()
    try:
        reply = conn.execute(
            "SELECT * FROM discussion_replies WHERE id = ?", (reply_id,)
        ).fetchone()
        if not reply:
            return False, '回复不存在'

        topic = conn.execute(
            "SELECT user_id FROM discussion_topics WHERE id = ?", (reply['topic_id'],)
        ).fetchone()

        # 作者、帖子作者、管理员可删除
        if reply['user_id'] != user_id and not is_admin and (not topic or topic['user_id'] != user_id):
            return False, '无权限'

        # 清理附件
        if reply['attachment']:
            clean_attachment_json(reply['attachment'])

        conn.execute("DELETE FROM discussion_replies WHERE id = ?", (reply_id,))
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("UPDATE discussion_topics SET updated_at = ? WHERE id = ?", (now, reply['topic_id']))
        conn.commit()
        log('Discussion', '删除回复', user_id=user_id, reply_id=reply_id,
            topic_id=reply['topic_id'], ip=ip_address)
        return True, '回复已删除'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('Discussion', '删除回复失败', user_id=user_id, reply_id=reply_id, ip=ip_address)
        return False, '删除失败'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 置顶 / 锁定
# ---------------------------------------------------------------------------

def toggle_pin(topic_id, ip_address):
    """切换置顶状态。返回 (success, message)。"""
    conn = get_db()
    try:
        topic = conn.execute(
            "SELECT id, is_pinned FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            return False, '帖子不存在'
        new_status = 0 if topic['is_pinned'] else 1
        conn.execute("UPDATE discussion_topics SET is_pinned = ? WHERE id = ?", (new_status, topic_id))
        conn.commit()
        log('Discussion', '切换置顶', topic_id=topic_id, is_pinned=new_status, ip=ip_address)
        return True, '置顶状态已更新'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, '操作失败'
    finally:
        conn.close()


def toggle_lock(topic_id, ip_address):
    """切换锁定状态。返回 (success, message)。"""
    conn = get_db()
    try:
        topic = conn.execute(
            "SELECT id, is_locked FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            return False, '帖子不存在'
        new_status = 0 if topic['is_locked'] else 1
        conn.execute("UPDATE discussion_topics SET is_locked = ? WHERE id = ?", (new_status, topic_id))
        conn.commit()
        log('Discussion', '切换锁定', topic_id=topic_id, is_locked=new_status, ip=ip_address)
        return True, '锁定状态已更新'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, '操作失败'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 回复 API（分页 + 实时刷新）
# ---------------------------------------------------------------------------

def get_replies_page(topic_id, page):
    """分页获取回复。"""
    per_page = get_config_value('REPLIES_PER_PAGE', 10)
    if page < 1:
        page = 1

    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM discussion_replies WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()['c']

        offset = (page - 1) * per_page
        rows = conn.execute(
            """SELECT r.id, r.content, r.attachment, r.created_at, r.user_id, u.username, u.avatar_key
               FROM discussion_replies r
               JOIN users u ON r.user_id = u.id
               WHERE r.topic_id = ?
               ORDER BY r.id ASC
               LIMIT ? OFFSET ?""",
            (topic_id, per_page, offset)
        ).fetchall()

        replies_list = []
        for r in rows:
            rd = dict(r)
            rd['attachment'] = parse_attachment_json(rd.get('attachment'))
            replies_list.append(rd)

        return {
            'replies': replies_list,
            'has_more': (page * per_page) < total,
            'total': total,
        }
    finally:
        conn.close()


def get_new_replies(topic_id, last_id):
    """获取最新回复（仅返回比 last_id 大的）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT r.id, r.content, r.attachment, r.created_at, r.user_id, u.username, u.avatar_key
               FROM discussion_replies r
               JOIN users u ON r.user_id = u.id
               WHERE r.topic_id = ? AND r.id > ?
               ORDER BY r.id ASC""",
            (topic_id, last_id)
        ).fetchall()

        replies_list = []
        for r in rows:
            rd = dict(r)
            rd['attachment'] = parse_attachment_json(rd.get('attachment'))
            replies_list.append(rd)

        return replies_list
    finally:
        conn.close()
