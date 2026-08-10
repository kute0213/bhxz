"""投票业务服务：创建、投票、删除、启停。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

import datetime

from core.db import get_db
from services.logger import log


def create_poll(user_id, username, title, description, options_text, is_multiple, ip_address):
    """创建投票。返回 (success, message)。"""

    if not title or not options_text:
        return False, '请填写完整信息'

    options = [line.strip() for line in options_text.split('\n') if line.strip()]
    if len(options) < 2:
        return False, '至少需要2个选项'

    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "INSERT INTO polls (title, description, is_multiple, created_at) VALUES (?, ?, ?, ?)",
            (title, description, is_multiple, now)
        )
        poll_id = cursor.lastrowid
        for opt in options:
            cursor.execute(
                "INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)",
                (poll_id, opt)
            )
        conn.commit()
        log('Poll', '创建投票', user_id=user_id, username=username, title=title, ip=ip_address)
        return True, '投票已创建'
    except Exception:
        conn.rollback()
        log('Poll', '创建投票失败', user_id=user_id, username=username, title=title, ip=ip_address)
        return False, '创建失败，请重试'
    finally:
        conn.close()


def vote_poll(poll_id, user_id, username, option_ids, ip_address):
    """投票。返回 (success, message)。"""

    if not option_ids:
        return False, '请至少选择一个选项'

    conn = get_db()
    try:
        poll = conn.execute(
            "SELECT * FROM polls WHERE id = ?", (poll_id,)
        ).fetchone()
        if not poll or not poll['is_active']:
            return False, '投票不存在或已结束'

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 检查是否已投过票
        already_voted = conn.execute(
            "SELECT id FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        ).fetchone()
        if already_voted:
            return False, '你已经投过票了'

        for option_id in option_ids:
            option = conn.execute(
                "SELECT id FROM poll_options WHERE id = ? AND poll_id = ?",
                (option_id, poll_id)
            ).fetchone()
            if option:
                conn.execute(
                    "INSERT OR IGNORE INTO poll_votes (poll_id, user_id, option_id, created_at) VALUES (?, ?, ?, ?)",
                    (poll_id, user_id, option_id, now)
                )
                conn.execute(
                    "UPDATE poll_options SET vote_count = vote_count + 1 WHERE id = ?",
                    (option_id,)
                )

        conn.commit()
        log('Poll', '投票成功', user_id=user_id, username=username, poll_id=poll_id, ip=ip_address)
        return True, '投票成功'
    except Exception:
        conn.rollback()
        log('Poll', '投票失败', user_id=user_id, username=username, poll_id=poll_id, ip=ip_address)
        return False, '投票失败，请重试'
    finally:
        conn.close()


def delete_poll(poll_id, ip_address):
    """删除投票（级联清理选项和投票记录）。返回 (success, message)。"""

    conn = get_db()
    try:
        conn.execute("DELETE FROM poll_votes WHERE poll_id = ?", (poll_id,))
        conn.execute("DELETE FROM poll_options WHERE poll_id = ?", (poll_id,))
        conn.execute("DELETE FROM polls WHERE id = ?", (poll_id,))
        conn.commit()
        log('Poll', '删除投票', poll_id=poll_id, ip=ip_address)
        return True, '投票已删除'
    except Exception:
        conn.rollback()
        log('Poll', '删除投票失败', poll_id=poll_id, ip=ip_address)
        return False, '删除失败'
    finally:
        conn.close()


def toggle_poll(poll_id, ip_address):
    """切换投票启停状态。返回 (success, message)。"""

    conn = get_db()
    try:
        poll = conn.execute(
            "SELECT * FROM polls WHERE id = ?", (poll_id,)
        ).fetchone()
        if not poll:
            return False, '投票不存在'

        new_status = 0 if poll['is_active'] else 1
        conn.execute("UPDATE polls SET is_active = ? WHERE id = ?", (new_status, poll_id))
        conn.commit()
        log('Poll', '切换投票状态', poll_id=poll_id, new_active=new_status, ip=ip_address)
        return True, '投票状态已更新'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('Poll', '切换投票状态失败', poll_id=poll_id, ip=ip_address)
        return False, '操作失败'
    finally:
        conn.close()