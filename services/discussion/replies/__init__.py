"""讨论区业务服务 - 回复管理（回复、删除、分页、实时刷新）。"""

import json
import datetime

from core.db import get_db
from config import get_page_size
from core.system.logger import log
from services.attachment_service import save_attachments, clean_attachment_json, parse_attachment_json, clean_attachments


def reply_to_topic(user_id, username, topic_id, content, attachment_files, ip_address):
    """回复帖子。返回 (success, message, reply)。

    reply 为新建回复的 dict（含 id/content/attachment/created_at/username/avatar_key），
    供前端无刷新插入列表；失败时为 None。
    """
    if not content or len(content) > 10000:
        return False, '内容长度应为 1-10000 字符', None

    conn = get_db()
    attachment_names = []
    try:
        topic = conn.execute(
            "SELECT id, is_locked FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            return False, '帖子不存在', None
        if topic['is_locked']:
            return False, '帖子已锁定，无法回复', None
        avatar_row = conn.execute(
            "SELECT avatar_key FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        avatar_key = avatar_row['avatar_key'] if avatar_row else None
    finally:
        conn.close()

    try:
        attachment_names = save_attachments(attachment_files)
    except ValueError as e:
        return False, str(e), None

    conn = get_db()
    try:
        attachment_json = json.dumps(attachment_names) if attachment_names else None

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute(
            "INSERT INTO discussion_replies (topic_id, user_id, content, attachment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, user_id, content, attachment_json, now, now)
        )
        reply_id = cursor.lastrowid
        conn.execute("UPDATE discussion_topics SET updated_at = ? WHERE id = ?", (now, topic_id))
        conn.commit()
        log('INFO', 'Discussion', '回复帖子', user_id=user_id, username=username,
            topic_id=topic_id, ip=ip_address)
        reply = {
            'id': reply_id,
            'content': content,
            'attachment': attachment_names,
            'created_at': now,
            'user_id': user_id,
            'username': username,
            'avatar_key': avatar_key,
        }
        return True, '回复成功', reply
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        clean_attachments(attachment_names)
        log('ERROR', 'Discussion', '回复帖子失败', user_id=user_id, username=username,
            topic_id=topic_id, ip=ip_address)
        return False, '回复失败，请稍后重试', None
    finally:
        conn.close()


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

        if reply['user_id'] != user_id and not is_admin and (not topic or topic['user_id'] != user_id):
            return False, '无权限'

        if reply['attachment']:
            clean_attachment_json(reply['attachment'])

        conn.execute("DELETE FROM discussion_replies WHERE id = ?", (reply_id,))
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("UPDATE discussion_topics SET updated_at = ? WHERE id = ?", (now, reply['topic_id']))
        conn.commit()
        log('INFO', 'Discussion', '删除回复', user_id=user_id, reply_id=reply_id,
            topic_id=reply['topic_id'], ip=ip_address)
        return True, '回复已删除'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('ERROR', 'Discussion', '删除回复失败', user_id=user_id, reply_id=reply_id, ip=ip_address)
        return False, '删除失败'
    finally:
        conn.close()


def get_replies_page(topic_id, page):
    """分页获取回复（每页数量由系统设置 REPLIES_PER_PAGE 控制，API 无法覆盖）。"""
    per_page = get_page_size('REPLIES_PER_PAGE', 5)
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