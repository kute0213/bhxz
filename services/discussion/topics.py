"""讨论区业务服务 - 帖子管理（列表、详情、创建、编辑、删除、置顶、锁定）。"""

import json
import datetime

from core.db import get_db
from core.logger import log
from services.attachment_service import save_attachments, clean_attachment_json, parse_attachment_json, clean_attachments
from services.discussion.categories import get_category_dict

PAGE_SIZE = 20


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
        topic['attachment'] = parse_attachment_json(topic.get('attachment'))

        conn.execute(
            "UPDATE discussion_topics SET view_count = view_count + 1 WHERE id = ?",
            (topic_id,)
        )
        conn.commit()

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


def create_topic(user_id, username, title, content, category_id, tags, attachment_files, ip_address):
    """创建帖子。返回 (success, message_or_data)。"""

    if not title or len(title) > 200:
        return False, '标题长度应为 1-200 字符'
    if not content:
        return False, '请输入内容'

    try:
        attachment_names = save_attachments(attachment_files)
    except ValueError as e:
        return False, str(e)
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

        if topic['attachment']:
            clean_attachment_json(topic['attachment'])

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