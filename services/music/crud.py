"""大喇叭音频业务服务 - CRUD 操作（删除、公开切换、审核、标签编辑）。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

import shutil
import os

from core.db import get_db
from core.logger import log
from services.music.constants import STATUS_PRIVATE, STATUS_PENDING, STATUS_PUBLIC
from services.music.queries import get_music, _music_dir, parse_tags


def delete_music(music_id, user_id, is_admin, ip_address):
    """删除音频：先删除数据库记录，再删除文件目录。返回 (success, message)。

    权限：管理员可删除任意音频；普通用户仅可删除自己上传的音频。
    """
    music = get_music(music_id)
    if not music:
        return False, '音频不存在'

    if not is_admin and music['user_id'] != user_id:
        return False, '无权删除该音频'

    conn = get_db()
    try:
        conn.execute("DELETE FROM music WHERE id = ?", (music_id,))
        # 同步清理该音频的所有收藏记录，避免残留脏数据
        conn.execute("DELETE FROM music_favorites WHERE music_id = ?", (music_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return False, '删除失败'
    conn.close()

    # 数据库记录删除后，同步删除音频文件目录
    file_removed = True
    final_dir = _music_dir(music_id)
    if os.path.isdir(final_dir):
        try:
            shutil.rmtree(final_dir, ignore_errors=False)
        except OSError:
            file_removed = False

    log('Music', '删除大喇叭音频', music_id=music_id, user_id=user_id,
        is_admin=is_admin, file_removed=file_removed, ip=ip_address)
    if not file_removed:
        return True, '音频已删除，但文件目录清理失败，请手动检查'
    return True, '音频已删除'


def toggle_music_public(music_id, user_id, is_admin, ip_address):
    """切换音频公开/私有状态。返回 (success, message)。

    - 私有 → 申请公开（进入待审核，管理员审核通过后才公开）
    - 待审核 / 已公开 / 历史已驳回 → 转为私有（仅自己可见）
    """
    music = get_music(music_id)
    if not music:
        return False, '音频不存在'

    if not is_admin and music['user_id'] != user_id:
        return False, '无权修改该音频'

    # 私有 → 申请公开（待审核）；其余状态 → 转为私有
    if music['status'] == STATUS_PRIVATE:
        new_status = STATUS_PENDING
    else:
        new_status = STATUS_PRIVATE

    conn = get_db()
    try:
        conn.execute(
            "UPDATE music SET status = ? WHERE id = ?",
            (new_status, music_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return False, '修改失败'
    conn.close()

    log('Music', '切换音频公开状态', music_id=music_id, user_id=user_id,
        status=new_status, ip=ip_address)
    if new_status == STATUS_PRIVATE:
        return True, '已转为私有，仅自己可见'
    return True, '已申请公开，审核通过后将展示在游戏内大喇叭音频列表'


def review_music(music_id, approve, reviewer_username, ip_address):
    """管理员审核公开申请。返回 (success, message)。

    approve=True 通过 → 已公开；approve=False 驳回 → 自动转为私有
    （用户仍可在「我的音频」中重新申请公开或删除）。
    仅待审核状态的音频可被审核。
    """
    music = get_music(music_id)
    if not music:
        return False, '音频不存在'
    if music['status'] != STATUS_PENDING:
        return False, '该音频不在待审核状态'

    new_status = STATUS_PUBLIC if approve else STATUS_PRIVATE
    conn = get_db()
    try:
        conn.execute(
            "UPDATE music SET status = ? WHERE id = ?",
            (new_status, music_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return False, '操作失败'
    conn.close()

    log('Music', '审核公开音频', music_id=music_id, approve=approve,
        reviewer=reviewer_username, title=music['title'], ip=ip_address)
    if approve:
        return True, '已通过审核，音频已在游戏内大喇叭公开'
    return True, '已驳回，音频已转为私有，用户可重新申请公开'


def set_music_tags(music_id, user_id, is_admin, tags, ip_address):
    """编辑音频标签。权限：管理员可改任意；普通用户仅可改自己上传的。返回 (success, message)。"""
    music = get_music(music_id)
    if not music:
        return False, '音频不存在'
    if not is_admin and music['user_id'] != user_id:
        return False, '无权修改该音频'

    normalized = parse_tags(tags)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE music SET tags = ? WHERE id = ?",
            (normalized, music_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return False, '保存标签失败'
    conn.close()

    log('Music', '编辑音频标签', music_id=music_id, user_id=user_id,
        is_admin=is_admin, tags=normalized, ip=ip_address)
    return True, '标签已保存'