"""游戏账号注册申请数据库操作 —— 申请、审批、封禁。

密码存储使用 Fernet 加密（基于 Flask SECRET_KEY），
审批通过后解密并执行 RCON 注册，注册后彻底删除密码。
"""

import base64
import hashlib
import os
from datetime import datetime
from typing import List, Optional, Tuple

from cryptography.fernet import Fernet

from core.db import get_db
from config import SECRET_KEY


def _get_fernet() -> Fernet:
    """从 SECRET_KEY 派生 Fernet 密钥。"""
    key = hashlib.sha256(SECRET_KEY.encode('utf-8')).digest()
    key_b64 = base64.urlsafe_b64encode(key)
    return Fernet(key_b64)


def encrypt_password(password: str) -> str:
    """加密密码。"""
    return _get_fernet().encrypt(password.encode('utf-8')).decode('utf-8')


def decrypt_password(encrypted: str) -> str:
    """解密密码。"""
    return _get_fernet().decrypt(encrypted.encode('utf-8')).decode('utf-8')


# ---------------------------------------------------------------------------
# 注册申请
# ---------------------------------------------------------------------------

def create_application(user_id: int, mc_username: str, password: str) -> Tuple[bool, str]:
    """创建游戏账号注册申请。

    Args:
        user_id: 网站用户 ID
        mc_username: 申请的 MC 用户名
        password: 密码（明文，内部加密存储）

    Returns:
        (success, message)
    """
    from services.validation import validate_mc_username, validate_game_password

    mc_username = mc_username.strip()
    valid_mc, mc_err = validate_mc_username(mc_username)
    if not valid_mc:
        return False, mc_err

    valid_pwd, pwd_err = validate_game_password(password, min_length=8)
    if not valid_pwd:
        return False, pwd_err

    conn = get_db()
    try:
        # 检查是否已被封禁
        banned = conn.execute(
            "SELECT id FROM game_account_bans WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        if banned:
            return False, '该账号已被禁止申请注册'

        # 检查是否有待处理的申请
        existing = conn.execute(
            "SELECT id FROM game_account_registrations WHERE mc_username = ? AND status = 'pending'",
            (mc_username,),
        ).fetchone()
        if existing:
            return False, '该账号已有待处理的注册申请'

        # 检查是否已被绑定
        bound = conn.execute(
            "SELECT id FROM game_account_bindings WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        if bound:
            return False, '该账号已被绑定'

        encrypted = encrypt_password(password)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """INSERT INTO game_account_registrations
               (user_id, mc_username, encrypted_password, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (user_id, mc_username, encrypted, now),
        )
        conn.commit()
        return True, '注册申请已提交，等待管理员审核'
    except Exception as e:
        return False, f'提交申请失败: {e}'
    finally:
        conn.close()


def get_pending_applications() -> List[dict]:
    """获取所有待审批的注册申请。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT r.id, r.user_id, r.mc_username, r.created_at, u.username AS applicant
               FROM game_account_registrations r
               JOIN users u ON r.user_id = u.id
               WHERE r.status = 'pending'
               ORDER BY r.created_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_applications() -> List[dict]:
    """获取所有注册申请记录（含已处理）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT r.id, r.user_id, r.mc_username, r.status,
                      r.created_at, r.reviewed_at, r.reject_reason,
                      u.username AS applicant, ru.username AS reviewer
               FROM game_account_registrations r
               JOIN users u ON r.user_id = u.id
               LEFT JOIN users ru ON r.reviewed_by = ru.id
               ORDER BY r.created_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_application_by_id(app_id: int) -> Optional[dict]:
    """获取单个申请详情。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_account_registrations WHERE id = ?",
            (app_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def approve_application(app_id: int, reviewer_id: int) -> Tuple[bool, str]:
    """审批通过注册申请，执行 RCON 注册。

    解密密码后执行 RCON 注册，成功后彻底删除密文。

    Returns:
        (success, message)
    """
    app = get_application_by_id(app_id)
    if not app:
        return False, '申请不存在'
    if app['status'] != 'pending':
        return False, '该申请已处理'

    from services.rcon.easy_auth import register_player

    # 解密密码并执行 RCON 注册
    try:
        password = decrypt_password(app['encrypted_password'])
    except Exception:
        return False, '密码解密失败，请联系管理员'

    succ, msg = register_player(app['mc_username'], password)
    if not succ:
        return False, f'RCON 注册失败: {msg}'

    # 更新数据库状态
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        conn.execute(
            """UPDATE game_account_registrations
               SET status = 'approved', reviewed_by = ?, reviewed_at = ?, encrypted_password = ''
               WHERE id = ?""",
            (reviewer_id, now, app_id),
        )
        conn.commit()
        return True, f'已批准并注册账号 {app["mc_username"]}'
    except Exception as e:
        return False, f'更新数据库失败: {e}'
    finally:
        conn.close()


def reject_application(app_id: int, reviewer_id: int, reason: str = '') -> Tuple[bool, str]:
    """驳回注册申请。"""
    app = get_application_by_id(app_id)
    if not app:
        return False, '申请不存在'
    if app['status'] != 'pending':
        return False, '该申请已处理'

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        conn.execute(
            """UPDATE game_account_registrations
               SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,
                   reject_reason = ?, encrypted_password = ''
               WHERE id = ?""",
            (reviewer_id, now, reason, app_id),
        )
        conn.commit()
        return True, '已驳回申请'
    except Exception as e:
        return False, f'操作失败: {e}'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 封禁管理
# ---------------------------------------------------------------------------

def ban_account(mc_username: str, reason: str, created_by: int) -> Tuple[bool, str]:
    """禁止某个 MC 用户名申请注册。"""
    mc_username = mc_username.strip()
    if not mc_username:
        return False, 'MC 用户名不能为空'

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM game_account_bans WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        if existing:
            return False, '该账号已被封禁'

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO game_account_bans (mc_username, reason, created_at, created_by) VALUES (?, ?, ?, ?)",
            (mc_username, reason, now, created_by),
        )
        conn.commit()
        return True, f'已封禁账号 {mc_username}'
    except Exception as e:
        return False, f'封禁失败: {e}'
    finally:
        conn.close()


def unban_account(mc_username: str) -> Tuple[bool, str]:
    """解除封禁。"""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM game_account_bans WHERE mc_username = ?",
            (mc_username,),
        )
        conn.commit()
        return True, f'已解除封禁 {mc_username}'
    except Exception as e:
        return False, f'解封失败: {e}'
    finally:
        conn.close()


def get_banned_accounts() -> List[dict]:
    """获取所有被封禁的账号。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT b.id, b.mc_username, b.reason, b.created_at, u.username AS created_by_name
               FROM game_account_bans b
               LEFT JOIN users u ON b.created_by = u.id
               ORDER BY b.created_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def is_banned(mc_username: str) -> bool:
    """检查 MC 用户名是否被封禁。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM game_account_bans WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()