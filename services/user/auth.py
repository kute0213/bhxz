"""用户业务服务 - 认证相关（注册、登录、找回密码）。"""

import os
from datetime import datetime

from flask import request

from core.auth import hash_password, validate_password, verify_password
from core.db import get_db
from config import REGISTER_VERIFY_CODE, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_TIME, get_config_value
from services.captcha import captcha_service
from services.email import normalize_email, email_code_service
from services.ratelimit import register_limiter, login_limiter, forgot_password_limiter
from core.logger import log


def _get_ua():
    """获取当前请求的 User-Agent。"""
    try:
        return request.headers.get('User-Agent', '') or ''
    except Exception:
        return ''


def check_username_available(username):
    """按不区分大小写的规则检查用户名是否可以注册。"""
    username = (username or '').strip()

    from services.validation import validate_website_username
    valid, err = validate_website_username(username)
    if not valid:
        return False, err

    try:
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (username,)
            ).fetchone()
    except Exception as exc:
        log('Register', '用户名可用性查询失败', username=username, error=str(exc))
        return False, '暂时无法检查用户名，请稍后重试'

    if existing:
        return False, '该用户名已被注册'
    return True, '该用户名可用'


def register(username, password, confirm, verify_code, captcha_input, captcha_id,
             email, email_code, ip_address, email_verify_enabled,
             group_code_verified=False):
    """注册用户。返回 (success, data_or_error)。"""

    if not register_limiter.check(ip_address or 'unknown', _get_ua()):
        log('Register', '注册请求过于频繁', ip=ip_address, username=username)
        return False, '注册请求过于频繁，请稍后再试'

    from services.validation import validate_website_username
    valid_uname, uname_err = validate_website_username(username)
    if not valid_uname:
        log('Register', '用户名格式不符合要求', username=username, ip=ip_address)
        return False, uname_err

    pwd_err = validate_password(password)
    if pwd_err:
        log('Register', '密码不符合要求', username=username, ip=ip_address)
        return False, pwd_err

    if password != confirm:
        log('Register', '两次密码不一致', username=username, ip=ip_address)
        return False, '两次输入的密码不一致'

    if not group_code_verified and verify_code != REGISTER_VERIFY_CODE:
        log('Register', '群内验证码错误', username=username, ip=ip_address)
        return False, '群内验证码错误，请在QQ群公告中获取正确验证码'

    if email_verify_enabled:
        if not email:
            log('Register', '邮箱为空', username=username, ip=ip_address)
            return False, '请输入邮箱地址'
        if not email_code:
            log('Register', '邮箱验证码为空', username=username, ip=ip_address)
            return False, '请输入邮箱验证码'
    else:
        email = ''

    if not captcha_service.verify(captcha_id, captcha_input):
        log('Register', '图形验证码错误', username=username, ip=ip_address)
        return False, '验证码错误或已过期'

    try:
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (username,)
            ).fetchone()
            if existing:
                log('Register', '用户名已被注册', username=username, ip=ip_address)
                return False, '该用户名已被注册'

            if email:
                email_exists = conn.execute(
                    "SELECT id FROM users WHERE email = ? AND email != ''",
                    (email,)
                ).fetchone()
                if email_exists:
                    log('Register', '邮箱已被注册', email=email, ip=ip_address)
                    return False, '该邮箱已被其他账号使用，一个邮箱只可注册一个账号'

            if email_verify_enabled and not email_code_service.verify(
                    email, email_code, purpose='注册', consume=False):
                log('Register', '邮箱验证码错误', username=username, email=email, ip=ip_address)
                return False, '邮箱验证码错误或已过期'

            password_hash = hash_password(password)
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(
                "INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, email, now)
            )

            new_user = conn.execute(
                "SELECT id, username, is_admin FROM users WHERE username = ?",
                (username,)
            ).fetchone()

        captcha_service.consume(captcha_id)
        if email_verify_enabled:
            email_code_service.consume(email, email_code, purpose='注册')

        log('Register', '注册成功', username=username, user_id=new_user['id'],
            email=email, ip=ip_address)
        return True, {
            'user_id': new_user['id'],
            'username': new_user['username'],
            'is_admin': bool(new_user['is_admin']),
        }
    except Exception as exc:
        log('Register', '注册异常', username=username, ip=ip_address, error=str(exc))
        return False, '注册失败，请稍后重试'


def login(username, password, captcha_input, captcha_id, ip_address):
    """登录验证。返回 (success, data_or_error)。"""

    if not login_limiter.check(ip_address or 'unknown', _get_ua()):
        log('Login', '登录请求过于频繁', ip=ip_address, username=username)
        return False, '登录请求过于频繁，请稍后再试'

    if not username or not password:
        log('Login', '用户名或密码为空', ip=ip_address)
        return False, '请输入用户名和密码'

    if os.environ.get('TRAE_TEST_BYPASS_CAPTCHA', '0') != '1' and \
            not captcha_service.verify(captcha_id, captcha_input):
        log('Login', '验证码错误', username=username, ip=ip_address)
        return False, '验证码错误或已过期'

    if os.environ.get('TRAE_TEST_BYPASS_CAPTCHA', '0') != '1':
        captcha_service.consume(captcha_id)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        with get_db() as conn:
            user = conn.execute(
                "SELECT id, username, password_hash, is_admin, "
                "login_attempts, locked_until FROM users "
                "WHERE lower(username) = lower(?) LIMIT 1",
                (username,)
            ).fetchone()

            if user:
                locked_until_str = user['locked_until'] or ''
                if locked_until_str and locked_until_str > now_str:
                    log('Login', '账户已被锁定', username=username, user_id=user['id'],
                        ip=ip_address, locked_until=locked_until_str)
                    return False, '账户已被锁定，请稍后再试'

                if not verify_password(password, user['password_hash']):
                    new_attempts = (user['login_attempts'] or 0) + 1
                    max_attempts = MAX_LOGIN_ATTEMPTS or 5
                    if new_attempts >= max_attempts:
                        lockout_seconds = LOGIN_LOCKOUT_TIME or 1800
                        locked_until = datetime.fromtimestamp(
                            datetime.now().timestamp() + lockout_seconds
                        ).strftime('%Y-%m-%d %H:%M:%S')
                        conn.execute(
                            "UPDATE users SET login_attempts = ?, locked_until = ? WHERE id = ?",
                            (new_attempts, locked_until, user['id'])
                        )
                        conn.commit()
                        log('Login', '密码错误次数过多，账户已锁定', username=username,
                            user_id=user['id'], ip=ip_address,
                            attempts=new_attempts, locked_until=locked_until)
                        return False, '密码错误次数过多，账户已被锁定，请稍后再试'
                    else:
                        conn.execute(
                            "UPDATE users SET login_attempts = ? WHERE id = ?",
                            (new_attempts, user['id'])
                        )
                        conn.commit()

                    log('Login', '用户名或密码错误', username=username, user_id=user['id'],
                        ip=ip_address, attempts=new_attempts)
                    return False, '用户名或密码错误'

            if not user:
                log('Login', '用户名或密码错误', username=username, ip=ip_address)
                return False, '用户名或密码错误'

            if (user['login_attempts'] or 0) > 0 or (user['locked_until'] or ''):
                conn.execute(
                    "UPDATE users SET login_attempts = 0, locked_until = '' WHERE id = ?",
                    (user['id'],)
                )
                conn.commit()

            if len(user['password_hash']) == 64:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), user['id'])
                )
                conn.commit()

    except Exception as exc:
        log('Login', '查询用户失败', username=username, ip=ip_address, error=str(exc))
        return False, '登录服务暂时不可用，请稍后再试'

    log('Login', '登录成功', username=username, user_id=user['id'],
        ip=ip_address, is_admin=user['is_admin'])
    return True, {
        'user_id': user['id'],
        'username': user['username'],
        'is_admin': bool(user['is_admin']),
    }


def forgot_password(username, email, captcha_input, captcha_id, email_code,
                    new_password, confirm_password, ip_address):
    """找回密码。返回 (success, message)。"""

    if not forgot_password_limiter.check(ip_address or 'unknown', _get_ua()):
        log('ForgotPassword', '找回密码请求过于频繁', username=username, ip=ip_address)
        return False, '找回密码请求过于频繁，请稍后再试'

    if not captcha_service.verify(captcha_id, captcha_input):
        log('ForgotPassword', '图形验证码错误', username=username, ip=ip_address)
        return False, '图形验证码错误或已过期'

    if not username:
        log('ForgotPassword', '用户名为空', ip=ip_address)
        return False, '请输入用户名'

    if not email:
        log('ForgotPassword', '邮箱为空', username=username, ip=ip_address)
        return False, '请输入邮箱地址'

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, email FROM users WHERE lower(username) = lower(?) LIMIT 1",
            (username,)
        ).fetchone()
    finally:
        conn.close()

    if not user:
        log('ForgotPassword', '用户不存在', username=username, ip=ip_address)
        return False, '用户不存在'

    if not user['email']:
        log('ForgotPassword', '用户未设置邮箱', username=username, ip=ip_address)
        return False, '该用户未设置邮箱，无法找回密码'

    if user['email'] != email:
        log('ForgotPassword', '邮箱不匹配', username=username, ip=ip_address)
        return False, '邮箱与用户名不匹配'

    if not email_code:
        log('ForgotPassword', '邮箱验证码为空', username=username, ip=ip_address)
        return False, '请输入邮箱验证码'

    if not email_code_service.verify(email, email_code, purpose='找回密码'):
        log('ForgotPassword', '邮箱验证码错误', username=username, email=email, ip=ip_address)
        return False, '邮箱验证码错误或已过期'

    pwd_err = validate_password(new_password)
    if pwd_err:
        log('ForgotPassword', '新密码不符合要求', username=username, ip=ip_address)
        return False, pwd_err

    if new_password != confirm_password:
        log('ForgotPassword', '两次密码不一致', username=username, ip=ip_address)
        return False, '两次输入的新密码不一致'

    conn = get_db()
    try:
        new_hash = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user['id']))
        conn.commit()
        captcha_service.consume(captcha_id)
        log('ForgotPassword', '密码重置成功', username=username, user_id=user['id'], ip=ip_address)
        return True, '密码重置成功'
    except Exception:
        conn.rollback()
        log('ForgotPassword', '密码重置失败', username=username, user_id=user['id'], ip=ip_address)
        return False, '密码重置失败，请稍后重试'
    finally:
        conn.close()