r"""公开文件/目录服务。

功能：
- 管理员可在后台配置将本地文件/目录映射到指定 URL 路径对外公开
- 支持相对路径（相对于项目根目录）：如 sw.js、verify
- 支持绝对路径：如 /home/user/docs、/opt/files、C:\Users\Public\docs
- 支持单文件公开（如 /sw.js -> ./sw.js）
- 支持目录公开（如 /verify -> ./verify/，子路径自动映射）
- 路径安全检查：禁止路径遍历攻击、禁止访问敏感目录
- MIME 类型自动识别
- 缓存控制
"""

import os
import platform
import mimetypes
from datetime import datetime
from flask import Blueprint, send_file, abort, request, render_template, redirect, url_for, flash

from config import APP_ROOT
from core.auth import login_required, get_current_user
from core.db import get_db

public_bp = Blueprint('public', __name__)

# 项目内部禁止公开的敏感目录/文件（相对路径时检查）
FORBIDDEN_LOCAL_PARTS = {
    'core', 'services', 'routes', 'templates', '__pycache__',
    '.git', 'backups', '.env', 'config.py', 'app.py',
    'requirements.txt', 'site.duckdb', 'site.duckdb.wal'
}

# 系统敏感目录前缀（绝对路径时禁止）
FORBIDDEN_SYSTEM_PREFIXES = {
    '/etc', '/proc', '/sys', '/dev', '/boot', '/root',
    '/var/log', '/var/run', '/run', '/usr/bin', '/usr/sbin',
    '/bin', '/sbin', '/lib', '/lib64',
}


def _is_windows_drive_path(path):
    """检测是否为 Windows 盘符路径（如 C:\\ 或 D:/）。"""
    if not path:
        return False
    # 检查原始路径前3个字符是否为 X:\\ 或 X:/
    if len(path) >= 3 and path[1] == ':' and path[0].isalpha():
        if path[2] in ('\\', '/'):
            return True
    return False


def _is_absolute_path(path):
    """判断路径是否为绝对路径（兼容 Linux 和 Windows）。"""
    if not path:
        return False
    # 优先检测 Windows 盘符路径（在 Linux 上 normpath 会改变它）
    if _is_windows_drive_path(path):
        return True
    norm = os.path.normpath(path)
    if os.path.isabs(norm):
        return True
    return False


def _resolve_local_path(local_path):
    """将配置的本地路径解析为绝对路径。

    - 绝对路径：直接返回 normpath 后的绝对路径
    - 相对路径：相对于 APP_ROOT 解析
    """
    if not local_path:
        return None
    # Windows 盘符路径：直接 normpath，不使用 os.path.abspath（避免 Linux 上加前缀）
    if _is_windows_drive_path(local_path):
        return os.path.normpath(local_path)
    norm = os.path.normpath(local_path)
    if os.path.isabs(norm):
        return os.path.abspath(norm)
    return os.path.abspath(os.path.join(APP_ROOT, norm))


def _is_path_safe(local_path, is_directory):
    """检查本地路径是否安全。

    策略：
    1. 禁止空路径
    2. 禁止路径中包含 .. 组件（路径遍历）
    3. 绝对路径：禁止访问系统敏感目录，禁止指向项目内部敏感目录
    4. 相对路径：禁止超出项目根目录，禁止映射到项目敏感目录
    5. 不能公开根目录本身
    6. 类型一致性检查（文件 vs 目录）

    Args:
        local_path: 用户配置的本地路径（相对或绝对）
        is_directory: 用户标记的目录/文件类型

    Returns:
        (bool, str): (是否安全, 错误信息)
    """
    if not local_path:
        return False, '本地路径不能为空'

    # 检查原始路径中是否包含 .. 组件
    # os.path.normpath 会消除 ..，但我们应在规范化前检查
    raw_parts = local_path.replace('\\', '/').split('/')
    if '..' in raw_parts:
        return False, '路径不能包含 ..（路径遍历攻击）'

    abs_path = _resolve_local_path(local_path)
    if abs_path is None:
        return False, '路径解析失败'

    # 禁止公开根目录
    if abs_path == os.path.abspath('/'):
        return False, '不能公开系统根目录'

    # 磁盘根目录检查（Windows 盘符根目录如 C:\、C:/）
    if _is_windows_drive_path(local_path):
        # 去掉尾部斜杠后若只剩下 "C:" 或长度<=3，则是根目录
        stripped = local_path.replace('\\', '/').rstrip('/')
        if len(stripped) <= 3:
            return False, '不能公开磁盘根目录'

    is_abs = _is_absolute_path(local_path)
    app_root_abs = os.path.abspath(APP_ROOT)

    if is_abs:
        # 绝对路径安全检查
        abs_norm = abs_path.replace('\\', '/')

        # 检查是否在系统敏感目录下
        for prefix in FORBIDDEN_SYSTEM_PREFIXES:
            prefix_norm = prefix.rstrip('/')
            if abs_norm == prefix_norm or abs_norm.startswith(prefix_norm + '/'):
                return False, f'禁止访问系统敏感目录：{prefix}'

        # Windows 系统目录检查（跨平台：无论当前系统是否 Windows，只要路径是 Windows 风格就检查）
        if _is_windows_drive_path(local_path):
            lower = abs_path.lower()
            win_forbidden = ['windows', 'program files', 'programdata',
                             'system32', 'syswow64', 'system volume information']
            for part in lower.replace('/', '\\').split('\\'):
                if part in win_forbidden:
                    return False, f'禁止访问 Windows 系统目录：{part}'

        # 绝对路径指向项目内部时，也要检查是否命中项目敏感目录
        if abs_path == app_root_abs or abs_path.startswith(app_root_abs + os.sep):
            rel_to_app = os.path.relpath(abs_path, app_root_abs).replace('\\', '/')
            first_part = rel_to_app.split('/')[0]
            if first_part in FORBIDDEN_LOCAL_PARTS:
                return False, f'禁止公开项目敏感路径：{first_part}'

    else:
        # 相对路径安全检查：不能超出项目根目录
        if not (abs_path == app_root_abs or abs_path.startswith(app_root_abs + os.sep)):
            return False, '相对路径不能超出项目根目录'

        # 检查是否映射到项目敏感目录
        rel_to_app = os.path.relpath(abs_path, app_root_abs).replace('\\', '/')
        first_part = rel_to_app.split('/')[0]
        if first_part in FORBIDDEN_LOCAL_PARTS:
            return False, f'禁止公开项目敏感路径：{first_part}'

    # 类型一致性检查（路径已存在时）
    if os.path.exists(abs_path):
        if is_directory and os.path.isfile(abs_path):
            return False, '指定路径是文件，但您标记为目录'
        if not is_directory and os.path.isdir(abs_path):
            return False, '指定路径是目录，但您标记为文件'

    return True, ''


def _send_file(filepath):
    """发送文件，设置正确的 MIME 类型和缓存头。"""
    mimetype, _ = mimetypes.guess_type(filepath)
    if mimetype is None:
        mimetype = 'application/octet-stream'

    if filepath.endswith('.js'):
        mimetype = 'application/javascript; charset=utf-8'
    elif filepath.endswith('.css'):
        mimetype = 'text/css; charset=utf-8'
    elif filepath.endswith('.json'):
        mimetype = 'application/json; charset=utf-8'
    elif filepath.endswith(('.html', '.htm')):
        mimetype = 'text/html; charset=utf-8'
    elif filepath.endswith('.txt'):
        mimetype = 'text/plain; charset=utf-8'
    elif filepath.endswith('.xml'):
        mimetype = 'application/xml; charset=utf-8'

    response = send_file(filepath, mimetype=mimetype)
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


def _join_under_base(base, sub):
    """安全地在 base 目录下拼接子路径，防止路径遍历。

    返回绝对路径，如果结果逃出 base 则返回 None。
    """
    if not sub:
        return base

    sub = os.path.normpath(sub)
    if '..' in sub.replace('\\', '/').split('/'):
        return None

    result = os.path.abspath(os.path.join(base, sub))
    if not (result == base or result.startswith(base + os.sep)):
        return None
    return result


def try_serve_public(path):
    """尝试为请求路径提供公开文件服务。

    Args:
        path: 请求路径（不含前导斜杠，可能为空字符串表示根路径）

    Returns:
        Response 对象如果匹配成功，否则返回 None
    """
    full_path = '/' + path if path else '/'
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM public_paths WHERE is_active = 1 ORDER BY LENGTH(url_path) DESC"
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        url_path = row['url_path'].rstrip('/')
        local_path = row['local_path']
        is_directory = bool(row['is_directory'])

        if not is_directory:
            # 单文件：URL 必须完全匹配
            if full_path.rstrip('/') == url_path.rstrip('/'):
                abs_path = _resolve_local_path(local_path)
                if abs_path and os.path.isfile(abs_path):
                    return _send_file(abs_path)
        else:
            # 目录映射
            req_prefix = url_path.rstrip('/')
            matched = False
            sub = ''

            if full_path.rstrip('/') == req_prefix:
                matched = True
                sub = ''
            elif req_prefix and full_path.startswith(req_prefix + '/'):
                matched = True
                sub = full_path[len(req_prefix) + 1:]
            elif req_prefix == '' and full_path.startswith('/'):
                # url_path 为 '/' 的特殊情况
                matched = True
                sub = full_path[1:]  # 去掉前导 /

            if not matched:
                continue

            abs_base = _resolve_local_path(local_path)
            if abs_base is None:
                continue

            abs_target = _join_under_base(abs_base, sub)
            if abs_target is None:
                continue

            if os.path.isfile(abs_target):
                return _send_file(abs_target)

            if os.path.isdir(abs_target):
                for idx_name in ['index.html', 'index.htm']:
                    idx_path = os.path.join(abs_target, idx_name)
                    if os.path.isfile(idx_path):
                        return _send_file(idx_path)

    return None


# ---------------------------------------------------------------------------
# 管理后台：公开路径管理
# ---------------------------------------------------------------------------

@public_bp.route('/admin/public-files')
@login_required
def admin_public_files_page():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        paths = conn.execute(
            "SELECT * FROM public_paths ORDER BY is_directory DESC, url_path ASC"
        ).fetchall()
    finally:
        conn.close()

    return render_template('admin/admin_public_files.html', user=user, paths=paths)


@public_bp.route('/admin/public-files/add', methods=['POST'])
@login_required
def admin_public_files_add():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    url_path = request.form.get('url_path', '').strip()
    local_path = request.form.get('local_path', '').strip()
    is_directory = request.form.get('is_directory') == 'on' or request.form.get('is_directory') == '1'

    if not url_path.startswith('/'):
        url_path = '/' + url_path

    if url_path != '/':
        url_path = url_path.rstrip('/')

    safe, err = _is_path_safe(local_path, is_directory)
    if not safe:
        flash(err, 'error')
        return redirect(url_for('public.admin_public_files_page'))

    abs_path = _resolve_local_path(local_path)
    if abs_path and not os.path.exists(abs_path):
        flash(f'注意：本地路径 {local_path} 当前不存在，但配置已保存', 'warning')

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO public_paths (url_path, local_path, is_directory, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            (url_path, local_path.replace('\\', '/'), 1 if is_directory else 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        flash('公开路径已添加', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'添加失败：{e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('public.admin_public_files_page'))


@public_bp.route('/admin/public-files/toggle/<int:pid>', methods=['POST'])
@login_required
def admin_public_files_toggle(pid):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        row = conn.execute("SELECT is_active FROM public_paths WHERE id = ?", (pid,)).fetchone()
        if not row:
            flash('路径不存在', 'error')
        else:
            new_status = 0 if row['is_active'] else 1
            conn.execute("UPDATE public_paths SET is_active = ? WHERE id = ?", (new_status, pid))
            conn.commit()
            flash('状态已更新', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'更新失败：{e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('public.admin_public_files_page'))


@public_bp.route('/admin/public-files/delete/<int:pid>', methods=['POST'])
@login_required
def admin_public_files_delete(pid):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        conn.execute("DELETE FROM public_paths WHERE id = ?", (pid,))
        conn.commit()
        flash('公开路径已删除', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'删除失败：{e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('public.admin_public_files_page'))
