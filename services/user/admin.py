"""用户业务服务 - 管理员操作（删除用户、切换管理员权限）。"""

from core.db import get_db
from core.logger import log
from services.attachment_service import clean_attachment_json
from services.user.profile import _get_user_media_keys, _clean_user_attachments, _clean_user_media


def admin_delete_user(admin_user, target_user_id, ip_address):
    """管理员删除用户，级联清理所有关联数据。返回 (success, message)。"""

    if target_user_id == admin_user['id']:
        return False, '不能删除自己'

    conn = get_db()
    try:
        media_keys = _get_user_media_keys(conn, target_user_id)
        _clean_user_attachments(conn, target_user_id)

        conn.execute("DELETE FROM poll_votes WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM board_replies WHERE user_id = ?", (target_user_id,))
        topic_rows = conn.execute(
            "SELECT id FROM board_topics WHERE user_id = ?", (target_user_id,)
        ).fetchall()
        for tr in topic_rows:
            tid = tr['id']
            conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM board_topics WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))
        conn.commit()
        _clean_user_media(media_keys, target_user_id)
        log('Admin', '删除用户', admin_user=admin_user['username'],
            target_user_id=target_user_id, ip=ip_address)
        return True, '用户已删除'
    except Exception:
        conn.rollback()
        log('Admin', '删除用户失败', admin_user=admin_user['username'],
            target_user_id=target_user_id, ip=ip_address)
        return False, '删除失败，请重试'
    finally:
        conn.close()


def admin_toggle_admin(admin_user, target_user_id, ip_address):
    """切换用户管理员权限。返回 (success, message)。"""

    if target_user_id == admin_user['id']:
        return False, '不能修改自己的管理员权限'

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, is_admin FROM users WHERE id = ?", (target_user_id,)
        ).fetchone()
        if not target:
            return False, '用户不存在'

        new_status = 0 if target['is_admin'] else 1
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, target_user_id))
        conn.commit()
        log('Admin', '切换管理员权限', admin_user=admin_user['username'],
            target_user_id=target_user_id, new_status=new_status, ip=ip_address)
        return True, '管理员权限已更新'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, '操作失败'
    finally:
        conn.close()