"""征集（Board）业务服务：主题 CRUD、回复 CRUD、附件管理。

所有函数均为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

import datetime

from core.db import get_db
from services.logger import log
from services.attachment_service import save_attachments, clean_attachment_json


def create_topic(user_id, username, title, description, ip_address):
    """创建征集主题。返回 (success, message)。"""

    if not title or len(title) > 100:
        return False, '标题长度应为1-100字符'
    if len(description) > 500:
        return False, '描述长度不能超过500字符'

    conn = get_db()
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO board_topics (user_id, title, description, created_at) VALUES (?, ?, ?, ?)",
            (user_id, title, description, now)
        )
        conn.commit()
        log('Board', '创建征集', user_id=user_id, username=username, title=title, ip=ip_address)
        return True, '征集已创建'
    except Exception:
        conn.rollback()
        log('Board', '创建征集失败', user_id=user_id, username=username, title=title, ip=ip_address)
        return False, '创建失败，请重试'
    finally:
        conn.close()


def reply_to_topic(user_id, username, topic_id, content, attachment_files, ip_address):
    """回复征集主题。返回 (success, message)。"""

    if not content or len(content) > 2000:
        return False, '内容长度应为1-2000字符'

    conn = get_db()
    attachment_names = []
    try:
        topic = conn.execute(
            "SELECT id, is_active FROM board_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic or not topic['is_active']:
            return False, '征集不存在或已关闭'

        # 处理附件上传
        attachment_names = save_attachments(attachment_files)
        attachment_json = __import__('json').dumps(attachment_names) if attachment_names else None

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO board_replies (topic_id, user_id, content, attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (topic_id, user_id, content, attachment_json, now)
        )
        conn.commit()
        log('Board', '回复征集', user_id=user_id, username=username, topic_id=topic_id, ip=ip_address)
        return True, '回复成功'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # 清理已上传的附件
        for fname in attachment_names:
            clean_attachment_json(fname)
        log('Board', '回复征集失败', user_id=user_id, username=username, topic_id=topic_id, ip=ip_address)
        return False, '回复失败，请重试'
    finally:
        conn.close()


def delete_topic(topic_id, ip_address):
    """删除征集主题（级联清理回复和附件）。返回 (success, message)。"""

    conn = get_db()
    try:
        # 清理附件
        replies = conn.execute(
            "SELECT attachment FROM board_replies WHERE topic_id = ?", (topic_id,)
        ).fetchall()
        for r in replies:
            if r['attachment']:
                clean_attachment_json(r['attachment'])

        conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (topic_id,))
        conn.execute("DELETE FROM board_topics WHERE id = ?", (topic_id,))
        conn.commit()
        log('Board', '删除征集', topic_id=topic_id, ip=ip_address)
        return True, '征集已删除'
    except Exception:
        conn.rollback()
        log('Board', '删除征集失败', topic_id=topic_id, ip=ip_address)
        return False, '删除失败'
    finally:
        conn.close()


def delete_reply(reply_id, user_id, is_admin, ip_address):
    """删除征集回复。返回 (success, message)。"""

    conn = get_db()
    try:
        reply = conn.execute(
            "SELECT * FROM board_replies WHERE id = ?", (reply_id,)
        ).fetchone()
        if not reply:
            return False, '回复不存在'

        if not is_admin and reply['user_id'] != user_id:
            return False, '无权限'

        # 清理附件
        if reply['attachment']:
            clean_attachment_json(reply['attachment'])

        conn.execute("DELETE FROM board_replies WHERE id = ?", (reply_id,))
        conn.commit()
        log('Board', '删除回复', user_id=user_id, reply_id=reply_id,
            topic_id=reply['topic_id'], ip=ip_address)
        return True, '回复已删除'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('Board', '删除回复失败', user_id=user_id, reply_id=reply_id, ip=ip_address)
        return False, '删除失败'
    finally:
        conn.close()