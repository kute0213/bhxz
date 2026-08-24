"""大喇叭音频业务服务：上传转码 HLS、列表查询、删除、公开审核。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
音频文件存放在 uploads/music/<音频ID>/ 目录，播放链接格式：
http://<主机>/music/<音频ID>.m3u8

上传采用「异步任务 + 轮询进度」：
- 每次上传创建独立临时目录（.tmp_<uuid>）与独立 ffmpeg 子进程，多用户并发互不冲突
- 后台线程运行 ffmpeg 并解析 -progress 输出，转码百分比通过 get_upload_progress 获取
"""

import os
import re
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


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 收藏
# ---------------------------------------------------------------------------

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


def _build_transcode_cmd(src_path, playlist_path, seg_pattern, mp3_path, progress_file):
    """构造 ffmpeg 转码命令：一次运行同时生成 HLS（m3u8+ts）与 MP3（唱片）。

    - MP3 供游戏内「电脑」下载后烧录成唱片；原音频源文件转码后删除。
    - -progress <文件> 把机器可读进度写入独立文件（ffmpeg 逐次 flush），
      后台轮询该文件计算真实百分比；-loglevel error 使 stderr 仅含错误。
    """
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
    """读取 ffmpeg 转码进度百分比（0~99），无法计算时返回 None。

    优先解析 -progress 文件中的 out_time_us；同时用 m3u8 已生成分片的
    累计时长作补充（时长探测失败时仍能给出真实进度），取两者较大值。
    """
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


def _insert_music_record(user_id, username, title, status, tags=''):
    """插入音频记录并返回可靠 ID（并发安全）；失败抛异常。

    原实现依赖 cursor.lastrowid：数据库为全局单例且共享游标，并发上传时
    lastrowid 会被其他线程的 INSERT 覆盖，返回错误 ID，导致音频文件被写入
    错误目录（无法播放）、删除时也清理不到对应文件。
    现改为在持锁事务内完成 INSERT 与 lastrowid 读取（DuckDBCursor 在
    INSERT 后立刻用 currval 计算 lastrowid），保证 ID 不被并发覆盖。
    """
    try:
        with get_db() as conn:  # 持有线程锁，INSERT 与 ID 读取保持原子
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
    # 删除原始上传文件与临时进度/错误日志，仅保留 HLS（index.m3u8 + seg_*.ts）与唱片 MP3（index.mp3）
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

        # 2. ffmpeg 转码：同时生成 HLS（m3u8 + ts 分片）与 MP3（唱片）
        playlist_path = os.path.join(work_dir, 'index.m3u8')
        seg_pattern = os.path.join(work_dir, 'seg_%03d.ts')
        mp3_path = os.path.join(work_dir, 'index.mp3')
        progress_file = os.path.join(work_dir, 'progress.log')
        cmd = _build_transcode_cmd(src_path, playlist_path, seg_pattern, mp3_path, progress_file)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not os.path.isfile(playlist_path) or not os.path.isfile(mp3_path):
            detail = (proc.stderr or proc.stdout or '')[-400:]
            raise RuntimeError(f'音频转码失败：{detail}')

        # 3. 插入数据库记录，获取音频 ID
        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        music_id = _insert_music_record(user_id, username, title, status, tags)
        if not music_id:
            raise RuntimeError('音频记录创建失败')

        # 4. 改写 m3u8 + 目录重命名 + 记录路径
        _finalize_music_files(work_dir, music_id)

        log('Music', '上传大喇叭音频', music_id=music_id, user_id=user_id,
            username=username, title=title, status=status, tags=parse_tags(tags), ip=ip_address)
        return True, {'music_id': music_id, 'title': title}
    except Exception as e:
        # 清理：删除临时目录；若已插入数据库记录则同步删除记录与文件
        shutil.rmtree(work_dir, ignore_errors=True)
        _cleanup_music_record(music_id)
        return False, str(e)


# ---------------------------------------------------------------------------
# 异步上传（独立页面 + 详细进度条）
# ---------------------------------------------------------------------------

def start_upload(user_id, username, title, is_public, upload_file, ip_address, tags=''):
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
              work_dir, src_path, ip_address, tags),
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
                     work_dir, src_path, ip_address, tags=''):
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

        # stderr 写文件避免管道阻塞；实时进度改由轮询 -progress 文件与 m3u8 分片获得
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

        # 落库 + 文件整理（自动删除原音频源文件）
        status = STATUS_PENDING if is_public else STATUS_PRIVATE
        music_id = _insert_music_record(user_id, username, title, status, tags)
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
