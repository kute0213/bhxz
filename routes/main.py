import json
import os
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from core.auth import login_required, get_current_user, hash_password, validate_password
from core.db import get_db
from config import REGISTER_VERIFY_CODE, UPLOAD_DIR, get_config_value
from services.captcha import captcha_service
from services.email import normalize_email
from services.ratelimit import register_limiter, login_limiter
from services.logger import log

main_bp = Blueprint('main', __name__)


def _is_safe_redirect_url(target: str) -> bool:
    """检查重定向目标 URL 是否安全，防止开放重定向漏洞。"""
    if not target:
        return False
    # 只允许相对路径的重定向，拒绝绝对 URL（防止 //evil.com 绕过）
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme


def _render_register_error(error: str, **kwargs):
    """渲染注册页面错误。"""
    return render_template('register.html', error=error, **kwargs)


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
        'index.html',
        user=user,
        mod_intros=mod_intros,
        map_url=get_config_value('MAP_URL', 'https://map.bhxz.tw.kg'),
        qq_group_url=get_config_value('QQ_GROUP_URL', ''),
    )


@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    email_verify_enabled = get_config_value('REGISTER_EMAIL_VERIFY', False)
    # 从 session 读取群内验证码验证状态，用于模板初始渲染
    group_code_verified = session.get('group_code_verified', False)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        verify_code = request.form.get('verify_code', '').strip()
        captcha_input = request.form.get('captcha', '').strip()
        captcha_id = request.form.get('captcha_id', '').strip()
        email = normalize_email(request.form.get('email', ''))
        email_code = request.form.get('email_code', '').strip()

        # IP 频率限制：每 IP 每分钟最多 5 次注册请求
        if not register_limiter.check(request.remote_addr or 'unknown'):
            log('Register', '注册请求过于频繁', ip=request.remote_addr, username=username)
            return _render_register_error('注册请求过于频繁，请稍后再试',
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)

        if len(username) < 2 or len(username) > 20:
            log('Register', '用户名长度不符合要求', username=username, ip=request.remote_addr)
            return _render_register_error('用户名长度应为 2-20 个字符',
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)
        pwd_err = validate_password(password)
        if pwd_err:
            log('Register', '密码不符合要求', username=username, ip=request.remote_addr)
            return _render_register_error(pwd_err,
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)
        if password != confirm:
            log('Register', '两次密码不一致', username=username, ip=request.remote_addr)
            return _render_register_error('两次输入的密码不一致',
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)

        # 群内验证码校验（由前端弹窗验证后，随表单提交）
        if verify_code != REGISTER_VERIFY_CODE:
            log('Register', '群内验证码错误', username=username, ip=request.remote_addr)
            return _render_register_error('群内验证码错误，请在QQ群公告中获取正确验证码',
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)

        # 邮箱验证（仅在开启时要求）
        if email_verify_enabled:
            if not email:
                log('Register', '邮箱为空', username=username, ip=request.remote_addr)
                return _render_register_error('请输入邮箱地址',
                                               email_verify_enabled=email_verify_enabled,
                                               group_code_verified=group_code_verified)
            if not email_code:
                log('Register', '邮箱验证码为空', username=username, ip=request.remote_addr)
                return _render_register_error('请输入邮箱验证码',
                                               email_verify_enabled=email_verify_enabled,
                                               group_code_verified=group_code_verified)
            from services.email import email_code_service
            if not email_code_service.verify(email, email_code):
                log('Register', '邮箱验证码错误', username=username, email=email, ip=request.remote_addr)
                return _render_register_error('邮箱验证码错误或已过期',
                                               email_verify_enabled=email_verify_enabled,
                                               group_code_verified=group_code_verified)
        else:
            email = ''

        # 图形验证码校验（在创建用户前最后一步，防止验证码被过早消耗）
        if not captcha_service.verify(captcha_id, captcha_input):
            log('Register', '图形验证码错误', username=username, ip=request.remote_addr)
            return _render_register_error('验证码错误或已过期',
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)

        conn = get_db()
        try:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                log('Register', '用户名已被注册', username=username, ip=request.remote_addr)
                return _render_register_error('该用户名已被注册',
                                               email_verify_enabled=email_verify_enabled,
                                               group_code_verified=group_code_verified)

            password_hash = hash_password(password)
            conn.execute(
                "INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, email, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()

            # 注册成功后消耗验证码，防止重放攻击
            captcha_service.consume(captcha_id)

            # 获取新创建的用户信息并自动登录
            new_user = conn.execute(
                "SELECT id, username, is_admin FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            if new_user:
                session.clear()
                session['user_id'] = new_user['id']
                session['username'] = new_user['username']
                session['is_admin'] = bool(new_user['is_admin'])
                session.permanent = True

            log('Register', '注册成功', username=username, user_id=new_user['id'], email=email, ip=request.remote_addr)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            log('Register', '注册异常', username=username, ip=request.remote_addr)
            return _render_register_error('注册失败，请稍后重试',
                                           email_verify_enabled=email_verify_enabled,
                                           group_code_verified=group_code_verified)
        finally:
            conn.close()

        return redirect(url_for('main.home'))

    return render_template('register.html', email_verify_enabled=email_verify_enabled,
                           group_code_verified=group_code_verified)


@main_bp.route('/api/verify-group-code', methods=['POST'])
def verify_group_code():
    """验证群内验证码（AJAX）。验证通过后存入 session，刷新页面后无需重新验证。"""
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()

    if not code:
        log('VerifyGroupCode', '群内验证码为空', ip=request.remote_addr)
        return jsonify({'success': False, 'message': '请输入验证码'}), 400

    if code != REGISTER_VERIFY_CODE:
        log('VerifyGroupCode', '群内验证码错误', ip=request.remote_addr)
        return jsonify({'success': False, 'message': '验证码错误，请在QQ群公告中获取正确验证码'}), 400

    # 存入 session，刷新页面后无需重新验证
    session['group_code_verified'] = True
    session.permanent = True
    log('VerifyGroupCode', '群内验证码验证成功', ip=request.remote_addr)
    return jsonify({'success': True, 'message': '验证成功'})


@main_bp.route('/api/verify-group-code/check')
def check_group_code():
    """检查群内验证码是否已验证（通过 session 持久化）。"""
    return jsonify({'verified': session.get('group_code_verified', False)})


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        captcha_input = request.form.get('captcha', '').strip()
        captcha_id = request.form.get('captcha_id', '').strip()

        # IP 频率限制：每 IP 每分钟最多 10 次登录尝试
        if not login_limiter.check(request.remote_addr or 'unknown'):
            log('Login', '登录请求过于频繁', ip=request.remote_addr, username=username)
            return render_template('login.html', error='登录请求过于频繁，请稍后再试')

        # 验证码校验（服务端内存存储，一次性删除防止重放）
        if not captcha_service.verify(captcha_id, captcha_input):
            log('Login', '验证码错误', username=username, ip=request.remote_addr)
            return render_template('login.html', error='验证码错误或已过期')

        if not username or not password:
            log('Login', '用户名或密码为空', ip=request.remote_addr)
            return render_template('login.html', error='请输入用户名和密码')

        password_hash = hash_password(password)
        conn = get_db()
        try:
            user = conn.execute(
                "SELECT id, username, is_admin FROM users WHERE username = ? AND password_hash = ?",
                (username, password_hash)
            ).fetchone()
        except Exception:
            user = None
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not user:
            log('Login', '用户名或密码错误', username=username, ip=request.remote_addr)
            return render_template('login.html', error='用户名或密码错误')

        # 清除旧会话数据，防止会话固定攻击
        session.clear()

        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = bool(user['is_admin'])
        session.permanent = True

        log('Login', '登录成功', username=username, user_id=user['id'], ip=request.remote_addr, is_admin=user['is_admin'])

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


@main_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """找回密码页面。"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = normalize_email(request.form.get('email', ''))
        captcha_input = request.form.get('captcha', '').strip()
        captcha_id = request.form.get('captcha_id', '').strip()
        email_code = request.form.get('email_code', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # 图形验证码校验
        if not captcha_service.verify(captcha_id, captcha_input):
            log('ForgotPassword', '图形验证码错误', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='图形验证码错误或已过期')

        if not username:
            log('ForgotPassword', '用户名为空', ip=request.remote_addr)
            return render_template('forgot_password.html', error='请输入用户名')

        if not email:
            log('ForgotPassword', '邮箱为空', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='请输入邮箱地址')

        # 查找用户并验证邮箱匹配
        conn = get_db()
        try:
            user = conn.execute(
                "SELECT id, email FROM users WHERE username = ?",
                (username,)
            ).fetchone()
        finally:
            conn.close()

        if not user:
            log('ForgotPassword', '用户不存在', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='用户不存在')

        if not user['email']:
            log('ForgotPassword', '用户未设置邮箱', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='该用户未设置邮箱，无法找回密码')

        if user['email'] != email:
            log('ForgotPassword', '邮箱不匹配', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='邮箱与用户名不匹配')

        # 邮箱验证码校验
        if not email_code:
            log('ForgotPassword', '邮箱验证码为空', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='请输入邮箱验证码')

        from services.email import email_code_service
        if not email_code_service.verify(email, email_code):
            log('ForgotPassword', '邮箱验证码错误', username=username, email=email, ip=request.remote_addr)
            return render_template('forgot_password.html', error='邮箱验证码错误或已过期')

        # 新密码校验
        pwd_err = validate_password(new_password)
        if pwd_err:
            log('ForgotPassword', '新密码不符合要求', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error=pwd_err)
        if new_password != confirm_password:
            log('ForgotPassword', '两次密码不一致', username=username, ip=request.remote_addr)
            return render_template('forgot_password.html', error='两次输入的新密码不一致')

        # 更新密码
        conn = get_db()
        try:
            new_hash = hash_password(new_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user['id']))
            conn.commit()
            log('ForgotPassword', '密码重置成功', username=username, user_id=user['id'], ip=request.remote_addr)
        except Exception:
            conn.rollback()
            log('ForgotPassword', '密码重置失败', username=username, user_id=user['id'], ip=request.remote_addr)
            return render_template('forgot_password.html', error='密码重置失败，请稍后重试')
        finally:
            conn.close()

        return redirect(url_for('main.login', reset=1))

    return render_template('forgot_password.html')


@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = get_current_user()
    return render_template('settings.html', user=user)


@main_bp.route('/settings/username', methods=['POST'])
@login_required
def change_username():
    user = get_current_user()
    new_username = request.form.get('new_username', '').strip()
    current_password = request.form.get('current_password', '')

    if len(new_username) < 2 or len(new_username) > 20:
        flash('用户名长度应为 2-20 个字符', 'error')
        return redirect(url_for('main.settings') + '#username')

    if not current_password:
        flash('请输入当前密码', 'error')
        return redirect(url_for('main.settings') + '#username')

    password_hash = hash_password(current_password)
    conn = get_db()
    try:
        db_user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user['id'],)).fetchone()
        if not db_user or db_user['password_hash'] != password_hash:
            flash('当前密码错误', 'error')
            return redirect(url_for('main.settings') + '#username')

        existing = conn.execute("SELECT id FROM users WHERE username = ?", (new_username,)).fetchone()
        if existing and existing['id'] != user['id']:
            flash('该用户名已被使用', 'error')
            return redirect(url_for('main.settings') + '#username')

        conn.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user['id']))
        conn.commit()

        # 同步更新所有依赖 username 的数据 (避免因 UNIQUE 冲突)
        conn.execute("UPDATE access_logs SET username = ? WHERE user_id = ?", (new_username, user['id']))
        conn.commit()

        session['username'] = new_username
        log('ChangeUsername', '用户名修改成功', user_id=user['id'], old_username=user['username'], new_username=new_username, ip=request.remote_addr)
        flash('用户名修改成功！', 'success')
    except Exception:
        conn.rollback()
        log('ChangeUsername', '用户名修改失败', user_id=user['id'], username=user['username'], ip=request.remote_addr)
        flash('修改失败，请重试', 'error')
    finally:
        conn.close()

    return redirect(url_for('main.settings'))


@main_bp.route('/settings/password', methods=['POST'])
@login_required
def change_password():
    user = get_current_user()
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not current_password:
        flash('请输入当前密码', 'error')
        return redirect(url_for('main.settings') + '#password')
    pwd_err = validate_password(new_password)
    if pwd_err:
        flash(pwd_err, 'error')
        return redirect(url_for('main.settings') + '#password')
    if new_password != confirm_password:
        flash('两次输入的新密码不一致', 'error')
        return redirect(url_for('main.settings') + '#password')

    password_hash = hash_password(current_password)
    conn = get_db()
    try:
        db_user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user['id'],)).fetchone()
        if not db_user or db_user['password_hash'] != password_hash:
            flash('当前密码错误', 'error')
            return redirect(url_for('main.settings') + '#password')

        new_hash = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user['id']))
        conn.commit()
        log('ChangePassword', '密码修改成功', user_id=user['id'], username=user['username'], ip=request.remote_addr)
        flash('密码修改成功！', 'success')
    except Exception:
        conn.rollback()
        log('ChangePassword', '密码修改失败', user_id=user['id'], username=user['username'], ip=request.remote_addr)
        flash('修改失败，请重试', 'error')
    finally:
        conn.close()

    return redirect(url_for('main.settings'))


@main_bp.route('/settings/email', methods=['POST'])
@login_required
def change_email():
    user = get_current_user()
    new_email = normalize_email(request.form.get('new_email', ''))
    email_code = request.form.get('email_code', '').strip()
    current_password = request.form.get('current_password', '')

    if not current_password:
        flash('请输入当前密码', 'error')
        return redirect(url_for('main.settings') + '#email')

    # 验证当前密码
    password_hash = hash_password(current_password)
    conn = get_db()
    try:
        db_user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user['id'],)).fetchone()
        if not db_user or db_user['password_hash'] != password_hash:
            flash('当前密码错误', 'error')
            return redirect(url_for('main.settings') + '#email')

        if not new_email:
            flash('请输入新邮箱地址', 'error')
            return redirect(url_for('main.settings') + '#email')

        # 邮箱验证码校验（仅在邮件功能且邮箱验证开启时）
        if get_config_value('EMAIL_ENABLED', False) and get_config_value('REGISTER_EMAIL_VERIFY', False):
            if not email_code:
                flash('请输入邮箱验证码', 'error')
                return redirect(url_for('main.settings') + '#email')
            from services.email import email_code_service
            if not email_code_service.verify(new_email, email_code):
                flash('邮箱验证码错误或已过期', 'error')
                return redirect(url_for('main.settings') + '#email')

        conn.execute("UPDATE users SET email = ? WHERE id = ?", (new_email, user['id']))
        conn.commit()
        log('ChangeEmail', '邮箱修改成功', user_id=user['id'], username=user['username'], new_email=new_email, ip=request.remote_addr)
        flash('邮箱修改成功！', 'success')
    except Exception:
        conn.rollback()
        log('ChangeEmail', '邮箱修改失败', user_id=user['id'], username=user['username'], ip=request.remote_addr)
        flash('修改失败，请重试', 'error')
    finally:
        conn.close()

    return redirect(url_for('main.settings'))


@main_bp.route('/settings/delete', methods=['POST'])
@login_required
def delete_account():
    user = get_current_user()
    confirm_username = request.form.get('confirm_username', '').strip()

    if confirm_username != user['username']:
        flash('用户名确认不匹配', 'error')
        return redirect(url_for('main.settings') + '#delete')

    conn = get_db()
    try:
        # 级联删除前清理用户回复中的附件文件
        replies = conn.execute("SELECT attachment FROM board_replies WHERE user_id = ?", (user['id'],)).fetchall()
        for r in replies:
            if r['attachment']:
                try:
                    parsed = json.loads(r['attachment'])
                    filenames = [parsed] if isinstance(parsed, str) else parsed
                except (json.JSONDecodeError, TypeError):
                    filenames = [r['attachment']]
                for fname in filenames:
                    filepath = os.path.join(UPLOAD_DIR, fname)
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass

        # 手动级联删除（DuckDB 不支持 ON DELETE CASCADE）
        conn.execute("DELETE FROM poll_votes WHERE user_id = ?", (user['id'],))
        # 删除用户创建的留言板主题（连带回复）
        topic_rows = conn.execute(
            "SELECT id FROM board_topics WHERE user_id = ?", (user['id'],)
        ).fetchall()
        for tr in topic_rows:
            tid = tr['id']
            # 清理主题下回复的附件
            reply_rows = conn.execute(
                "SELECT attachment FROM board_replies WHERE topic_id = ?", (tid,)
            ).fetchall()
            for rr in reply_rows:
                if rr['attachment']:
                    try:
                        parsed = json.loads(rr['attachment'])
                        fnames = [parsed] if isinstance(parsed, str) else parsed
                    except (json.JSONDecodeError, TypeError):
                        fnames = [rr['attachment']]
                    for fn in fnames:
                        fp = os.path.join(UPLOAD_DIR, fn)
                        if os.path.exists(fp):
                            try:
                                os.remove(fp)
                            except OSError:
                                pass
            conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM board_topics WHERE user_id = ?", (user['id'],))
        conn.execute("DELETE FROM board_replies WHERE user_id = ?", (user['id'],))
        conn.execute("DELETE FROM users WHERE id = ?", (user['id'],))
        conn.commit()
        log('DeleteAccount', '账号注销成功', user_id=user['id'], username=user['username'], ip=request.remote_addr)
    except Exception:
        conn.rollback()
        log('DeleteAccount', '账号注销失败', user_id=user['id'], username=user['username'], ip=request.remote_addr)
        flash('注销失败，请重试', 'error')
        return redirect(url_for('main.settings') + '#delete')
    finally:
        conn.close()

    session.clear()
    flash('账号已注销', 'success')
    return redirect(url_for('main.home'))


@main_bp.route('/performance')
def performance_page():
    """服务器性能监控页面（公开访问）。"""
    user = get_current_user()
    return render_template('performance.html', user=user)
