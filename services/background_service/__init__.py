"""背景图片业务服务：上传、审核、列表查询。

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
背景图片存储在 uploads/backgrounds/ 目录，自动转换为 WebP 格式。

磁盘上**每张背景只保留一个文件**（长边 ≤ 1920 的主图），不再生成 / 按需缓存
任何尺寸变体。取图时服务端**只做查询与返回**：按客户端上报的屏幕宽高比挑选一张
最接近的已启用背景，原样返回主图字节（不缩放、不裁剪）；裁剪与铺满由浏览器按
CSS `background-size` 完成。
"""

import os
import hashlib
import threading
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from core.db import get_db, transaction
from core.shared.snowflake import next_id
from config import UPLOAD_BACKGROUNDS_DIR, USER_IMAGE_MAX_BYTES, get_page_size
from core.system.logger import log_module, register_module_log
from services.mail import email_service, background_review_result

register_module_log('background')

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

# 历史遗留的尺寸变体档位（仅用于删除背景时清理旧文件，不再生成）
RESPONSIVE_SIZES = [768, 1280, 1920]
# 主图档位：磁盘上唯一文件的缩放上限（全站背景默认使用）
PRIMARY_SIZE = 1920

# 默认宽高比（旧数据 / 无比例参数时的回退值，对应 16:9）
RATIO_DEFAULT = 16 / 9
# 自然宽高比的合理范围（宽/高），超出收窄，避免记录异常值
RATIO_MIN = 0.4
RATIO_MAX = 3.6

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

    # 防火墙文件守卫：拒绝危险扩展名 + 校验文件头魔数（防改名伪装）
    from services.firewall.protection.file_guard import check_upload, KIND_IMAGE
    ok, message = check_upload(
        upload, KIND_IMAGE,
        max_bytes=USER_IMAGE_MAX_BYTES,
        allowed_extensions=ALLOWED_EXTENSIONS,
        source='background',
    )
    if not ok:
        raise ValueError(message)

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


def _convert_to_webp(raw):
    """将图片转换为 WebP 格式，保持自然宽高比，按长边缩放到 PRIMARY_SIZE 以内。

    不做任何裁剪：裁切由浏览器按展示区域完成（CSS background-size: cover）。

    Args:
        raw: 原始图片字节数据

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
    if max(w, h) > PRIMARY_SIZE:
        ratio = PRIMARY_SIZE / max(w, h)
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


def _format_ratio(ratio):
    """把宽高比格式化为文件名友好的短字符串（保留 4 位小数并去掉尾随零）。"""
    return f'{ratio:.4f}'.rstrip('0').rstrip('.')


def _background_filename(bg_id, ratio):
    """生成背景图片主文件名：雪花 ID + 比例（如 `123456789_1.7778.webp`）。"""
    return f'{bg_id}_{_format_ratio(ratio)}.webp'


def _save_background_master(bg_id, raw):
    """保存背景图片主图（磁盘上唯一的文件），返回 (主图绝对路径, 主文件名, 自然宽高比)。

    保持自然宽高比，只按长边缩放到 PRIMARY_SIZE 以内；裁切与按屏幕缩放由客户端
    完成，因此不再生成任何尺寸变体文件。

    Args:
        bg_id: 背景图片记录 ID（雪花 ID）
        raw: 原始图片字节
    """
    ratio = _get_natural_ratio(raw)
    main_name = _background_filename(bg_id, ratio)
    main_path = os.path.join(UPLOAD_BACKGROUNDS_DIR, main_name)
    with open(main_path, 'wb') as f:
        f.write(_convert_to_webp(raw))
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
            with transaction() as conn:
                filename = original_filename
                now = _now()
                bg_id = next_id()
                conn.execute(
                    "INSERT INTO backgrounds (id, user_id, username, filename, file_path, status, is_active, ratio, created_at) "
                    "VALUES (?, ?, ?, ?, '', ?, 0, ?, ?)",
                    (bg_id, user_id, username, filename, STATUS_PENDING, RATIO_DEFAULT, now),
                )

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 60
                _upload_tasks[task_id]['message'] = '正在保存...'

            # 生成主图并落盘（文件名统一为 <雪花ID>_<比例>.webp，不使用原始文件名）
            save_path, main_name, ratio = _save_background_master(bg_id, raw)

            with transaction() as conn:
                conn.execute(
                    "UPDATE backgrounds SET file_path = ?, filename = ?, ratio = ? WHERE id = ?",
                    (save_path, main_name, ratio, bg_id),
                )
                conn.commit()

            with _upload_tasks_lock:
                _upload_tasks[task_id]['percent'] = 100
                _upload_tasks[task_id]['status'] = 'completed'
                _upload_tasks[task_id]['message'] = '上传完成，等待管理员审核'

            log_module('background', 'INFO', 'BackgroundUpload', '背景图片上传成功',
                user_id=user_id, username=username, bg_id=bg_id,
                ip_address=ip_address)

        except ValueError as exc:
            _fail_upload(task_id, str(exc))
            log_module('background', 'ERROR', 'BackgroundUpload', '背景图片上传失败',
                user_id=user_id, username=username, error=str(exc),
                ip_address=ip_address)
            _cleanup_failed_upload(bg_id, save_path)
        except Exception as exc:
            _fail_upload(task_id, '上传失败，请稍后重试')
            log_module('background', 'ERROR', 'BackgroundUpload', '背景图片上传异常',
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
            with transaction() as conn:
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
    with transaction() as conn:
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


def get_admin_page_size() -> int:
    """后台背景图片列表每页数量，由系统设置 BACKGROUNDS_PER_PAGE 控制。"""
    return get_page_size('BACKGROUNDS_PER_PAGE', 5)


def get_backgrounds_page(status=None, page=1, page_size=None):
    """分页获取背景图片列表，返回 (items, total)。"""
    if page < 1:
        page = 1
    if page_size is None:
        page_size = get_admin_page_size()
    else:
        page_size = max(1, min(int(page_size), 100))
    with transaction() as conn:
        conditions = []
        params = []
        if status is not None:
            conditions.append('status = ?')
            params.append(status)
        where = ' AND '.join(conditions) if conditions else '1=1'

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM backgrounds WHERE {where}", params
        ).fetchone()['c']
        rows = conn.execute(
            f"SELECT * FROM backgrounds WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        return [dict(r) for r in rows], total


def get_active_backgrounds():
    """获取所有已通过且标记为活跃（启用）的背景图片。

    这些图片共同构成「可用于全站背景」的图片池：多张可同时处于启用状态，
    由 `get_background_for_ratio()` 按屏幕宽高比从中挑选最合适的一张。
    """
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM backgrounds WHERE status = ? AND is_active = 1 ORDER BY id DESC",
            (STATUS_APPROVED,),
        ).fetchall()
        return [dict(r) for r in rows]


def _bg_ratio(bg):
    """读取背景记录的宽高比（宽/高）；缺失或非法时回退默认 16:9。"""
    try:
        ratio = float(bg.get('ratio') or 0)
    except (TypeError, ValueError):
        ratio = 0.0
    if ratio <= 0:
        return RATIO_DEFAULT
    return ratio


def get_background_for_ratio(ratio=None):
    """从已启用的背景图片中挑选宽高比最接近 `ratio`（宽/高）的一张。

    * `ratio` 为空或非法 —— 返回最新启用的一张（保持旧行为）；
    * 未启用任何背景 —— 返回 None。

    只做查询与挑选，不缩放、不裁剪；裁剪与铺满由浏览器完成。
    """
    actives = get_active_backgrounds()
    if not actives:
        return None
    if ratio is None:
        return actives[0]
    target = max(RATIO_MIN, min(RATIO_MAX, float(ratio)))
    return min(actives, key=lambda bg: abs(_bg_ratio(bg) - target))


def get_background(bg_id):
    """获取单个背景图片信息。"""
    with transaction() as conn:
        row = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        return dict(row) if row else None


def resolve_background_path(bg):
    """返回背景图片的主图本地路径（磁盘上唯一的文件）；不存在时返回 None。"""
    main_path = bg['file_path'] if bg else None
    if not main_path or not os.path.isfile(main_path):
        return None
    return main_path


def read_background_data(bg):
    """读取背景图片字节（磁盘上取唯一主图，原样返回，不做任何处理）。"""
    path = resolve_background_path(bg)
    if not path:
        return None
    try:
        with open(path, 'rb') as file:
            return file.read()
    except OSError:
        return None


def background_etag(bg):
    """背景图片的缓存校验值：主图路径 + 修改时间。

    全站背景的 URL 固定（不带 ID，仅带 ratio 参数），管理员切换 / 启用背景后
    内容可能变化，因此需要 ETag 让浏览器重新校验，避免长期缓存到旧图。
    """
    path = (bg or {}).get('file_path') or ''
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        stamp = 0
    return hashlib.md5(f'{path}:{stamp}'.encode()).hexdigest()


def _send_review_email(bg, approved: bool, admin_username: str):
    """发送审核结果邮件通知给上传者。"""
    if not email_service.is_enabled():
        return
    try:
        with transaction() as conn:
            user = conn.execute(
                "SELECT email FROM users WHERE id = ?",
                (bg['user_id'],),
            ).fetchone()
            if not user or not user['email']:
                return

        subject = '背景图片审核通过' if approved else '背景图片审核未通过'
        html = background_review_result(bg['filename'], approved)
        email_service.send(to=user['email'], subject=subject, body=subject, html=html)
        log_module('background', 'INFO', 'Email', f'已发送背景审核邮件: {user["email"]} <- {subject}')
    except Exception as e:
        log_module('background', 'WARNING', 'Email', f'发送背景审核邮件失败: {e}')


def approve_background(bg_id, admin_id, admin_username, ip_address):
    """通过背景图片审核，并将其加入「可用于全站背景」的图片池。

    不再取消其他背景的启用状态：多张背景可同时启用，由
    `get_background_for_ratio()` 按访问者屏幕宽高比挑选最合适的一张。
    """
    with transaction() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_PENDING:
            return False, '该背景图片已处理'

        conn.execute(
            "UPDATE backgrounds SET status = ?, is_active = 1 WHERE id = ?",
            (STATUS_APPROVED, bg_id),
        )
        conn.commit()

    _send_review_email(bg, True, admin_username)

    log_module('background', 'INFO', 'BackgroundApprove', '背景图片审核通过',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, '审核通过'


def remove_background_files(bg):
    """删除背景图片本地文件（主图；顺带清理历史遗留的尺寸变体文件）。失败仅记日志。"""
    main_path = bg['file_path'] if bg else None
    if not main_path or not os.path.isfile(main_path):
        return
    try:
        os.remove(main_path)
        # 历史版本曾为每张图生成 <主名>_<size>.webp 变体，删除记录时一并清掉，
        # 避免这些不再被使用的文件长期占盘
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
        log_module('background', 'WARNING', 'BackgroundDelete', '背景图片文件删除失败',
            bg_id=bg['id'], error=str(exc))


def reject_background(bg_id, admin_id, admin_username, ip_address):
    """驳回背景图片审核（记录驳回时间，24 小时后由清理服务自动删除）。"""
    with transaction() as conn:
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

    log_module('background', 'INFO', 'BackgroundReject', '背景图片审核驳回',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, '已驳回'


def toggle_active(bg_id, admin_id, admin_username, ip_address):
    """切换单张背景图片的启用状态（加入 / 移出「可用于全站背景」的图片池）。

    各张背景独立开关，不再互相影响：可同时启用多张，由
    `get_background_for_ratio()` 按访问者屏幕宽高比挑选最合适的一张。
    """
    with transaction() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['status'] != STATUS_APPROVED:
            return False, '只能对已通过的背景图片操作'

        new_active = 0 if bg['is_active'] else 1
        conn.execute(
            "UPDATE backgrounds SET is_active = ? WHERE id = ?",
            (new_active, bg_id),
        )
        conn.commit()

    action = '启用' if new_active else '停用'
    log_module('background', 'INFO', 'BackgroundToggle', f'背景图片{action}',
        bg_id=bg_id, admin_id=admin_id, admin_username=admin_username,
        ip_address=ip_address)
    return True, f'背景图片已{action}'


def delete_background(bg_id, user_id, is_admin, ip_address):
    """删除背景图片（主图与响应式变体一并删除）。"""
    with transaction() as conn:
        bg = conn.execute("SELECT * FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if not bg:
            return False, '背景图片不存在'
        if bg['user_id'] != user_id and not is_admin:
            return False, '无权删除'

        # 删除本地主图及响应式变体
        remove_background_files(bg)

        conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg_id,))
        conn.commit()

    log_module('background', 'INFO', 'BackgroundDelete', '背景图片删除',
        bg_id=bg_id, user_id=user_id, is_admin=is_admin,
        ip_address=ip_address)
    return True, '背景图片已删除'