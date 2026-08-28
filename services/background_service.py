"""背景图片业务服务：上传、审核、列表查询。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
背景图片存储在 uploads/backgrounds/ 目录，自动转换为 WebP 格式。
"""

import os
import hashlib
import threading
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from core.db import get_db
from config import UPLOAD_BACKGROUNDS_DIR, USER_IMAGE_MAX_BYTES
from services.logger import log

# 背景图片状态：0=待审核 1=已通过 2=已驳回
STATUS_PENDING = 0
STATUS_APPROVED = 1
STATUS_REJECTED = 2

STATUS_LABELS = {
    STATUS_PENDING: '待审核',
    STATUS_APPROVED: '已通过',
    STATUS_REJECTED: '已驳回',
}

# 支持的源图片格式
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff'}

# 上传任务进度
_upload_tasks = {}
_upload_tasks_lock = threading.Lock()


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _validate_image(upload):
    """校验上传文件是否为有效图片，返回原始字节数据。"""
    if not upload or not upload.filename:
        raise ValueError('请选择图片')

    ext = (upload.filename.rsplit('.', 1)[-1] if '.' in upload.filename else '').lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError('不支持的图片格式，支持：png、jpg、jpeg、gif、webp、bmp、tiff')

    raw = upload.stream.read(USER_IMAGE_MAX_BYTES + 1)
    if not raw:
        raise ValueError('上传的图片为空')
    if len(raw) > USER_IMAGE_MAX_BYTES:
        raise ValueError('图片不能超过 10MB')
    return raw, ext


def _convert_to_webp(raw, target_size=1920):
    """将图片转换为 WebP 格式，自动适配尺寸。

    Args:
        raw: 原始图片字节数据
        target_size: 目标长边最大像素（默认 1920px）

    Returns:
        WebP 格式的字节数据
    """
    try:
        image = Image.open(BytesIO(raw))
        if image.width * image.height > 40_000_000:
            raise ValueError('图片像素过大，请压缩后重试')
        image.verify()
        image = Image.open(BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        image.load()
    except ValueError:
        raise
    except Image.DecompressionBombError as exc:
        raise ValueError('图片像素过大，请压缩后重试') from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError('文件不是有效的图片') from exc

    # 按长边缩放
    w, h = image.size
    if max(w, h) > target_size:
        ratio = target_size / max(w, h)
        new_size = (int(w * ratio), int(h * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    if image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')

    output = BytesIO()
    image.save(output, format='WEBP', quality=85, method=6)
    data = output.getvalue()
    if not data:
        raise ValueError('图片处理失败')
    return data


def _background_filename(bg_id, original_filename):
    """生成背景图片文件名。"""
    ext = (original_filename.rsplit('.', 1)[-1] if '.' in original_filename else '').lower()
    hash_suffix = hashlib.md5(f'{bg_id}_{_now()}'.encode()).hexdigest()[:8]
    return f'bg_{bg_id}_{hash_suffix}.webp'


def start_upload(user_id, username, upload_file, ip_address):
    """开始异步上传背景图片任务。返回 (success, result_or_error)。"""
    task_id = hashlib.md5(f'{user_id}_{_now()}_{id(upload_file)}'.encode()).hexdigest()[:16]

    with _upload_tasks_lock:
        _upload_tasks[task_id] = {
            'task_id': task_id,
            'status': 'processing',
            'percent': 0,
            'message': '正在处理...',
        }

    # 在后台线程中处理上传
    def _process():
        try:
            raw, ext = _validate_image(upload_file)

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 30
                _upload_tasks[task_id]['message'] = '正在转换格式...'

            # 转换为 WebP
            webp_data = _convert_to_webp(raw)

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 60
                _upload_tasks[task_id]['message'] = '正在保存...'

            # 写入数据库
            with get_db() as conn:
                filename = upload_file.filename
                now = _now()
                cursor = conn.execute(
                    "INSERT INTO backgrounds (user_id, username, filename, file_path, status, is_active, created_at) "
                    "VALUES (?, ?, ?, '', ?, 0, ?)",
                    (user_id, username, filename, STATUS_PENDING, now),
                )
                conn.commit()
                bg_id = cursor.lastrowid

                # 生成文件名并保存
                save_name = _background_filename(bg_id, filename)
                save_path = os.path.join(UPLOAD_BACKGROUNDS_DIR, save_name)
                with open(save_path, 'wb') as f:
                    f.write(webp_data)

                # 更新文件路径
                conn.execute(
                    "UPDATE backgrounds SET file_path = ? WHERE id = ?",
                    (save_path, bg_id),
                )
                conn.commit()

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 100
                _upload_tasks[task_id]['status'] = 'completed'
                _upload_tasks[task_id]['message'] = '上传完成，等待管理员审核'

            log('BackgroundUpload', '背景图片上传成功',
                user_id=user_id, username=username, bg_id=bg_id,
                ip_address=ip_address)

        except ValueError as exc:
            with _upload_tasks_lock:
                _upload_tasks[task_id]['status'] = 'error'
                _upload_tasks[task_id]['message'] = str(exc)
            log('BackgroundUpload', '背景图片上传失败',
                user_id=user_id, username=username, error=str(exc),
                ip_address=ip_address)
        except Exception as exc:
            with _upload_tasks_lock:
                _upload_tasks[task_id]['status'] = 'error'
                _upload_tasks[task_id]['message'] = '上传失败，请稍后重试'
            log('BackgroundUpload', '背景图片上传异常',
                user_id=user_id, username=username, error=str(exc),
                ip_address=ip_address)

    t = threading.Thread(target=_process, daemon=True, name=f'bg-upload-{task_id}')
    t.start()

    return True, {'task_id': task_id}


def get_upload_progress(task_id):
    """查询上传任务进度。"""
    with _upload_tasks_lock:
        return _upload_tasks.get(task_id)


def get_backgrounds(status=None, user_id=None):
    """获取背景图片列表。"""
    with get_db() as conn:
        conditions = []
        params = []
        if status is not None:
            conditions.append('status = ?')
            params.append(status)
        if user_id is not None:
            conditions.append('user_id = ?')
            params.append(user_id)

        where = ' AND '.join(conditions) if conditions else '1=1'
        rows = conn.execute(
            f"SELECT * FROM backgrounds WHERE {where} ORDER BY id DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_active_backgrounds():
    """获取所有已通过且标记为活跃的背景图片（按上传时间排序，最新在前）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM backgrounds WHERE status = ? AND is_active = 1 ORDER BY id DESC",
            (STATUS_APPROVED,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_background(bg_id):
    """获取单个背景图片信息。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        return dict(row) if row else None


def approve_background(bg_id, admin_id, admin_username, ip_address):
    """通过背景图片审核。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_PENDING:
            return False, '该背景图片已处理'

        conn.execute(
            "UPDATE backgrounds SET status = ? WHERE id = ?",
            (STATUS_APPROVED, bg_id),
        )
        conn.commit()

    log('BackgroundApprove', '背景图片审核通过',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, '审核通过'


def reject_background(bg_id, admin_id, admin_username, ip_address):
    """驳回背景图片审核。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_PENDING:
            return False, '该背景图片已处理'

        conn.execute(
            "UPDATE backgrounds SET status = ? WHERE id = ?",
            (STATUS_REJECTED, bg_id),
        )
        conn.commit()

    log('BackgroundReject', '背景图片审核驳回',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, '已驳回'


def toggle_active(bg_id, admin_id, admin_username, ip_address):
    """切换背景图片的活跃状态（设为当前背景或取消）。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_APPROVED:
            return False, '只能对已通过的背景图片操作'

        new_active = 0 if bg['is_active'] else 1
        if new_active:
            # 取消所有其他背景的活跃状态
            conn.execute("UPDATE backgrounds SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "UPDATE backgrounds SET is_active = ? WHERE id = ?",
            (new_active, bg_id),
        )
        conn.commit()

    action = '启用' if new_active else '停用'
    log('BackgroundToggle', f'背景图片{action}',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, f'背景图片已{action}'


def delete_background(bg_id, user_id, is_admin, ip_address):
    """删除背景图片。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['user_id'] != user_id and not is_admin:
            return False, '无权删除'

        # 删除文件
        if bg['file_path'] and os.path.isfile(bg['file_path']):
            try:
                os.remove(bg['file_path'])
            except OSError:
                pass

        conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg_id,))
        conn.commit()

    log('BackgroundDelete', '背景图片删除',
        bg_id=bg_id, user_id=user_id, is_admin=is_admin,
        ip_address=ip_address)
    return True, '背景图片已删除'