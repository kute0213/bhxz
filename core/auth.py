from functools import wraps
from flask import session, redirect, url_for, request, abort, g
from core.db import get_db


def allowed_file(filename):
    return bool(filename)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        if not session.get('is_admin', False):
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
    user = conn.execute(
        "SELECT id, username, is_admin FROM users WHERE id = ?",
        (session['user_id'],),
    ).fetchone()
    conn.close()

    user_dict = dict(user) if user else None
    g._current_user = user_dict
    return user_dict
