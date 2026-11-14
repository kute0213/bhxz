"""音频直播业务服务 - 数据库读写（频道 / 封禁）。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 或纯数据。
"""

from datetime import datetime

from core.db import get_db, transaction
from core.shared.snowflake import next_id
from services.live.constants import (
    MODE_LOOP,
    STATUS_LIVE,
    STATUS_STOPPED,
    VOLUME_DEFAULT,
    SPEED_DEFAULT,
    normalize_speed,
    normalize_title,
    normalize_volume,
)


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row(row):
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# 频道
# ---------------------------------------------------------------------------

def get_channel(channel_id):
    """按 ID 获取频道（不存在返回 None）。"""
    conn = get_db()
    try:
        return _row(conn.execute(
            "SELECT * FROM live_channels WHERE id = ?", (int(channel_id),)
        ).fetchone())
    finally:
        conn.close()


def get_active_channels():
    """所有直播中的频道（公共列表）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM live_channels WHERE status = ? ORDER BY id DESC",
            (STATUS_LIVE,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_channels(limit=100):
    """最近的频道记录（管理端使用）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM live_channels ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_active_channel(user_id):
    """用户当前直播中的频道（每个用户最多 1 个）。"""
    conn = get_db()
    try:
        return _row(conn.execute(
            "SELECT * FROM live_channels WHERE user_id = ? AND status = ? "
            "ORDER BY id DESC LIMIT 1",
            (int(user_id), STATUS_LIVE),
        ).fetchone())
    finally:
        conn.close()


def get_user_channels(user_id, limit=20):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM live_channels WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (int(user_id), int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_channel(user_id, username, title, music_id=None,
                   volume=VOLUME_DEFAULT, speed=SPEED_DEFAULT):
    """创建直播频道记录（单用户单直播在事务内原子校验）。

    Returns:
        (success, channel_dict_or_error)
    """
    title = normalize_title(title)
    if not title:
        return False, '请填写直播标题'

    volume = normalize_volume(volume)
    speed = normalize_speed(speed)

    try:
        music_id = int(music_id)
    except (TypeError, ValueError):
        return False, '请选择要循环播放的音频'

    channel_id = next_id()
    now = _now()

    with transaction() as conn:
        if conn.execute(
            "SELECT 1 FROM live_bans WHERE user_id = ?", (int(user_id),)
        ).fetchone():
            return False, '你已被管理员禁止开播'

        if conn.execute(
            "SELECT 1 FROM live_channels WHERE user_id = ? AND status = ?",
            (int(user_id), STATUS_LIVE),
        ).fetchone():
            return False, '你已有一个正在进行的直播，请先停止后再开播'

        music = conn.execute(
            "SELECT id, user_id, status FROM music WHERE id = ?", (music_id,)
        ).fetchone()
        if not music:
            return False, '选择的音频不存在'
        if music['user_id'] != int(user_id):
            return False, '只能循环播放自己上传的音频'
        if music['status'] == 3:
            return False, '该音频已被驳回，无法用于直播'

        conn.execute(
            "INSERT INTO live_channels "
            "(id, user_id, username, title, mode, music_id, volume, speed, "
            " status, created_at, updated_at, stopped_at, stop_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '')",
            (
                channel_id, int(user_id), username or '', title, MODE_LOOP,
                music_id, volume, speed, STATUS_LIVE, now, now,
            ),
        )

    return True, {
        'id': int(channel_id),
        'user_id': int(user_id),
        'username': username or '',
        'title': title,
        'music_id': music_id,
        'volume': volume,
        'speed': speed,
        'status': STATUS_LIVE,
        'created_at': now,
        'updated_at': now,
    }


def update_channel_settings(channel_id, volume=None, speed=None):
    """更新直播的音量 / 速度（只更新传入的字段）。"""
    sets, params = [], []
    if volume is not None:
        sets.append('volume = ?')
        params.append(normalize_volume(volume))
    if speed is not None:
        sets.append('speed = ?')
        params.append(normalize_speed(speed))
    if not sets:
        return True, '没有需要更新的设置'

    sets.append('updated_at = ?')
    params.append(_now())
    params.append(int(channel_id))

    conn = get_db()
    try:
        conn.execute(
            f"UPDATE live_channels SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        conn.commit()
        return True, '设置已更新'
    finally:
        conn.close()


def mark_stopped(channel_id, reason=''):
    """将频道标记为已停止（幂等）。"""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE live_channels SET status = ?, stopped_at = ?, "
            "stop_reason = ?, updated_at = ? "
            "WHERE id = ? AND status = ?",
            (STATUS_STOPPED, _now(), (reason or '')[:200], _now(),
             int(channel_id), STATUS_LIVE),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 封禁
# ---------------------------------------------------------------------------

def is_banned(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT 1 FROM live_bans WHERE user_id = ?", (int(user_id),)
        ).fetchone() is not None
    finally:
        conn.close()


def get_ban(user_id):
    conn = get_db()
    try:
        return _row(conn.execute(
            "SELECT * FROM live_bans WHERE user_id = ?", (int(user_id),)
        ).fetchone())
    finally:
        conn.close()


def list_bans():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM live_bans ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def ban_user(user_id, username, reason, banned_by):
    """永久禁止某用户开播（重复封禁则更新理由）。"""
    now = _now()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO live_bans (user_id, username, reason, banned_by, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username = excluded.username, reason = excluded.reason, "
            "banned_by = excluded.banned_by, created_at = excluded.created_at",
            (int(user_id), username or '', (reason or '')[:200], int(banned_by), now),
        )
    return True, '已禁止该用户开播'


def unban_user(user_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM live_bans WHERE user_id = ?", (int(user_id),))
        conn.commit()
        if cur.rowcount == 0:
            return False, '该用户未被封禁'
        return True, '已解除直播封禁'
    finally:
        conn.close()


def find_user_by_username(username):
    """按用户名查找未注销用户（管理端封禁使用）。"""
    username = (username or '').strip()
    if not username:
        return None
    conn = get_db()
    try:
        return _row(conn.execute(
            "SELECT id, username FROM users "
            "WHERE lower(username) = lower(?) AND is_deleted = 0 LIMIT 1",
            (username,),
        ).fetchone())
    finally:
        conn.close()
