"""游戏账号绑定数据库操作 —— 绑定/解绑/查询 MC 账号与网站用户的关系。"""

from datetime import datetime
from typing import List, Optional

from core.db import get_db


def bind_account(user_id: int, mc_username: str) -> tuple[bool, str]:
    """绑定一个 MC 账号到网站用户。

    Args:
        user_id: 网站用户 ID
        mc_username: MC 玩家名

    Returns:
        (success, message)
    """
    mc_username = mc_username.strip()
    if not mc_username:
        return False, 'MC 用户名不能为空'

    conn = get_db()
    try:
        # 检查是否已被绑定
        existing = conn.execute(
            "SELECT user_id FROM game_account_bindings WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        if existing:
            return False, f'该账号已被其他用户绑定'

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO game_account_bindings (user_id, mc_username, created_at) VALUES (?, ?, ?)",
            (user_id, mc_username, now),
        )
        conn.commit()
        return True, '绑定成功'
    except Exception as e:
        return False, f'绑定失败: {e}'
    finally:
        conn.close()


def unbind_account(user_id: int, mc_username: str) -> tuple[bool, str]:
    """解绑一个 MC 账号。"""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM game_account_bindings WHERE user_id = ? AND mc_username = ?",
            (user_id, mc_username),
        )
        conn.commit()
        return True, '解绑成功'
    except Exception as e:
        return False, f'解绑失败: {e}'
    finally:
        conn.close()


def get_bound_accounts(user_id: int) -> List[dict]:
    """获取用户绑定的所有 MC 账号。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, mc_username, created_at FROM game_account_bindings WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def is_bound(user_id: int, mc_username: str) -> bool:
    """检查某个 MC 账号是否已被特定用户绑定。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM game_account_bindings WHERE user_id = ? AND mc_username = ?",
            (user_id, mc_username),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_binding_by_username(mc_username: str) -> Optional[dict]:
    """通过 MC 用户名查找绑定记录。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_account_bindings WHERE mc_username = ?",
            (mc_username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()