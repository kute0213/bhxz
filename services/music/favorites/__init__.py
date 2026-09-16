"""大喇叭音频业务服务 - 收藏功能。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

import threading
import time

from core.db import get_db
from services.music.constants import STATUS_PUBLIC, UPLOAD_TASK_TTL
from services.music.queries import get_music


def _now():
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def toggle_favorite(user_id, music_id):
    """收藏 / 取消收藏音频。返回 (success, message, is_favorited)。

    仅已公开的音频可被收藏（收藏「别人的歌」场景）；重复收藏自动取消。
    """
    music = get_music(music_id)
    if not music:
        return False, '音频不存在', False
    if music['status'] != STATUS_PUBLIC:
        return False, '仅可收藏已公开的音频', False

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM music_favorites WHERE user_id = ? AND music_id = ?",
            (user_id, music_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM music_favorites WHERE user_id = ? AND music_id = ?",
                (user_id, music_id),
            )
            conn.commit()
            return True, '已取消收藏', False
        conn.execute(
            "INSERT INTO music_favorites (user_id, music_id, created_at) VALUES (?, ?, ?)",
            (user_id, music_id, _now()),
        )
        conn.commit()
        return True, '已收藏', True
    except Exception as e:
        conn.rollback()
        return False, f'操作失败：{str(e)}', False
    finally:
        conn.close()


def get_favorite_ids(user_id):
    """获取用户已收藏的音频 ID 集合（列表页标记收藏状态用）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT music_id FROM music_favorites WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {int(r['music_id']) for r in rows}
    finally:
        conn.close()


def get_user_favorites(user_id):
    """获取用户收藏的音频列表（含上传者与收藏时间），按收藏时间倒序。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT m.id, m.user_id, m.username, m.title, m.tags, m.status, m.created_at, "
            "f.created_at AS fav_created_at "
            "FROM music_favorites f JOIN music m ON m.id = f.music_id "
            "WHERE f.user_id = ? "
            "ORDER BY f.created_at DESC, m.id DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()