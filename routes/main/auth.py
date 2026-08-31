"""认证路由：登录、注册、找回密码、退出、群码验证。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from urllib.parse import urlparse

from flask import render_template, request, redirect, url_for, session, flash, jsonify
from core.auth import get_current_user
from config import get_config_value, REGISTER_VERIFY_CODE
from services.email import normalize_email
from services.user_service import (
    register, login, forgot_password, check_username_available,
)
from core.logger import log
from routes.main import main_bp


def _is_safe_redirect_url(target: str) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

@main_bp.route('/register', methods=['GET', 'POST'], endpoint='register')
def register_view():
    email_verify_enabled = get_config_value('REGISTER_EMAIL_VERIFY', False)
    group_code_verified = session.get('group_code_verified', False)
    show_back_to_login = request.args.get('source') == 'login'

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
            group_code_verified=group_code_verified,
        )
        if not success:
            return render_template(
                'register.html', error=result,
                email_verify_enabled=email_verify_enabled,
                group_code_verified=group_code_verified,
                show_back_to_login=show_back_to_login,
                submitted_username=request.form.get('username', '').strip(),
                submitted_email=normalize_email(request.form.get('email', '')),
            )
        # 自动登录
        session.clear()
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        session['is_admin'] = result['is_admin']
        session['login_welcome_username'] = result['username']
        session.permanent = True
        return redirect(url_for('main.home'))

    return render_template(
        'register.html',
        email_verify_enabled=email_verify_enabled,
        group_code_verified=group_code_verified,
        show_back_to_login=show_back_to_login,
    )


@main_bp.route('/api/username/check')
def check_username():
    """供注册页实时查询用户名是否可用，最终仍以注册写入校验为准。"""
    available, message = check_username_available(request.args.get('username', ''))
    return jsonify({'available': available, 'message': message})


@main_bp.route('/api/verify-group-code', methods=['POST'])
def verify_group_code():
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
            return render_template(
                'login.html', error=result,
                submitted_username=request.form.get('username', '').strip(),
                submitted_next=request.form.get('next', ''),
            )

        session.clear()
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        session['is_admin'] = result['is_admin']
        session['login_welcome_username'] = result['username']
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
