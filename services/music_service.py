"""大喇叭音频业务服务：上传转码 HLS、列表查询、删除、公开审核。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
音频文件存放在 uploads/music/<音频ID>/ 目录，播放链接格式：
http://<主机>/music/<音频ID>.m3u8

上传采用「异步任务 + 轮询进度」：
- 每次上传创建独立临时目录（.tmp_<uuid>）与独立 ffmpeg 子进程，多用户并发互不冲突
- 后台线程运行 ffmpeg 并解析 -progress 输出，转码百分比通过 get_upload_progress 获取
"""

import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime

from core.db import get_db
from config import (
    UPLOAD_MUSIC_DIR,
    MUSIC_ALLOWED_EXTENSIONS,
    FFMPEG_BIN,
    FFPROBE_BIN,
    FFMPEG_THREADS,
)
from services.logger import log

# HLS 分片时长（秒）
HLS_SEGMENT_SECONDS = 10

# 音频状态：0=私有 1=待审核 2=已公开（3=已驳回 仅遗留老数据，新驳回直接转为私有）
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

# 上传任务在内存中的保留时间（秒），超过后自动清理
_UPLOAD_TASK_TTL = 3600

# 内存中的上传任务进度表：task_id -> {task_id, status, percent, message, ...}
_upload_tasks = {}
_upload_tasks_lock = threading.Lock()


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _music_dir(music_id):
    """音频文件所在目录（绝对路径），路径由音频 ID 决定。"""
    return os.path.join(UPLOAD_MUSIC_DIR, str(music_id))


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def get_public_musics(keyword=''):
    """获取所有已通过审核的公开音频（游戏内大喇叭列表），支持按名称模糊搜索。"""
    conn = get_db()
    try:
        sql = ("SELECT id, user_id, username, title, status, created_at "
               "FROM music WHERE status = ?")
        params = [STATUS_PUBLIC]
        kw = (keyword or '').strip()
        if kw:
            sql += " AND title LIKE ?"
            params.append(f'%{kw}%')
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


def _probe_duration(src_path):
    """用 ffprobe 探测音频时长（秒），失败返回 None（进度降级为不确定）。"""
    try:
        proc = subprocess.run(
            [FFPROBE_BIN, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', src_path],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode == 0:
            val = (proc.stdout or '').strip()
            try:
                return float(val) if val else None
            except ValueError:
                return None
    except Exception:
        pass
    return None


def _build_transcode_cmd(src_path, playlist_path, seg_pattern):
    """构造 ffmpeg 转码命令：音频统一转 AAC 并生成 HLS（m3u8 + ts）。

    -progress pipe:1 输出机器可读进度，-loglevel error 保证 stderr 仅包含
    错误信息（避免管道缓冲阻塞）。
    """
    cmd = [
        FFMPEG_BIN, '-y', '-loglevel', 'error', '-nostats',
        '-i', src_path, '-vn',
        '-threads', str(FFMPEG_THREADS),
        '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
        '-hls_time', str(HLS_SEGMENT_SECONDS),
        '-hls_list_size', '0',
        '-hls_segment_filename', seg_pattern,
        '-progress', 'pipe:1',
        '-f', 'hls', playlist_path,
    ]
    return cmd


def _insert_music_record(user_id, username, title, status):
    """插入音频记录并返回 ID；失败抛异常。"""
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO music (user_id, username, title, file_path, status, created_at) "
            "VALUES (?, ?, ?, '', ?, ?)",
            (user_id, username, title, status, _now()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _finalize_music_files(work_dir, music_id):
    """转码完成后：改写 m3u8 绝对路径 → 目录重命名为 <ID> 目录 → 记录 file_path。"""
    playlist_path = os.path.join(work_dir, 'index.m3u8')
    _rewrite_playlist_segments(playlist_path, music_id)
    final_dir = _music_dir(music_id)
    if os.path.isdir(final_dir):
        shutil.rmtree(final_dir, ignore_errors=True)
    shutil.move(work_dir, final_dir)

    conn = get_db()
    try:
        conn.execute(
            "UPDATE music SET file_path = ? WHERE id = ?",
            (f'music/{music_id}/index.m3u8', music_id),
        )
        conn.commit()
    finally:
        conn.close()


def _cleanup_music_record(music_id):
    """删除转码失败时残留的数据库记录与文件目录。"""
    if not music_id:
        return
    try:
        conn = get_db()
        conn.execute("DELETE FROM music WHERE id = ?", (music_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    shutil.rmtree(_music_dir(music_id), ignore_errors=True)


def upload_music(user_id, username, title, is_public, upload_file, ip_address):
    """同步上传音频并转码为 HLS（m3u8）。返回 (success, data_or_error)。

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
        cmd = _build_transcode_cmd(src_path, playlist_path, seg_pattern)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not os.path.isfile(playlist_path):
            detail = (proc.stderr or proc.stdout or '')[-400:]
            raise RuntimeError(f'音频转码失败：{detail}')

        # 3. 插入数据库记录，获取音频 ID
        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        music_id = _insert_music_record(user_id, username, title, status)
        if not music_id:
            raise RuntimeError('音频记录创建失败')

        # 4. 改写 m3u8 + 目录重命名 + 记录路径
        _finalize_music_files(work_dir, music_id)

        log('Music', '上传大喇叭音频', music_id=music_id, user_id=user_id,
            username=username, title=title, status=status, ip=ip_address)
        return True, {'music_id': music_id, 'title': title}
    except Exception as e:
        # 清理：删除临时目录；若已插入数据库记录则同步删除记录与文件
        shutil.rmtree(work_dir, ignore_errors=True)
        _cleanup_music_record(music_id)
        return False, str(e)


# ---------------------------------------------------------------------------
# 异步上传（独立页面 + 详细进度条）
# ---------------------------------------------------------------------------

def start_upload(user_id, username, title, is_public, upload_file, ip_address):
    """开始异步上传任务，立即返回 task_id，转码在后台线程执行。

    返回 (True, {'task_id': ...})；参数校验失败返回 (False, 错误信息)。
    每次上传使用独立临时目录（.tmp_<uuid>）与独立 ffmpeg 子进程，
    多用户同时上传时天然并行，不会出现「文件正在使用」冲突。
    """
    if not upload_file or not upload_file.filename:
        return False, '请选择要上传的音频文件'
    if not title:
        return False, '请填写音频名称'

    filename = upload_file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in MUSIC_ALLOWED_EXTENSIONS:
        return False, f'不支持的音频格式，仅支持：{"、".join(sorted(MUSIC_ALLOWED_EXTENSIONS))}'

    task_id = uuid.uuid4().hex
    work_dir = os.path.join(UPLOAD_MUSIC_DIR, f'.tmp_{task_id}')
    os.makedirs(work_dir, exist_ok=True)
    src_path = os.path.join(work_dir, f'source.{ext}')
    upload_file.save(src_path)

    task = {
        'task_id': task_id,
        'status': 'transcoding',   # transcoding / done / error
        'percent': 0,
        'message': '正在准备转码…',
        'duration': _probe_duration(src_path),
        'error': '',
        'music_id': None,
        'title': title,
        'link': '',
        'created_at': time.time(),
    }
    with _upload_tasks_lock:
        _upload_tasks[task_id] = task
        _prune_upload_tasks()

    # 后台线程执行转码，避免阻塞上传请求
    threading.Thread(
        target=_run_upload_task,
        args=(task_id, user_id, username, title, is_public,
              work_dir, src_path, ip_address),
        daemon=True,
    ).start()
    return True, {'task_id': task_id}


def _prune_upload_tasks():
    """清理超过 TTL 的任务，防止内存无限增长（调用方须持有锁）。"""
    now = time.time()
    stale = [k for k, v in _upload_tasks.items()
             if now - v.get('created_at', 0) > _UPLOAD_TASK_TTL]
    for k in stale:
        _upload_tasks.pop(k, None)


def _set_task(task_id, **kwargs):
    """更新内存中的任务进度（线程安全）。"""
    with _upload_tasks_lock:
        if task_id in _upload_tasks:
            _upload_tasks[task_id].update(kwargs)


def _run_upload_task(task_id, user_id, username, title, is_public,
                     work_dir, src_path, ip_address):
    """后台线程：运行 ffmpeg 转码，解析 -progress 输出，成功后落库。"""
    try:
        playlist_path = os.path.join(work_dir, 'index.m3u8')
        seg_pattern = os.path.join(work_dir, 'seg_%03d.ts')
        cmd = _build_transcode_cmd(src_path, playlist_path, seg_pattern)

        with _upload_tasks_lock:
            duration = _upload_tasks.get(task_id, {}).get('duration')

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
        )
        # 解析 stdout 中的 -progress 输出（key=value 行），计算转码百分比
        out_time_us = None
        for line in proc.stdout:
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, _, value = line.partition('=')
            if key == 'out_time_us':
                try:
                    out_time_us = int(value)
                except ValueError:
                    out_time_us = None
            elif key == 'progress' and value == 'continue' and out_time_us and duration:
                percent = min(99.0, round(out_time_us / 1_000_000.0 / duration * 100, 1))
                _set_task(task_id, percent=percent, message=f'正在转码… {percent:.0f}%')
                out_time_us = None

        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError('音频转码超时')
        stderr = proc.stderr.read() if proc.stderr else ''

        if proc.returncode != 0 or not os.path.isfile(playlist_path):
            detail = (stderr or '')[-400:]
            raise RuntimeError(f'音频转码失败：{detail}' if detail else '音频转码失败')

        # 落库 + 文件整理
        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        music_id = _insert_music_record(user_id, username, title, status)
        if not music_id:
            raise RuntimeError('音频记录创建失败')
        _finalize_music_files(work_dir, music_id)

        log('Music', '上传大喇叭音频', music_id=music_id, user_id=user_id,
            username=username, title=title, status=status, ip=ip_address)
        _set_task(task_id, status='done', percent=100, message='转码完成', music_id=music_id)
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        _set_task(task_id, status='error', message='转码失败', error=str(e))
        log('Music', '上传大喇叭音频失败', user_id=user_id, title=title,
            error=str(e), ip=ip_address)


def get_upload_progress(task_id):
    """获取上传任务进度。返回任务 dict 副本；任务不存在返回 None。"""
    with _upload_tasks_lock:
        task = _upload_tasks.get(task_id)
        return dict(task) if task else None


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
