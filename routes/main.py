"""公开页面路由：首页、登录、注册、找回密码、设置、性能监控。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from core.auth import login_required, get_current_user
from core.db import get_db
from config import get_config_value
from services.email import normalize_email
from services.user_service import (
    register, login, forgot_password,
    change_username, change_password, change_email, delete_account,
)
from services.logger import log

main_bp = Blueprint('main', __name__)


def _is_safe_redirect_url(target: str) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme


@main_bp.route('/')
def home():
    user = get_current_user()
    conn = get_db()
    try:
        mod_intros = conn.execute(
            "SELECT * FROM mod_intros ORDER BY id ASC"
        ).fetchall()
        mod_intros = [dict(r) for r in mod_intros]
    finally:
        conn.close()
    return render_template(
        'index.html', user=user, mod_intros=mod_intros,
        map_url=get_config_value('MAP_URL', 'https://map.bhxz.tw.kg'),
        qq_group_url=get_config_value('QQ_GROUP_URL', ''),
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

@main_bp.route('/register', methods=['GET', 'POST'], endpoint='register')
def register_view():
    email_verify_enabled = get_config_value('REGISTER_EMAIL_VERIFY', False)
    group_code_verified = session.get('group_code_verified', False)

    if request.method == 'POST':
        success, result = register(
            username=request.form.get('username', '').strip(),
            password=request.form.get('password', ''),
            confirm=request.form.get('confirm', ''),
            verify_code=request.form.get('verify_code', '').strip(),
            captcha_input=request.form.get('captcha', '').strip(),
            captcha_id=request.form.get('captcha_id', '').strip(),
            email=normalize_email(request.form.get('email', '')),
            email_code=request.form.get('email_code', '').strip(),
            ip_address=request.remote_addr,
            email_verify_enabled=email_verify_enabled,
        )
        if not success:
            return render_template('register.html', error=result,
                                   email_verify_enabled=email_verify_enabled,
                                   group_code_verified=group_code_verified)
        # 自动登录
        session.clear()
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        session['is_admin'] = result['is_admin']
        session.permanent = True
        return redirect(url_for('main.home'))

    return render_template('register.html', email_verify_enabled=email_verify_enabled,
                           group_code_verified=group_code_verified)


@main_bp.route('/api/verify-group-code', methods=['POST'])
def verify_group_code():
    from config import REGISTER_VERIFY_CODE
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()
    if not code:
        log('VerifyGroupCode', '群内验证码为空', ip=request.remote_addr)
        return jsonify({'success': False, 'message': '请输入验证码'}), 400
    if code != REGISTER_VERIFY_CODE:
        log('VerifyGroupCode', '群内验证码错误', ip=request.remote_addr)
        return jsonify({'success': False, 'message': '验证码错误，请在QQ群公告中获取正确验证码'}), 400
    session['group_code_verified'] = True
    session.permanent = True
    log('VerifyGroupCode', '群内验证码验证成功', ip=request.remote_addr)
    return jsonify({'success': True, 'message': '验证成功'})


@main_bp.route('/api/verify-group-code/check')
def check_group_code():
    return jsonify({'verified': session.get('group_code_verified', False)})


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

@main_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login_view():
    if request.method == 'POST':
        success, result = login(
            username=request.form.get('username', '').strip(),
            password=request.form.get('password', ''),
            captcha_input=request.form.get('captcha', '').strip(),
            captcha_id=request.form.get('captcha_id', '').strip(),
            ip_address=request.remote_addr,
        )
        if not success:
            return render_template('login.html', error=result)

        session.clear()
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        session['is_admin'] = result['is_admin']
        session.permanent = True

        next_page = request.args.get('next') or request.form.get('next')
        if next_page and _is_safe_redirect_url(next_page):
            return redirect(next_page)
        return redirect(url_for('main.home'))

    user = get_current_user()
    if user:
        return redirect(url_for('main.home'))
    return render_template('login.html')


@main_bp.route('/logout')
def logout():
    username = session.get('username', 'unknown')
    session.clear()
    log('Logout', '用户登出', username=username, ip=request.remote_addr)
    return redirect(url_for('main.home'))


# ---------------------------------------------------------------------------
# 找回密码
# ---------------------------------------------------------------------------

@main_bp.route('/forgot-password', methods=['GET', 'POST'], endpoint='forgot_password')
def forgot_password_view():
    if request.method == 'POST':
        success, message = forgot_password(
            username=request.form.get('username', '').strip(),
            email=normalize_email(request.form.get('email', '')),
            captcha_input=request.form.get('captcha', '').strip(),
            captcha_id=request.form.get('captcha_id', '').strip(),
            email_code=request.form.get('email_code', '').strip(),
            new_password=request.form.get('new_password', ''),
            confirm_password=request.form.get('confirm_password', ''),
            ip_address=request.remote_addr,
        )
        if not success:
            return render_template('forgot_password.html', error=message)
        return redirect(url_for('main.login', reset=1))

    return render_template('forgot_password.html')


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------

@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = get_current_user()
    return render_template('settings.html', user=user)


@main_bp.route('/settings/username', methods=['POST'])
@login_required
def change_username_view():
    user = get_current_user()
    success, message = change_username(
        user_id=user['id'],
        current_username=user['username'],
        new_username=request.form.get('new_username', '').strip(),
        current_password=request.form.get('current_password', ''),
        ip_address=request.remote_addr,
    )
    if success:
        session['username'] = request.form.get('new_username', '').strip()
    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.settings'))

@main_bp.route('/settings/password', methods=['POST'])
@login_required
def change_password_view():
    user = get_current_user()
    success, message = change_password(
        user_id=user['id'],
        username=user['username'],
        current_password=request.form.get('current_password', ''),
        new_password=request.form.get('new_password', ''),
        confirm_password=request.form.get('confirm_password', ''),
        ip_address=request.remote_addr,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.settings'))

@main_bp.route('/settings/email', methods=['POST'])
@login_required
def change_email_view():
    user = get_current_user()
    success, message = change_email(
        user_id=user['id'],
        username=user['username'],
        new_email=normalize_email(request.form.get('new_email', '')),
        email_code=request.form.get('email_code', '').strip(),
        current_password=request.form.get('current_password', ''),
        ip_address=request.remote_addr,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.settings'))


@main_bp.route('/settings/delete', methods=['POST'])
@login_required
def delete_account_view():
    user = get_current_user()
    success, message = delete_account(
        user_id=user['id'],
        username=user['username'],
        confirm_username=request.form.get('confirm_username', '').strip(),
        ip_address=request.remote_addr,
    )
    if success:
        session.clear()
        flash(message, 'success')
        return redirect(url_for('main.home'))
    flash(message, 'error')
    return redirect(url_for('main.settings'))


# ---------------------------------------------------------------------------
# 性能监控
# ---------------------------------------------------------------------------

@main_bp.route('/performance')
def performance_page():
    user = get_current_user()
    return render_template('performance.html', user=user)