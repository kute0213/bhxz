"""用户头像与全站主页背景路由。"""

from io import BytesIO

from flask import abort, flash, redirect, request, send_file, url_for

from core.auth import get_current_user, login_required
from core.db import get_db
from config import SITE_BACKGROUND_PREFIX
from routes.main import main_bp
from services.logger import log
from services.object_storage import ObjectStorageError, object_storage
from services.settings_manager import get_setting


def _update_user_object_key(user_id, column, object_key):
    """仅允许更新已声明的用户图片列。"""
    if column != 'avatar_key':
        raise ValueError('非法的用户图片字段')
    with get_db() as conn:
        conn.execute(f'UPDATE users SET {column} = ? WHERE id = ?', (object_key, user_id))


def _serve_private_image(object_key, filename):
    try:
        data, content_type = object_storage.get_object(object_key)
    except ObjectStorageError:
        abort(404)
    response = send_file(
        BytesIO(data),
        mimetype=content_type,
        download_name=filename,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@main_bp.route('/media/avatar/<int:user_id>')
def user_avatar(user_id):
    """通过站内代理读取用户头像，MinIO Bucket 无需公开。"""
    with get_db() as conn:
        row = conn.execute('SELECT avatar_key FROM users WHERE id = ?', (user_id,)).fetchone()
    if not row or not row['avatar_key']:
        abort(404)
    return _serve_private_image(row['avatar_key'], f'avatar-{user_id}.webp')


@main_bp.route('/media/site-background')
def site_background():
    """读取管理员配置的全站首页背景。"""
    object_key = get_setting('SITE_BACKGROUND_ACTIVE_KEY', '')
    if not _is_site_background_key(object_key):
        abort(404)
    response = _serve_private_image(object_key, 'site-background.webp')
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


def _is_site_background_key(object_key):
    """限制只能读取站点背景图库中的 WebP 对象。"""
    return bool(
        object_key
        and object_key.startswith(SITE_BACKGROUND_PREFIX)
        and object_key.endswith('.webp')
    )


@main_bp.route('/media/site-background-option')
def site_background_option():
    """读取管理后台图库预览图。"""
    object_key = (request.args.get('key') or '').strip()
    if not _is_site_background_key(object_key):
        abort(404)
    response = _serve_private_image(object_key, 'site-background-option.webp')
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@main_bp.route('/settings/avatar', methods=['POST'])
@login_required
def upload_avatar():
    user = get_current_user()
    try:
        object_key = object_storage.save_user_image(user['id'], 'avatar', request.files.get('avatar'))
        _update_user_object_key(user['id'], 'avatar_key', object_key)
        log('UserMedia', '用户头像上传成功', user_id=user['id'], username=user['username'])
        flash('头像更新成功！', 'success')
    except ObjectStorageError as exc:
        log('UserMedia', '用户头像上传失败', user_id=user['id'], error=str(exc))
        flash(str(exc), 'error')
    return redirect(url_for('main.settings', tab='avatar'))


@main_bp.route('/settings/avatar/delete', methods=['POST'])
@login_required
def delete_avatar():
    user = get_current_user()
    try:
        object_storage.delete_object(user.get('avatar_key'))
        _update_user_object_key(user['id'], 'avatar_key', '')
        flash('头像已恢复为默认样式', 'success')
    except ObjectStorageError as exc:
        log('UserMedia', '用户头像删除失败', user_id=user['id'], error=str(exc))
        flash('头像删除失败，请稍后重试', 'error')
    return redirect(url_for('main.settings', tab='avatar'))

