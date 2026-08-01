from functools import wraps
import hashlib
from flask import session, redirect, url_for, request, g, jsonify, abort
from core.db import get_db


def _is_json_request():
    """检测当前请求是否期望 JSON 响应（AJAX 或 JSON 内容类型）。"""
    accept = request.headers.get('Accept', '')
    return (
        request.is_json
        or 'application/json' in accept
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


def hash_password(password: str) -> str:
    """统一密码哈希算法（SHA-256）。"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def validate_password(password: str) -> str | None:
    """校验密码强度，返回 None 表示通过，否则返回错误描述。"""
    if len(password) < 8:
        return '密码至少 8 位'
    if not any(c.isalpha() for c in password):
        return '密码必须包含至少一个字母'
    return None


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码是否匹配哈希值。"""
    return hash_password(password) == password_hash


def login_required(f):
    """登录校验装饰器。

    - 普通 GET 请求：未登录时重定向到登录页（带 next 参数）
    - JSON/AJAX 请求：未登录时返回 401 JSON，避免前端解析 HTML 报错
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if _is_json_request():
                return jsonify({'success': False, 'message': '请先登录'}), 401
            return redirect(url_for('main.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理员校验装饰器。

    - 普通 GET 请求：未登录重定向到登录页，非管理员 abort(403)
    - JSON/AJAX 请求：未登录返回 401 JSON，非管理员返回 403 JSON
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if _is_json_request():
                return jsonify({'success': False, 'message': '请先登录'}), 401
            return redirect(url_for('main.login', next=request.path))
        user = get_current_user()
        if not user or not user.get('is_admin'):
            if _is_json_request():
                return jsonify({'success': False, 'message': '权限不足'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    """获取当前登录用户信息（单次请求内缓存，避免重复 DB 查询）。"""
    if 'user_id' not in session:
        return None

    # 使用 Flask g 对象在同一请求内缓存，避免 middleware 和路由重复查询
    if hasattr(g, '_current_user'):
        return g._current_user

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, username, email, is_admin FROM users WHERE id = ?",
            (session['user_id'],),
        ).fetchone()
    finally:
        conn.close()

    user_dict = dict(user) if user else None
    g._current_user = user_dict
    return user_dict
