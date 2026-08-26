"""用户头像与主页背景路由（本地文件存储）。"""

import os
from io import BytesIO

from flask import abort, current_app, flash, redirect, request, send_file, url_for

from config import UPLOAD_DIR, USER_IMAGE_MAX_BYTES
from core.auth import get_current_user, login_required
from core.db import get_db
from routes.main import main_bp
from services.logger import log
from PIL import Image, ImageOps, UnidentifiedImageError

_MEDIA_DIR = os.path.join(UPLOAD_DIR, 'media')
_IMAGE_SPECS = {
    'avatar': {'size': (512, 512), 'quality': 88, 'crop': True},
}


def _user_media_dir(user_id):
    d = os.path.join(_MEDIA_DIR, str(user_id))
    os.makedirs(d, exist_ok=True)
    return d


def _media_path(user_id, kind):
    return os.path.join(_user_media_dir(user_id), f'{kind}.webp')


def _update_user_object_key(user_id, column, object_key):
    if column not in ('avatar_key',):
        raise ValueError('非法的用户图片字段')
    with get_db() as conn:
        conn.execute(f'UPDATE users SET {column} = ? WHERE id = ?', (object_key, user_id))


def _serve_local_image(filepath, filename):
    if not os.path.isfile(filepath):
        abort(404)
    response = send_file(
        filepath,
        mimetype='image/webp',
        download_name=filename,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@main_bp.route('/media/avatar/<int:user_id>')
def user_avatar(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT avatar_key FROM users WHERE id = ?', (user_id,)).fetchone()
    if not row or not row['avatar_key']:
        abort(404)
    return _serve_local_image(row['avatar_key'], f'avatar-{user_id}.webp')


def _read_upload(upload):
    if not upload or not upload.filename:
        raise ValueError('请选择图片')

    raw = upload.stream.read(USER_IMAGE_MAX_BYTES + 1)
    if not raw:
        raise ValueError('上传的图片为空')
    if len(raw) > USER_IMAGE_MAX_BYTES:
        raise ValueError('图片不能超过 10MB')
    return raw


def _convert_image(upload, kind):
    spec = _IMAGE_SPECS.get(kind)
    if not spec:
        raise ValueError('不支持的图片类型')

    raw = _read_upload(upload)
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

    if spec['crop']:
        image = ImageOps.fit(image, spec['size'], method=Image.Resampling.LANCZOS)
    else:
        image.thumbnail(spec['size'], Image.Resampling.LANCZOS)

    if image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')

    output = BytesIO()
    image.save(output, format='WEBP', quality=spec['quality'], method=6)
    data = output.getvalue()
    if not data:
        raise ValueError('图片处理失败')
    return data


@main_bp.route('/settings/avatar', methods=['POST'])
@login_required
def upload_avatar():
    user = get_current_user()
    try:
        data = _convert_image(request.files.get('avatar'), 'avatar')
        filepath = _media_path(user['id'], 'avatar')
        with open(filepath, 'wb') as f:
            f.write(data)
        _update_user_object_key(user['id'], 'avatar_key', filepath)
        log('UserMedia', '用户头像上传成功', user_id=user['id'], username=user['username'])
        flash('头像更新成功！', 'success')
    except ValueError as exc:
        log('UserMedia', '用户头像上传失败', user_id=user['id'], error=str(exc))
        flash(str(exc), 'error')
    return redirect(url_for('main.settings', tab='avatar'))


@main_bp.route('/settings/avatar/delete', methods=['POST'])
@login_required
def delete_avatar():
    user = get_current_user()
    try:
        filepath = user.get('avatar_key', '')
        if filepath and os.path.isfile(filepath):
            os.remove(filepath)
        _update_user_object_key(user['id'], 'avatar_key', '')
        flash('头像已恢复为默认样式', 'success')
    except Exception as exc:
        log('UserMedia', '用户头像删除失败', user_id=user['id'], error=str(exc))
        flash('头像删除失败，请稍后重试', 'error')
    return redirect(url_for('main.settings', tab='avatar'))


