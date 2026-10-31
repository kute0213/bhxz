"""服务器指南文件存储服务。

指南不再把正文存在数据库，而是以「每个指南一个文件夹」的方式存放在
``uploads/guides/`` 下：

    uploads/guides/<指南ID>/
        guide.md        # 指南 Markdown 源文件（唯一内容来源）
        assets/         # 指南资源（视频等），合计不超过 50MB

指南在「新建」时即获得 ID 与目录，因此编辑页上传的资源直接写入
``assets/``，不再需要临时草稿目录。

本模块为纯 Python（不依赖 Flask / 数据库），供路由与迁移脚本复用。
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta

from config import (
    UPLOAD_GUIDES_DIR,
    GUIDE_RESOURCE_MAX_BYTES,
    GUIDE_VIDEO_EXTENSIONS,
    GUIDE_DRAFT_KEEP_HOURS,
    GUIDE_VIDEO_TRANSCODE_TIMEOUT,
    FFPROBE_BIN,
    FFMPEG_BIN,
)
from core.shared.snowflake import next_id

MD_FILENAME = 'guide.md'
ASSETS_DIRNAME = 'assets'
CONFIG_FILENAME = 'config.json'
CONFIG_VERSION = 1
VIDEO_TASK_TTL = 3600  # 视频转码任务进度在内存中保留的秒数
DRAFT_DIRNAME = '_drafts'  # 旧版草稿目录，仅用于清理历史残留


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def guide_dir(guide_id):
    """指南文件夹：uploads/guides/<指南ID>。"""
    return os.path.join(UPLOAD_GUIDES_DIR, str(int(guide_id)))


def guide_md_path(guide_id):
    """指南 Markdown 源文件路径。"""
    return os.path.join(guide_dir(guide_id), MD_FILENAME)


def assets_dir_for(guide_id):
    """指南资源目录（视频等）。"""
    return os.path.join(guide_dir(guide_id), ASSETS_DIRNAME)


def guide_config_path(guide_id):
    """指南配置文件路径：uploads/guides/<指南ID>/config.json。"""
    return os.path.join(guide_dir(guide_id), CONFIG_FILENAME)


def draft_dir(token):
    """旧版草稿根目录：uploads/guides/_drafts/<token>（仅用于清理残留）。"""
    return os.path.join(UPLOAD_GUIDES_DIR, DRAFT_DIRNAME, str(token))


def ensure_guide_dir(guide_id):
    """确保指南目录、assets 目录与 config.json 存在。"""
    os.makedirs(assets_dir_for(guide_id), exist_ok=True)
    if not os.path.isfile(guide_config_path(guide_id)):
        write_guide_config(guide_id, default_guide_config())


# ---------------------------------------------------------------------------
# 正文（guide.md）
# ---------------------------------------------------------------------------

def read_guide_content(guide_id, fallback=''):
    """读取指南 Markdown 正文。

    文件存在时以文件为准；文件缺失时回退到数据库旧内容（迁移前的数据），
    保证迁移脚本尚未执行时站点仍可正常显示。
    """
    path = guide_md_path(guide_id)
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                return fh.read()
        except OSError:
            return fallback or ''
    return fallback or ''


def write_guide_content(guide_id, content):
    """写入指南 Markdown 正文（先写临时文件再原子替换）。"""
    ensure_guide_dir(guide_id)
    path = guide_md_path(guide_id)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(str(content or ''))
    os.replace(tmp, path)
    return path


def delete_guide_dir(guide_id):
    """删除整个指南文件夹（正文 + 资源 + config.json）。目录不存在时静默。"""
    shutil.rmtree(guide_dir(guide_id), ignore_errors=True)


# ---------------------------------------------------------------------------
# 指南配置（config.json）
#
# 结构固定为「版本号 + 分节」，便于后续扩展：
#     {
#       "version": 1,
#       "videos": {
#         "366117423394816.mp4": {"title": "海滩日落"}
#       }
#     }
# - 键为资源的真实文件名，值为该资源的展示配置；
# - 新增配置项时只增加分节 / 字段，不改变已有结构。
# ---------------------------------------------------------------------------

def default_guide_config():
    """返回全新的指南配置字典。"""
    return {'version': CONFIG_VERSION, 'videos': {}}


def read_guide_config(guide_id):
    """读取指南配置；文件缺失或损坏时返回默认结构（不写盘）。"""
    config = default_guide_config()
    path = guide_config_path(guide_id)
    if not os.path.isfile(path):
        return config
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return config
    if not isinstance(data, dict):
        return config
    try:
        config['version'] = int(data.get('version') or CONFIG_VERSION)
    except (TypeError, ValueError):
        config['version'] = CONFIG_VERSION
    videos = data.get('videos')
    config['videos'] = videos if isinstance(videos, dict) else {}
    return config


def write_guide_config(guide_id, config):
    """原子写入指南配置（先写临时文件再替换）。"""
    os.makedirs(assets_dir_for(guide_id), exist_ok=True)
    data = config if isinstance(config, dict) else default_guide_config()
    data['version'] = CONFIG_VERSION
    if not isinstance(data.get('videos'), dict):
        data['videos'] = {}
    path = guide_config_path(guide_id)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def video_config(guide_id, filename):
    """读取某个视频的配置（缺失时返回空字典）。"""
    config = read_guide_config(guide_id)
    item = config['videos'].get(os.path.basename(str(filename or '')))
    return item if isinstance(item, dict) else {}


def video_title(guide_id, filename, default=''):
    """视频在页面上显示的伪文件名；未配置时返回 default / 文件名。"""
    meta = video_config(guide_id, filename)
    title = str(meta.get('title') or '').strip()
    return title or default or os.path.basename(str(filename or ''))


def set_video_title(guide_id, filename, title):
    """设置视频的显示名称（写入 config.json）。"""
    name = os.path.basename(str(filename or ''))
    config = read_guide_config(guide_id)
    item = config['videos'].get(name)
    if not isinstance(item, dict):
        item = {}
    item['title'] = str(title or '').strip()
    config['videos'][name] = item
    write_guide_config(guide_id, config)
    return item['title']


def remove_video_config(guide_id, filename):
    """删除某个视频的配置项（视频文件删除时同步调用）。"""
    name = os.path.basename(str(filename or ''))
    config = read_guide_config(guide_id)
    if name in config['videos']:
        config['videos'].pop(name, None)
        write_guide_config(guide_id, config)
        return True
    return False


# ---------------------------------------------------------------------------
# 资源文件名 / 大小
# ---------------------------------------------------------------------------

def safe_asset_name(filename):
    """把上传文件名转换为安全的资源文件名（保留中文，去掉路径与危险字符）。"""
    raw = os.path.basename(str(filename or '').replace('\\', '/')).strip()
    if not raw:
        return 'asset'
    stem, ext = os.path.splitext(raw)
    stem = re.sub(r'[^\w\- .()]+', '_', stem).strip(' ._')[:80] or 'asset'
    ext = re.sub(r'[^A-Za-z0-9]', '', ext.lstrip('.')).lower()
    return f'{stem}.{ext}' if ext else stem


def _unique_name(directory, name):
    """在目录内生成不冲突的文件名。"""
    base, ext = os.path.splitext(name)
    candidate = name
    i = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f'{base}-{i}{ext}'
        i += 1
    return candidate


def is_video_name(filename):
    """文件名扩展名是否为允许的视频格式。"""
    ext = str(filename or '').rsplit('.', 1)[-1].lower() if '.' in str(filename or '') else ''
    return ext in GUIDE_VIDEO_EXTENSIONS


def format_size(size):
    """字节数转可读文本（如 12.3 MB）。"""
    n = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            if unit == 'B':
                return f'{int(n)} B'
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} GB'


# ---------------------------------------------------------------------------
# 资源列表 / 配额 / 保存 / 删除
# ---------------------------------------------------------------------------

def _iter_files(directory):
    """遍历目录内的普通文件（忽略子目录与隐藏临时文件）。"""
    if not os.path.isdir(directory):
        return
    with os.scandir(directory) as entries:
        for entry in entries:
            try:
                if entry.is_file() and not entry.name.startswith('.'):
                    yield entry.name, entry.stat().st_size
            except OSError:
                continue


def list_assets(directory):
    """列出目录内的资源：``[{'name': ..., 'size': ..., 'size_label': ...}]``。"""
    items = []
    for name, size in sorted(_iter_files(directory), key=lambda x: x[0].lower()):
        items.append({'name': name, 'size': size, 'size_label': format_size(size)})
    return items


def directory_total(directory):
    """目录内所有资源文件的总字节数。"""
    return sum(size for _, size in _iter_files(directory))


def guide_total(guide_id):
    """指南资源占用字节数。"""
    return directory_total(assets_dir_for(guide_id))


def _quota_error(total, size, limit_bytes=None):
    """资源配额错误提示；limit_bytes 为 None 时使用默认配置上限。"""
    limit = int(limit_bytes or GUIDE_RESOURCE_MAX_BYTES)
    if (total or 0) + (size or 0) > limit:
        return (
            f'资源超出上限：每个指南最多 {format_size(limit)}，'
            f'当前已用 {format_size(total)}'
        )
    return ''


def _save_upload(directory, upload):
    """把上传文件保存到目录（自动重名），返回 (文件名, 字节数)。"""
    os.makedirs(directory, exist_ok=True)
    name = _unique_name(directory, safe_asset_name(upload.filename))
    path = os.path.join(directory, name)
    upload.save(path)
    return name, os.path.getsize(path)


def save_guide_asset(guide_id, upload, limit_bytes=None):
    """保存指南资源，返回 ``(ok, message, item)``。

    item 为 ``{'name', 'size', 'size_label'}``；配额按整个 assets 目录累计。
    """
    directory = assets_dir_for(guide_id)
    os.makedirs(directory, exist_ok=True)
    total = directory_total(directory)
    # 先估算大小，超配额时不落盘
    try:
        stream = getattr(upload, 'stream', None)
        if stream is not None:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
        else:
            size = 0
    except (AttributeError, OSError):
        size = 0
    msg = _quota_error(total, size, limit_bytes)
    if msg:
        return False, msg, None
    name, size = _save_upload(directory, upload)
    return True, '', {'name': name, 'size': size, 'size_label': format_size(size)}


FFMPEG_MISSING_MSG = (
    '未找到 ffmpeg 可执行文件，无法转码视频：'
    'Windows 请将 ffmpeg.exe 放到 uploads/ffmpeg/ 目录；'
    'Linux/macOS 请安装系统 ffmpeg'
)


def _probe_duration(src_path):
    """用 ffprobe 读取视频时长（秒）；失败时返回 0（进度条退化为不确定状态）。"""
    if not FFPROBE_BIN:
        return 0.0
    try:
        proc = subprocess.run(
            [FFPROBE_BIN, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=nw=1:nk=1', src_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
        )
        value = (proc.stdout or b'').decode('utf-8', 'ignore').strip()
        return max(0.0, float(value)) if value else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _read_progress(progress_file, duration):
    """解析 ffmpeg ``-progress`` 输出，返回 0~99 的百分比；无可用数据时 None。"""
    if duration <= 0:
        return None
    try:
        with open(progress_file, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except OSError:
        return None
    micro = re.findall(r'out_time_us=(\d+)', content)
    if not micro:
        micro = re.findall(r'out_time_ms=(\d+)', content)  # 该字段实际也是微秒
    if not micro:
        return None
    seconds = int(micro[-1]) / 1e6
    return max(0.0, min(99.0, seconds / duration * 100))


def _run_ffmpeg(src_path, out_path, progress_file, duration, progress_cb=None):
    """执行 ffmpeg 转码并轮询进度，返回 ``(ok, message)``。"""
    cmd = [
        FFMPEG_BIN, '-y', '-loglevel', 'error', '-nostats',
        '-i', src_path,
        # 视频：H.264（yuv420p 保证浏览器 / 系统兼容，宽高取偶数）
        '-map', '0:v:0',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
        '-pix_fmt', 'yuv420p',
        # 音频：有则转 AAC，无则忽略
        '-map', '0:a?', '-c:a', 'aac', '-b:a', '128k',
        # 便于网页边下边播
        '-movflags', '+faststart',
        '-progress', progress_file,
        '-f', 'mp4', out_path,
    ]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, OSError):
        return False, FFMPEG_MISSING_MSG

    deadline = time.time() + GUIDE_VIDEO_TRANSCODE_TIMEOUT
    last_percent = 0.0
    timed_out = False
    try:
        while True:
            code = proc.poll()
            if code is not None:
                break
            if time.time() >= deadline:
                timed_out = True
                proc.kill()
                proc.wait()
                break
            percent = _read_progress(progress_file, duration)
            if percent is not None and percent >= last_percent:
                last_percent = percent
                if progress_cb:
                    progress_cb(percent)
            time.sleep(0.4)
        stderr = (proc.stderr.read() if proc.stderr else b'').decode('utf-8', 'ignore')
    finally:
        if proc.stderr:
            proc.stderr.close()

    if timed_out:
        return False, '视频转码超时，请尝试体积更小或更短的视频'
    if proc.returncode != 0 or not os.path.isfile(out_path):
        detail = stderr.strip()[-300:]
        return False, f'视频转码失败：{detail or "ffmpeg 返回异常"}'
    if progress_cb:
        progress_cb(100.0)
    return True, ''


def _process_video(guide_id, src_path, limit_bytes=None, title=None, progress_cb=None):
    """把临时目录中的原始视频转码为最终资源，写入 ``assets/``。

    原文件与转码中间产物都放在临时目录，只有最终 MP4 才会进入 ``assets/``，
    因此配额只按转码后的实际大小计算，也不会把「原视频 + 转码视频」重复累加。
    """
    directory = assets_dir_for(guide_id)
    os.makedirs(directory, exist_ok=True)
    total = directory_total(directory)
    out_name = f'{next_id()}.mp4'

    tmp_dir = tempfile.mkdtemp(prefix='.transcode_', dir=guide_dir(guide_id))
    try:
        staged = os.path.join(tmp_dir, out_name)
        progress_file = os.path.join(tmp_dir, 'progress.txt')
        duration = _probe_duration(src_path)
        if progress_cb:
            progress_cb(0.0 if duration else None)
        ok, message = _run_ffmpeg(src_path, staged, progress_file, duration, progress_cb)
        if not ok:
            return False, message, None

        size = os.path.getsize(staged)
        message = _quota_error(total, size, limit_bytes)
        if message:
            return False, message, None

        os.replace(staged, os.path.join(directory, out_name))
        if title:
            set_video_title(guide_id, out_name, title)
        return True, '', {
            'name': out_name,
            'size': size,
            'size_label': format_size(size),
            'title': video_title(guide_id, out_name, out_name),
        }
    except Exception as exc:
        # 兜底：任何未预期异常（临时目录 / 写入 / 权限 / 杀软占用等）
        # 都要清理半成品并返回可展示的提示，避免接口 500 导致前端「无法上传」。
        return False, f'视频处理失败：{exc}', None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def save_guide_video(guide_id, upload, limit_bytes=None, title=None, progress_cb=None):
    """同步保存并转码指南视频，返回 ``(ok, message, item)``。"""
    ensure_guide_dir(guide_id)
    tmp_dir = tempfile.mkdtemp(prefix='.upload_', dir=guide_dir(guide_id))
    try:
        src_path = os.path.join(tmp_dir, 'source')
        upload.save(src_path)
        return _process_video(guide_id, src_path, limit_bytes, title, progress_cb)
    except Exception as exc:
        return False, f'视频处理失败：{exc}', None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 视频转码任务（异步 + 进度轮询）
# ---------------------------------------------------------------------------

_VIDEO_TASKS = {}
_VIDEO_TASKS_LOCK = threading.Lock()


def _prune_video_tasks():
    """清理超过 TTL 的已完成任务，避免内存无限增长。"""
    now = time.time()
    with _VIDEO_TASKS_LOCK:
        for task_id, task in list(_VIDEO_TASKS.items()):
            if task['status'] in ('done', 'error') and now - task['updated_at'] > VIDEO_TASK_TTL:
                _VIDEO_TASKS.pop(task_id, None)


def _task_update(task_id, **fields):
    with _VIDEO_TASKS_LOCK:
        task = _VIDEO_TASKS.get(task_id)
        if task is None:
            return
        task.update(fields)
        task['updated_at'] = time.time()


def get_video_task(task_id):
    """读取转码任务快照；任务不存在或已过期时返回 None。"""
    _prune_video_tasks()
    with _VIDEO_TASKS_LOCK:
        task = _VIDEO_TASKS.get(str(task_id or ''))
        return dict(task) if task else None


def _video_progress_message(percent):
    if percent is None:
        return '正在转码…'
    return f'正在转码 {int(percent)}%'


def _run_video_task(task_id, guide_id, src_path, src_dir, limit_bytes, title):
    """后台线程：转码并把结果写回任务状态。"""
    def on_progress(percent):
        _task_update(task_id, percent=percent, message=_video_progress_message(percent))

    try:
        ok, message, item = _process_video(
            guide_id, src_path, limit_bytes, title, on_progress,
        )
    except Exception as exc:  # 兜底，保证任务一定能结束
        ok, message, item = False, f'视频处理失败：{exc}', None
    finally:
        shutil.rmtree(src_dir, ignore_errors=True)

    if ok:
        _task_update(task_id, status='done', percent=100.0,
                     message='转码完成', item=item, error='')
    else:
        _task_update(task_id, status='error', percent=None,
                     message=message, item=None, error=message)


def start_guide_video_upload(guide_id, upload, limit_bytes=None, title=None):
    """接收上传文件并启动后台转码任务。

    返回 ``(ok, message, {'task_id': ...})``。浏览器端上传进度由 XHR 负责，
    响应返回后前端把进度条归零并轮询 ``get_video_task`` 获取转码进度。
    """
    try:
        ensure_guide_dir(guide_id)
        src_dir = tempfile.mkdtemp(prefix='.upload_', dir=guide_dir(guide_id))
        src_path = os.path.join(src_dir, 'source')
        upload.save(src_path)
    except Exception as exc:
        return False, f'视频接收失败：{exc}', None

    task_id = uuid.uuid4().hex
    now = time.time()
    with _VIDEO_TASKS_LOCK:
        _VIDEO_TASKS[task_id] = {
            'task_id': task_id,
            'guide_id': int(guide_id),
            'status': 'transcoding',
            'percent': None,
            'message': '正在转码…',
            'item': None,
            'error': '',
            'created_at': now,
            'updated_at': now,
        }
    threading.Thread(
        target=_run_video_task,
        args=(task_id, guide_id, src_path, src_dir, limit_bytes, title),
        daemon=True,
    ).start()
    return True, '', {'task_id': task_id}


def delete_asset(directory, filename):
    """删除目录内的单个资源文件。返回是否实际删除。"""
    name = os.path.basename(str(filename or ''))
    path = os.path.join(directory, name)
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False


def delete_guide_asset(guide_id, filename):
    """删除指南资源文件，并同步清理 config.json 中对应的配置。"""
    removed = delete_asset(assets_dir_for(guide_id), filename)
    if removed:
        remove_video_config(guide_id, filename)
    return removed


def list_guide_assets(guide_id):
    """列出指南资源；视频附带页面显示名 ``title``。"""
    items = list_assets(assets_dir_for(guide_id))
    for item in items:
        if is_video_name(item['name']):
            item['title'] = video_title(guide_id, item['name'], item['name'])
    return items


# ---------------------------------------------------------------------------
# 旧版草稿目录清理
# ---------------------------------------------------------------------------

def cleanup_stale_drafts(keep_hours=GUIDE_DRAFT_KEEP_HOURS):
    """删除超过保留时长的草稿目录，返回删除数量。"""
    root = os.path.join(UPLOAD_GUIDES_DIR, DRAFT_DIRNAME)
    if not os.path.isdir(root):
        return 0
    deadline = datetime.now() - timedelta(hours=keep_hours)
    removed = 0
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            continue
        if mtime < deadline:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
