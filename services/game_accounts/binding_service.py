"""游戏账号绑定数据库操作 —— 绑定、解绑、查询。"""

from datetime import datetime
from typing import List, Optional, Tuple

from core.db import get_db


def get_user_bindings(user_id: int) -> List[dict]:
    """获取用户的所有已绑定账号。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, mc_username, created_at FROM game_account_bindings WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_binding_by_id(binding_id: int) -> Optional[dict]:
    """按 ID 获取绑定记录。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, mc_username, created_at FROM game_account_bindings WHERE id = ?",
            (binding_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_binding(user_id: int, mc_username: str) -> Tuple[bool, str]:
    """创建绑定记录。

    Args:
        user_id: 网站用户 ID
        mc_username: MC 用户名

    Returns:
        (success, message_or_data)
    """
    # 一个网站账号只能绑定一个服务器账号，已绑定时需先解绑
    if get_user_bindings(user_id):
        return False, '一个网站账号只能绑定一个服务器账号，请先解绑当前账号'

    # 该 MC 账号已被其他用户绑定
    if is_mc_username_bound(mc_username):
        return False, '该 MC 账号已被其他用户绑定'

    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute(
            "INSERT INTO game_account_bindings (user_id, mc_username, created_at) VALUES (?, ?, ?)",
            (user_id, mc_username, now),
        )
        if cursor.rowcount == 0:
            return False, '绑定失败，请重试'
        conn.commit()
        return True, mc_username
    except Exception as e:
        return False, f'绑定失败: {e}'
    finally:
        conn.close()


def unbind_account(binding_id: int, user_id: int) -> Tuple[bool, str]:
    """解绑游戏账号。

    Args:
        binding_id: 绑定记录 ID
        user_id: 当前用户 ID（用于验证所有权）

    Returns:
        (success, message)
    """
    binding = get_binding_by_id(binding_id)
    if not binding:
        return False, '绑定记录不存在'
    if binding['user_id'] != user_id:
        return False, '无权解绑此账号'

    mc_username = binding['mc_username']
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM game_account_bindings WHERE id = ? AND user_id = ?",
            (binding_id, user_id),
        )
        if cursor.rowcount == 0:
            return False, '解绑失败，请重试'
        conn.commit()
        return True, f'已成功解绑账号 {mc_username}'
    except Exception as e:
        return False, f'解绑失败: {e}'
    finally:
        conn.close()


def get_all_bindings() -> List[dict]:
    """获取所有绑定记录（含用户名），用于管理员后台。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT b.id, b.mc_username, b.user_id, u.username AS site_username, b.created_at "
            "FROM game_account_bindings b "
            "LEFT JOIN users u ON b.user_id = u.id "
            "ORDER BY b.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def is_bound_to_user(mc_username: str, user_id: int) -> bool:
    """检查 MC 用户名是否已被指定用户绑定。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM game_account_bindings WHERE mc_username = ? AND user_id = ?",
            (mc_username, user_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def is_mc_username_bound(mc_username: str) -> bool:
    """检查 MC 用户名是否已被绑定。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM game_account_bindings WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()