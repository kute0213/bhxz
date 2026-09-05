"""大喇叭音频业务服务 - 上传转码 HLS。

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
    AUDIO_MAX_BYTES,
)
from core.logger import log
from services.music.constants import (
    HLS_SEGMENT_SECONDS,
    STATUS_PENDING,
    STATUS_PRIVATE,
    UPLOAD_TASK_TTL,
)
from services.music.queries import parse_tags, _music_dir


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# 内存中的上传任务进度表：task_id -> {task_id, status, percent, message, ...}
_upload_tasks = {}
_upload_tasks_lock = threading.Lock()


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


def _build_transcode_cmd(src_path, playlist_path, seg_pattern, mp3_path, progress_file):
    """构造 ffmpeg 转码命令：一次运行同时生成 HLS（m3u8+ts）与 MP3（唱片）。"""
    cmd = [
        FFMPEG_BIN, '-y', '-loglevel', 'error', '-nostats',
        '-threads', str(FFMPEG_THREADS),
        '-i', src_path,
        # 输出1：HLS 流（统一 AAC 128k，供大喇叭在线播放）
        '-map', '0:a', '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
        '-hls_time', str(HLS_SEGMENT_SECONDS),
        '-hls_list_size', '0',
        '-hls_segment_filename', seg_pattern,
        '-f', 'hls', playlist_path,
        # 输出2：MP3（唱片文件）
        '-map', '0:a', '-c:a', 'libmp3lame', '-b:a', '192k', '-ac', '2',
        '-id3v2_version', '3', mp3_path,
        '-progress', progress_file,
    ]
    return cmd


def _read_transcode_percent(progress_file, playlist_path, duration):
    """读取 ffmpeg 转码进度百分比（0~99），无法计算时返回 None。"""
    if not duration:
        return None
    pct = None
    # 方法1：-progress 文件
    try:
        if os.path.isfile(progress_file):
            with open(progress_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            for line in content.splitlines():
                if line.startswith('out_time_us='):
                    try:
                        us = int(line.split('=', 1)[1])
                    except ValueError:
                        us = None
                    if us is not None:
                        pct = us / 1_000_000.0 / duration * 100
    except Exception:
        pct = None
    # 方法2：m3u8 分片累计时长
    try:
        if os.path.isfile(playlist_path):
            seg_dur = 0.0
            with open(playlist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('#EXTINF:'):
                        try:
                            seg_dur += float(line.split(':', 1)[1].split(',', 1)[0])
                        except (ValueError, IndexError):
                            pass
            if seg_dur > 0:
                pct2 = seg_dur / duration * 100
                pct = max(pct or 0.0, pct2)
    except Exception:
        pass
    if pct is None:
        return None
    return min(99.0, max(0.0, pct))


def _insert_music_record(user_id, username, title, status, tags='', music_id=None):
    """插入音频记录并返回可靠 ID（并发安全）；失败抛异常。"""
    try:
        with get_db() as conn:
            if music_id is not None:
                conn.execute(
                    "INSERT INTO music (id, user_id, username, title, file_path, status, tags, created_at) "
                    "VALUES (?, ?, ?, ?, '', ?, ?, ?)",
                    (music_id, user_id, username, title, status, parse_tags(tags), _now()),
                )
                return music_id
            cursor = conn.execute(
                "INSERT INTO music (user_id, username, title, file_path, status, tags, created_at) "
                "VALUES (?, ?, ?, '', ?, ?, ?)",
                (user_id, username, title, status, parse_tags(tags), _now()),
            )
            music_id = cursor.lastrowid
            if not music_id:
                raise RuntimeError('音频记录创建失败')
            return int(music_id)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f'插入音频记录失败: {str(e)}')


def _finalize_music_files(work_dir, music_id):
    """转码完成后：删除原音频源文件与临时日志 → 改写 m3u8 绝对路径 → 目录重命名。"""
    playlist_path = os.path.join(work_dir, 'index.m3u8')
    _rewrite_playlist_segments(playlist_path, music_id)
    for name in os.listdir(work_dir):
        if name.startswith('source.') or name in ('progress.log', 'transcode.err'):
            try:
                os.remove(os.path.join(work_dir, name))
            except OSError:
                pass
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


def upload_music(user_id, username, title, is_public, upload_file, ip_address, tags=''):
    """同步上传音频并转码为 HLS（m3u8）。返回 (success, data_or_error)。"""
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
        src_path = os.path.join(work_dir, f'source.{ext}')
        upload_file.save(src_path)

        playlist_path = os.path.join(work_dir, 'index.m3u8')
        seg_pattern = os.path.join(work_dir, 'seg_%03d.ts')
        mp3_path = os.path.join(work_dir, 'index.mp3')
        progress_file = os.path.join(work_dir, 'progress.log')
        cmd = _build_transcode_cmd(src_path, playlist_path, seg_pattern, mp3_path, progress_file)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not os.path.isfile(playlist_path) or not os.path.isfile(mp3_path):
            detail = (proc.stderr or proc.stdout or '')[-400:]
            raise RuntimeError(f'音频转码失败：{detail}')

        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        music_id = _insert_music_record(user_id, username, title, status, tags)
        if not music_id:
            raise RuntimeError('音频记录创建失败')

        _finalize_music_files(work_dir, music_id)

        log('Music', '上传大喇叭音频', music_id=music_id, user_id=user_id,
            username=username, title=title, status=status, tags=parse_tags(tags), ip=ip_address)
        return True, {'music_id': music_id, 'title': title}
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        _cleanup_music_record(music_id)
        return False, str(e)


def start_upload(user_id, username, title, is_public, upload_file, ip_address, tags=''):
    """开始异步上传任务，立即返回 task_id，转码在后台线程执行。"""
    if not upload_file or not upload_file.filename:
        return False, '请选择要上传的音频文件'
    if not title:
        return False, '请填写音频名称'

    upload_file.seek(0, os.SEEK_END)
    file_size = upload_file.tell()
    upload_file.seek(0)
    if file_size > AUDIO_MAX_BYTES:
        return False, f'音频文件大小不能超过 {AUDIO_MAX_BYTES // (1024*1024)}MB'

    filename = upload_file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in MUSIC_ALLOWED_EXTENSIONS:
        return False, f'不支持的音频格式，仅支持：{"、".join(sorted(MUSIC_ALLOWED_EXTENSIONS))}'

    # 音频魔数校验
    _AUDIO_MAGIC = {
        'mp3': [b'ID3', b'\xff\xfb', b'\xff\xf3'],
        'wav': [b'RIFF'],
        'ogg': [b'OggS'],
        'flac': [b'fLaC'],
        'm4a': None,
        'mp4': None,
    }
    header = upload_file.read(8)
    upload_file.seek(0)
    expected_magics = _AUDIO_MAGIC.get(ext)
    if expected_magics is not None:
        if not any(header.startswith(m) for m in expected_magics):
            return False, f'文件类型校验失败：{filename} 的文件头魔数与扩展名不匹配'
    elif ext in ('mp4', 'm4a'):
        if len(header) < 8 or header[4:8] != b'ftyp':
            return False, f'文件类型校验失败：{filename} 的文件头魔数与扩展名不匹配'

    task_id = uuid.uuid4().hex
    work_dir = os.path.join(UPLOAD_MUSIC_DIR, f'.tmp_{task_id}')
    os.makedirs(work_dir, exist_ok=True)
    src_path = os.path.join(work_dir, f'source.{ext}')
    upload_file.save(src_path)

    task = {
        'task_id': task_id,
        'status': 'transcoding',
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

    threading.Thread(
        target=_run_upload_task,
        args=(task_id, user_id, username, title, is_public,
              work_dir, src_path, ip_address, tags, None),
        daemon=True,
    ).start()
    return True, {'task_id': task_id}


def _prune_upload_tasks():
    """清理超过 TTL 的任务，防止内存无限增长（调用方须持有锁）。"""
    now = time.time()
    stale = [k for k, v in _upload_tasks.items()
             if now - v.get('created_at', 0) > UPLOAD_TASK_TTL]
    for k in stale:
        _upload_tasks.pop(k, None)


def _set_task(task_id, **kwargs):
    """更新内存中的任务进度（线程安全）。"""
    with _upload_tasks_lock:
        if task_id in _upload_tasks:
            _upload_tasks[task_id].update(kwargs)


def _run_upload_task(task_id, user_id, username, title, is_public,
                     work_dir, src_path, ip_address, tags='', music_id=None):
    """后台线程：运行 ffmpeg 转码（HLS+MP3），轮询进度，成功后落库。"""
    try:
        playlist_path = os.path.join(work_dir, 'index.m3u8')
        seg_pattern = os.path.join(work_dir, 'seg_%03d.ts')
        mp3_path = os.path.join(work_dir, 'index.mp3')
        progress_file = os.path.join(work_dir, 'progress.log')
        err_log = os.path.join(work_dir, 'transcode.err')
        cmd = _build_transcode_cmd(src_path, playlist_path, seg_pattern, mp3_path, progress_file)

        with _upload_tasks_lock:
            duration = _upload_tasks.get(task_id, {}).get('duration')

        _set_task(task_id, status='transcoding', percent=0, message='正在转码… 0%')

        with open(err_log, 'w', encoding='utf-8', errors='replace') as errf:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errf)
            deadline = time.time() + 300
            try:
                while proc.poll() is None:
                    pct = _read_transcode_percent(progress_file, playlist_path, duration)
                    if pct is not None:
                        p = round(pct, 1)
                        _set_task(task_id, percent=p, message=f'正在转码… {p:.0f}%')
                    if time.time() > deadline:
                        proc.kill()
                        proc.wait()
                        raise RuntimeError('音频转码超时')
                    time.sleep(0.2)
                proc.wait(timeout=10)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

        with open(err_log, 'r', encoding='utf-8', errors='replace') as f:
            stderr = f.read()

        if proc.returncode != 0 or not os.path.isfile(playlist_path) or not os.path.isfile(mp3_path):
            detail = (stderr or '')[-400:]
            raise RuntimeError(f'音频转码失败：{detail}' if detail else '音频转码失败')

        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        music_id = _insert_music_record(user_id, username, title, status, tags, music_id)
        if not music_id:
            raise RuntimeError('音频记录创建失败')
        _finalize_music_files(work_dir, music_id)

        log('Music', '上传大喇叭音频', music_id=music_id, user_id=user_id,
            username=username, title=title, status=status, tags=parse_tags(tags), ip=ip_address)
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