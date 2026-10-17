"""用户业务服务 - 管理员操作（删除用户、切换管理员权限）。"""

from datetime import datetime

from core.db import get_db
from core.shared.validation import DELETED_USER_DISPLAY_NAME
from core.system.logger import log_module, register_module_log
from services.user.profiles import _get_user_media_keys, _clean_user_media

register_module_log('user')


def admin_delete_user(admin_user, target_user_id, ip_address):
    """管理员删除用户（软删除）。返回 (success, message)。

    与用户自助注销一致：保留用户行与 ID，发布过的内容不删除；
    用户名替换为「账号已注销」、清空凭据并置 is_deleted = 1，
    该账号随即无法登录，已登录会话下次请求即失效。
    """

    if target_user_id == admin_user['id']:
        return False, '不能删除自己'

    conn = get_db()
    try:
        media_keys = _get_user_media_keys(conn, target_user_id)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE users SET username = ?, password_hash = '', email = '', "
            "avatar_key = '', login_attempts = 0, locked_until = '', "
            "is_deleted = 1, deleted_at = ? WHERE id = ? AND is_deleted = 0",
            (DELETED_USER_DISPLAY_NAME, now, target_user_id),
        )
        conn.commit()
        _clean_user_media(media_keys, target_user_id)
        log_module('user', 'INFO', 'Admin', '删除用户（软删除，内容保留）', admin_user=admin_user['username'],
            target_user_id=target_user_id, ip=ip_address)
        return True, '用户已删除'
    except Exception:
        conn.rollback()
        log_module('user', 'ERROR', 'Admin', '删除用户失败', admin_user=admin_user['username'],
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
        log_module('user', 'INFO', 'Admin', '切换管理员权限', admin_user=admin_user['username'],
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