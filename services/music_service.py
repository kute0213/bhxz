"""大喇叭音频业务服务：上传转码 HLS、列表查询、删除（数据库记录删除同步删除文件）。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
音频文件存放在 uploads/music/<音频ID>/ 目录，播放链接格式：
http://<主机>/music/<音频ID>.m3u8
"""

import os
import shutil
import subprocess
import uuid
from datetime import datetime

from core.db import get_db
from config import UPLOAD_MUSIC_DIR, MUSIC_ALLOWED_EXTENSIONS, FFMPEG_BIN
from services.logger import log

# HLS 分片时长（秒）
HLS_SEGMENT_SECONDS = 10

# 音频状态：0=私有 1=待审核 2=已公开 3=已驳回
STATUS_PRIVATE = 0
STATUS_PENDING = 1
STATUS_PUBLIC = 2
STATUS_REJECTED = 3

# 状态显示文案
STATUS_LABELS = {
    STATUS_PRIVATE: '私有',
    STATUS_PENDING: '待审核',
    STATUS_PUBLIC: '已公开',
    STATUS_REJECTED: '已驳回',
}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _music_dir(music_id):
    """音频文件所在目录（绝对路径），路径由音频 ID 决定。"""
    return os.path.join(UPLOAD_MUSIC_DIR, str(music_id))


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def get_public_musics():
    """获取所有已通过审核的公开音频（游戏内大喇叭列表）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, title, status, created_at "
            "FROM music WHERE status = ? ORDER BY id DESC",
            (STATUS_PUBLIC,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_musics(user_id):
    """获取指定用户上传的音频。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, title, status, created_at "
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
            "SELECT id, user_id, username, title, status, created_at "
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
            "SELECT id, user_id, username, title, status, created_at "
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
            "SELECT id, user_id, username, title, file_path, status, created_at "
            "FROM music WHERE id = ?",
            (music_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_music_file_path(music_id):
    """获取音频 HLS 播放列表文件的绝对路径（不校验是否存在）。"""
    return os.path.join(_music_dir(music_id), 'index.m3u8')


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


# ---------------------------------------------------------------------------
# 上传 / 转码
# ---------------------------------------------------------------------------

def _rewrite_playlist_segments(playlist_path, music_id):
    """将 m3u8 中的相对分片路径改写为绝对 URL 路径（/music/<id>/<分片>.ts）。

    播放器（含游戏端）以 m3u8 的 URL（/music/<id>.m3u8）为基准解析分片，
    相对路径会解析到 /music/seg_000.ts 导致 404，因此改为绝对路径。
    """
    with open(playlist_path, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        if line and not line.startswith('#') and line.endswith('.ts'):
            out.append(f'/music/{music_id}/{os.path.basename(line)}')
        else:
            out.append(line)
    with open(playlist_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')


def upload_music(user_id, username, title, is_public, upload_file, ip_address):
    """上传音频并转码为 HLS（m3u8）。返回 (success, data_or_error)。

    流程：保存源文件 → ffmpeg 转码 HLS → 插入数据库记录获取 ID →
    改写 m3u8 分片为绝对 URL → 临时目录重命名为 <ID> 目录。
    任一步失败都会清理已产生的临时文件与数据库记录。
    """
    if not upload_file or not upload_file.filename:
        return False, '请选择要上传的音频文件'
    if not title:
        return False, '请填写音频名称'

    filename = upload_file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in MUSIC_ALLOWED_EXTENSIONS:
        return False, f'不支持的音频格式，仅支持：{"、".join(sorted(MUSIC_ALLOWED_EXTENSIONS))}'

    work_dir = os.path.join(UPLOAD_MUSIC_DIR, f'.tmp_{uuid.uuid4().hex}')
    os.makedirs(work_dir, exist_ok=True)

    music_id = None
    try:
        # 1. 保存源文件
        src_path = os.path.join(work_dir, f'source.{ext}')
        upload_file.save(src_path)

        # 2. ffmpeg 转码为 HLS（音频统一转 AAC，生成 m3u8 + ts 分片）
        playlist_path = os.path.join(work_dir, 'index.m3u8')
        seg_pattern = os.path.join(work_dir, 'seg_%03d.ts')
        cmd = [
            FFMPEG_BIN, '-y', '-i', src_path, '-vn',
            '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
            '-hls_time', str(HLS_SEGMENT_SECONDS),
            '-hls_list_size', '0',
            '-hls_segment_filename', seg_pattern,
            '-f', 'hls', playlist_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not os.path.isfile(playlist_path):
            detail = (proc.stderr or proc.stdout or '')[-400:]
            raise RuntimeError(f'音频转码失败：{detail}')

        # 3. 插入数据库记录，获取音频 ID
        #    申请公开 → 待审核；仅自己使用 → 私有
        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        conn = get_db()
        try:
            cursor = conn.execute(
                "INSERT INTO music (user_id, username, title, file_path, status, created_at) "
                "VALUES (?, ?, ?, '', ?, ?)",
                (user_id, username, title, status, _now()),
            )
            conn.commit()
            music_id = cursor.lastrowid
        finally:
            conn.close()
        if not music_id:
            raise RuntimeError('音频记录创建失败')

        # 4. 改写 m3u8 分片为绝对 URL 路径
        _rewrite_playlist_segments(playlist_path, music_id)

        # 5. 临时目录重命名为最终 ID 目录
        final_dir = _music_dir(music_id)
        if os.path.isdir(final_dir):
            shutil.rmtree(final_dir, ignore_errors=True)
        shutil.move(work_dir, final_dir)

        # 6. 记录最终文件路径
        conn = get_db()
        try:
            conn.execute(
                "UPDATE music SET file_path = ? WHERE id = ?",
                (f'music/{music_id}/index.m3u8', music_id),
            )
            conn.commit()
        finally:
            conn.close()

        log('Music', '上传大喇叭音频', music_id=music_id, user_id=user_id,
            username=username, title=title, status=status, ip=ip_address)
        return True, {'music_id': music_id, 'title': title}
    except Exception as e:
        # 清理：删除临时目录；若已插入数据库记录则同步删除记录与文件
        shutil.rmtree(work_dir, ignore_errors=True)
        if music_id:
            try:
                conn = get_db()
                conn.execute("DELETE FROM music WHERE id = ?", (music_id,))
                conn.commit()
                conn.close()
            except Exception:
                pass
            shutil.rmtree(_music_dir(music_id), ignore_errors=True)
        return False, str(e)


# ---------------------------------------------------------------------------
# 删除 / 公开切换
# ---------------------------------------------------------------------------

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
    - 待审核/已公开/已驳回 → 转为私有（仅自己可见）
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

    approve=True 通过 → 已公开；approve=False 驳回 → 已驳回（用户可转为私有或删除）。
    仅待审核状态的音频可被审核。
    """
    music = get_music(music_id)
    if not music:
        return False, '音频不存在'
    if music['status'] != STATUS_PENDING:
        return False, '该音频不在待审核状态'

    new_status = STATUS_PUBLIC if approve else STATUS_REJECTED
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
    return True, '已驳回，用户可将音频转为私有或删除'
