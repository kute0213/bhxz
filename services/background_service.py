"""背景图片业务服务：上传、审核、列表查询。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
背景图片存储在 uploads/backgrounds/ 目录，自动转换为 WebP 格式，
并为不同屏幕尺寸生成多档变体（768 / 1280 / 1920）：
  - 保存时保持图片自然宽高比并写入 ratio 列（不再强制裁剪 16:9）
  - 取图时客户端携带屏幕比例，服务端将所选档位中心裁剪到该比例后返回
    （结果缓存），实现"上传即转换、按设备比例最适配取图"。
"""

import os
import hashlib
import threading
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from core.db import get_db
from config import UPLOAD_BACKGROUNDS_DIR, USER_IMAGE_MAX_BYTES
from core.logger import log
from services.email import email_service, background_review_result

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

# 响应式变体档位：键为前端请求的 size 参数，值为图片长边最大像素。
# 上传时按此列表生成多档 WebP，serve 时按设备尺寸就近取用。
RESPONSIVE_SIZES = [768, 1280, 1920]
# 主图档位（全站背景默认使用）
PRIMARY_SIZE = 1920

# 默认宽高比（旧数据 / 无比例参数时的回退值，对应 16:9）
RATIO_DEFAULT = 16 / 9
# 服务端接受的比例（宽/高）范围，超出收窄，避免极端裁剪造成画质损失
RATIO_MIN = 0.4
RATIO_MAX = 3.6

# 按屏幕比例裁剪结果缓存（key: (文件路径, 比例保留 2 位)）
_crop_cache = {}
_crop_cache_lock = threading.Lock()
_CROP_CACHE_MAX = 32

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


def _get_natural_ratio(raw):
    """读取图片自然宽高比（宽/高，应用 EXIF 旋转后）。失败回退默认 16:9。"""
    try:
        image = Image.open(BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        w, h = image.size
        if not w or not h:
            return RATIO_DEFAULT
        return max(RATIO_MIN, min(RATIO_MAX, w / h))
    except Exception:
        return RATIO_DEFAULT


def _smart_crop(image, target_ratio=16/9):
    """智能裁剪图片到目标宽高比，从中心裁剪。

    Args:
        image: PIL Image 对象
        target_ratio: 目标宽高比（默认 16:9）

    Returns:
        裁剪后的 PIL Image 对象
    """
    w, h = image.size
    current_ratio = w / h

    if abs(current_ratio - target_ratio) < 0.01:
        # 已经是目标比例，不需要裁剪
        return image

    if current_ratio > target_ratio:
        # 图片太宽，裁剪宽度
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        return image.crop((left, 0, left + new_w, h))
    else:
        # 图片太高，裁剪高度
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        return image.crop((0, top, w, top + new_h))


def _convert_to_webp(raw, target_size=PRIMARY_SIZE, crop_to_ratio=False):
    """将图片转换为 WebP 格式，自动适配尺寸。

    Args:
        raw: 原始图片字节数据
        target_size: 目标长边最大像素（默认 1920px）
        crop_to_ratio: 是否裁剪到 16:9（默认关闭；保存时保持自然宽高比，
            裁剪推迟到取图时按屏幕比例进行）

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

    # 智能裁剪到 16:9
    if crop_to_ratio:
        image = _smart_crop(image, 16/9)

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
    """生成背景图片主文件名（不含尺寸后缀）。"""
    ext = (original_filename.rsplit('.', 1)[-1] if '.' in original_filename else '').lower()
    hash_suffix = hashlib.md5(f'{bg_id}_{_now()}'.encode()).hexdigest()[:8]
    return f'bg_{bg_id}_{hash_suffix}.webp'


def _save_background_variants(bg_id, filename, raw):
    """生成并保存背景图片主图与各档响应式变体。

    保持图片自然宽高比（不再强制裁剪 16:9），裁剪推迟到取图时按屏幕比例进行。

    Args:
        bg_id: 背景图片记录 ID
        filename: 原始文件名（用于生成主文件名）
        raw: 原始图片字节

    Returns:
        (主图绝对路径, 统一主文件名, 自然宽高比)；任一档位处理失败时抛异常（由调用方回滚记录）
    """
    ratio = _get_natural_ratio(raw)
    main_name = _background_filename(bg_id, filename)
    # 主图（1920）优先生成，保证基础路径必然存在
    main_path = os.path.join(UPLOAD_BACKGROUNDS_DIR, main_name)
    with open(main_path, 'wb') as f:
        f.write(_convert_to_webp(raw, target_size=PRIMARY_SIZE, crop_to_ratio=False))

    # 其余档位：失败不影响主图，仅记录日志
    for size in RESPONSIVE_SIZES:
        if size == PRIMARY_SIZE:
            continue
        variant_path = os.path.join(
            UPLOAD_BACKGROUNDS_DIR, f'{main_name[:-5]}_{size}.webp'
        )
        try:
            with open(variant_path, 'wb') as f:
                f.write(_convert_to_webp(raw, target_size=size, crop_to_ratio=False))
        except Exception as exc:
            log('WARNING', 'BackgroundUpload', f'生成 {size}px 变体失败',
                bg_id=bg_id, error=str(exc))

    return main_path, main_name, ratio


def start_upload(user_id, username, upload_file, ip_address):
    """开始异步上传背景图片任务。返回 (success, result_or_error)。"""
    # Flask 会在请求结束后关闭上传流，因此必须在线程启动前读取文件。
    try:
        raw, _ = _validate_image(upload_file)
    except ValueError as exc:
        return False, str(exc)

    original_filename = upload_file.filename
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
        save_path = None
        bg_id = None
        try:
            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 30
                _upload_tasks[task_id]['message'] = '正在转换格式...'

            # 写入数据库（先生成记录拿到 bg_id，再落盘，文件名依赖 bg_id）
            with get_db() as conn:
                filename = original_filename
                now = _now()
                cursor = conn.execute(
                    "INSERT INTO backgrounds (user_id, username, filename, file_path, status, is_active, ratio, created_at) "
                    "VALUES (?, ?, ?, '', ?, 0, ?, ?)",
                    (user_id, username, filename, STATUS_PENDING, RATIO_DEFAULT, now),
                )
                bg_id = cursor.lastrowid
                conn.commit()

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 60
                _upload_tasks[task_id]['message'] = '正在保存...'

            # 生成主图 + 响应式变体并落盘（文件名统一为 bg_<id>_<hash>.webp，不使用原始文件名）
            save_path, main_name, ratio = _save_background_variants(bg_id, original_filename, raw)

            with get_db() as conn:
                conn.execute(
                    "UPDATE backgrounds SET file_path = ?, filename = ?, ratio = ? WHERE id = ?",
                    (save_path, main_name, ratio, bg_id),
                )
                conn.commit()

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 100
                _upload_tasks[task_id]['status'] = 'completed'
                _upload_tasks[task_id]['message'] = '上传完成，等待管理员审核'

            log('INFO', 'BackgroundUpload', '背景图片上传成功',
                user_id=user_id, username=username, bg_id=bg_id,
                ip_address=ip_address)

        except ValueError as exc:
            _fail_upload(task_id, str(exc))
            log('ERROR', 'BackgroundUpload', '背景图片上传失败',
                user_id=user_id, username=username, error=str(exc),
                ip_address=ip_address)
            _cleanup_failed_upload(bg_id, save_path)
        except Exception as exc:
            _fail_upload(task_id, '上传失败，请稍后重试')
            log('ERROR', 'BackgroundUpload', '背景图片上传异常',
                user_id=user_id, username=username, error=str(exc),
                ip_address=ip_address)
            _cleanup_failed_upload(bg_id, save_path)

    t = threading.Thread(target=_process, daemon=True, name=f'bg-upload-{task_id}')
    t.start()

    return True, {'task_id': task_id}


def _fail_upload(task_id, message):
    """标记上传任务失败。"""
    with _upload_tasks_lock:
        _upload_tasks[task_id]['status'] = 'error'
        _upload_tasks[task_id]['message'] = message


def _cleanup_failed_upload(bg_id, save_path):
    """清理失败上传产生的数据库记录与文件。"""
    if bg_id:
        try:
            with get_db() as conn:
                conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg_id,))
                conn.commit()
        except Exception:
            pass
    if save_path and os.path.isfile(save_path):
        try:
            os.remove(save_path)
        except Exception:
            pass


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


def resolve_background_path(bg, size=None):
    """按请求尺寸解析本地背景图片路径（不存在时回退主图）。

    规则：size 为空时返回主图；否则在响应式变体中取与目标最接近
    且不小于目标的档位；该档位文件缺失时逐级回退到主图。
    """
    main_path = bg.get('file_path') if bg else None
    if not main_path or not os.path.isfile(main_path):
        return None

    if size is None:
        return main_path

    # 选取不小于目标宽度的最小档位
    chosen = None
    for s in sorted(RESPONSIVE_SIZES):
        if s >= size:
            chosen = s
            break
    if chosen is None:
        chosen = RESPONSIVE_SIZES[-1]

    if chosen == PRIMARY_SIZE:
        return main_path

    variant_path = os.path.join(
        os.path.dirname(main_path),
        f'{os.path.splitext(os.path.basename(main_path))[0]}_{chosen}.webp',
    )
    if os.path.isfile(variant_path):
        return variant_path
    return main_path


def _crop_to_ratio(data, ratio):
    """将 WebP 字节按目标宽高比中心裁剪，返回新的 WebP 字节。

    原图比例与目标一致（误差 < 0.01）或处理失败时直接返回原数据，避免重复编码。
    """
    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except Exception:
        return data
    w, h = image.size
    if w and h and abs(w / h - ratio) < 0.01:
        return data
    image = _smart_crop(image, ratio)
    output = BytesIO()
    image.save(output, format='WEBP', quality=85, method=6)
    return output.getvalue() or data


def read_background_data(bg, size=None, ratio=None):
    """读取背景图片字节（按设备尺寸就近取档，兼容历史本地路径）。

    ratio 非空时，将所选档位图片按该宽高比中心裁剪后再返回（结果缓存），
    使客户端拿到与其屏幕比例完全匹配的图片，避免多余像素传输。
    """
    path = resolve_background_path(bg, size=size)
    if not path:
        return None
    try:
        with open(path, 'rb') as file:
            data = file.read()
    except OSError:
        return None

    if ratio is None:
        return data

    key = (path, round(ratio, 2))
    with _crop_cache_lock:
        cached = _crop_cache.get(key)
    if cached is not None:
        return cached

    cropped = _crop_to_ratio(data, ratio)
    if cropped is data:
        # 原图比例已匹配，无需裁剪也无需缓存（与直接取档结果一致）
        return data

    with _crop_cache_lock:
        if len(_crop_cache) >= _CROP_CACHE_MAX:
            _crop_cache.clear()
        _crop_cache[key] = cropped
    return cropped


def _send_review_email(bg, approved: bool, admin_username: str):
    """发送审核结果邮件通知给上传者。"""
    if not email_service.is_enabled():
        return
    try:
        with get_db() as conn:
            user = conn.execute(
                "SELECT email FROM users WHERE id = ?",
                (bg['user_id'],),
            ).fetchone()
            if not user or not user['email']:
                return

        subject = '背景图片审核通过' if approved else '背景图片审核未通过'
        html = background_review_result(bg['filename'], approved)
        email_service.send(to=user['email'], subject=subject, body=subject, html=html)
        log('INFO', 'Email', f'已发送背景审核邮件: {user["email"]} <- {subject}')
    except Exception as e:
        log('WARNING', 'Email', f'发送背景审核邮件失败: {e}')


def approve_background(bg_id, admin_id, admin_username, ip_address):
    """通过背景图片审核。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_PENDING:
            return False, '该背景图片已处理'

        conn.execute(
            "UPDATE backgrounds SET status = ?, is_active = 1 WHERE id = ?",
            (STATUS_APPROVED, bg_id),
        )
        # 审核通过即直接启用为当前背景，取消其他背景的启用状态
        conn.execute(
            "UPDATE backgrounds SET is_active = 0 WHERE id != ? AND is_active = 1",
            (bg_id,),
        )
        conn.commit()

    _send_review_email(bg, True, admin_username)

    log('INFO', 'BackgroundApprove', '背景图片审核通过',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, '审核通过'


def remove_background_files(bg):
    """删除背景图片本地文件（主图与全部响应式变体）。失败仅记日志。"""
    main_path = bg.get('file_path') if bg else None
    if not main_path or not os.path.isfile(main_path):
        return
    try:
        os.remove(main_path)
        base_name = os.path.splitext(os.path.basename(main_path))[0]
        for size in RESPONSIVE_SIZES:
            if size == PRIMARY_SIZE:
                continue
            variant_path = os.path.join(
                os.path.dirname(main_path), f'{base_name}_{size}.webp'
            )
            if os.path.isfile(variant_path):
                os.remove(variant_path)
    except Exception as exc:
        log('WARNING', 'BackgroundDelete', '背景图片文件删除失败',
            bg_id=bg.get('id'), error=str(exc))


def reject_background(bg_id, admin_id, admin_username, ip_address):
    """驳回背景图片审核（记录驳回时间，24 小时后由清理服务自动删除）。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_PENDING:
            return False, '该背景图片已处理'

        conn.execute(
            "UPDATE backgrounds SET status = ?, rejected_at = ? WHERE id = ?",
            (STATUS_REJECTED, _now(), bg_id),
        )
        conn.commit()

    _send_review_email(bg, False, admin_username)

    log('INFO', 'BackgroundReject', '背景图片审核驳回',
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
    log('INFO', 'BackgroundToggle', f'背景图片{action}',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, f'背景图片已{action}'


def delete_background(bg_id, user_id, is_admin, ip_address):
    """删除背景图片（主图与响应式变体一并删除）。"""
    with get_db() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['user_id'] != user_id and not is_admin:
            return False, '无权删除'

        # 删除本地主图及响应式变体
        remove_background_files(bg)

        conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg_id,))
        conn.commit()

    log('INFO', 'BackgroundDelete', '背景图片删除',
        bg_id=bg_id, user_id=user_id, is_admin=is_admin,
        ip_address=ip_address)
    return True, '背景图片已删除'
