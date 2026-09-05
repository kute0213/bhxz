"""大喇叭音频业务服务 - 查询函数。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组或纯数据。
"""

import os
import re

from core.db import get_db
from config import UPLOAD_MUSIC_DIR
from core.logger import log
from services.music.constants import STATUS_PUBLIC, STATUS_PENDING, STATUS_PRIVATE


def parse_tags(raw):
    """解析/清洗标签：逗号/顿号/空格分隔，去重、去空白、限长（≤10 个，每个 ≤12 字）。

    返回逗号分隔的规范化字符串（如 'BGM,开服,钢琴'），无效输入返回空字符串。
    """
    if not raw or not isinstance(raw, str):
        return ''
    seen, tags = [], set()
    for part in re.split(r'[,，、;；\s]+', raw):
        tag = part.strip()
        if not tag:
            continue
        if tag not in seen:
            seen.append(tag)
        tags.add(tag)
        if len(tags) >= 10:
            break
    # 截断单个过长标签并再次去重
    final, seen2 = [], set()
    for tag in seen[:10]:
        tag = tag[:12]
        if tag not in seen2:
            seen2.add(tag)
            final.append(tag)
    return ','.join(final)


def tags_to_list(tags):
    """将逗号分隔的标签字符串转为列表（模板展示用），空/无效返回空列表。"""
    if not tags or not isinstance(tags, str):
        return []
    return [t for t in (x.strip() for x in tags.split(',')) if t]


def _music_dir(music_id):
    """音频文件所在目录（绝对路径），路径由音频 ID 决定。"""
    return os.path.join(UPLOAD_MUSIC_DIR, str(music_id))


def get_public_musics(keyword=''):
    """获取所有已通过审核的公开音频（游戏内大喇叭列表），支持按名称或标签模糊搜索。"""
    conn = get_db()
    try:
        sql = ("SELECT id, user_id, username, title, tags, status, created_at "
               "FROM music WHERE status = ?")
        params = [STATUS_PUBLIC]
        kw = (keyword or '').strip()
        if kw:
            sql += " AND (title LIKE ? OR tags LIKE ?)"
            params.extend([f'%{kw}%', f'%{kw}%'])
        sql += " ORDER BY id DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_musics(user_id):
    """获取指定用户上传的音频。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, title, tags, status, created_at "
            "FROM music WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_musics():
    """获取所有待审核音频（管理员审核队列）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, title, tags, status, created_at "
            "FROM music WHERE status = ? ORDER BY id DESC",
            (STATUS_PENDING,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_musics():
    """获取全部音频（管理员后台）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, title, tags, status, created_at "
            "FROM music ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_music(music_id):
    """根据 ID 获取音频记录，不存在返回 None。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, username, title, tags, file_path, status, created_at "
            "FROM music WHERE id = ?",
            (music_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_music_file_path(music_id):
    """获取音频 HLS 播放列表文件的绝对路径（不校验是否存在）。"""
    return os.path.join(_music_dir(music_id), 'index.m3u8')


def get_music_mp3_path(music_id):
    """获取音频 MP3（唱片）文件的绝对路径（不校验是否存在）。"""
    return os.path.join(_music_dir(music_id), 'index.mp3')


def get_music_duration_seconds(music_id):
    """读取 HLS 播放列表，返回音频总时长（秒，四舍五入取整）；无法读取返回 None。

    时长由 m3u8 各分片 EXTINF 累计得出，供「复制时长（秒）」按钮使用；
    对所有音频（含历史数据）都适用，无需额外存库。
    """
    playlist_path = get_music_file_path(music_id)
    if not os.path.isfile(playlist_path):
        return None
    total = 0.0
    try:
        with open(playlist_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#EXTINF:'):
                    try:
                        total += float(line.split(':', 1)[1].split(',', 1)[0])
                    except (ValueError, IndexError):
                        pass
    except OSError:
        return None
    if total <= 0:
        return None
    return int(round(total))


def attach_durations(musics):
    """为音频列表中的每个元素补充 duration_seconds 字段（秒），便于模板展示。

    返回原列表（原地补充字段），单个音频时长读取失败时为 None。
    """
    for m in musics or []:
        m['duration_seconds'] = get_music_duration_seconds(m['id'])
    return musics


def get_author_email(music_id):
    """获取音频上传者的邮箱（用于审核结果通知），无邮箱或不存在返回空字符串。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT u.email FROM music m LEFT JOIN users u ON m.user_id = u.id "
            "WHERE m.id = ?",
            (music_id,),
        ).fetchone()
        return (row['email'] or '') if row else ''
    finally:
        conn.close()