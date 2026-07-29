import json
import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort
from core.auth import login_required, get_current_user, hash_password
from core.db import get_db
from config import REGISTER_VERIFY_CODE, UPLOAD_DIR, get_config_value
from services.captcha import captcha_service
from services.email_code import normalize_email

main_bp = Blueprint('main', __name__)


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
        mod_intros=mod_intros
    )


@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    email_verify_enabled = get_config_value('REGISTER_EMAIL_VERIFY', False)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        verify_code = request.form.get('verify_code', '').strip()
        captcha_input = request.form.get('captcha', '').strip()
        captcha_id = request.form.get('captcha_id', '').strip()
        email = normalize_email(request.form.get('email', ''))
        email_code = request.form.get('email_code', '').strip()

        # 验证码校验（服务端内存存储，一次性删除防止重放）
        if not captcha_service.verify(captcha_id, captcha_input):
            return render_template('register.html', error='验证码错误或已过期',
                                   email_verify_enabled=email_verify_enabled)

        if len(username) < 2 or len(username) > 20:
            return render_template('register.html', error='用户名长度应为 2-20 个字符',
                                   email_verify_enabled=email_verify_enabled)
        if len(password) < 6:
            return render_template('register.html', error='密码至少 6 位',
                                   email_verify_enabled=email_verify_enabled)
        if password != confirm:
            return render_template('register.html', error='两次输入的密码不一致',
                                   email_verify_enabled=email_verify_enabled)
        if verify_code != REGISTER_VERIFY_CODE:
            return render_template('register.html', error='群内验证码错误，请在QQ群公告中获取正确验证码',
                                   email_verify_enabled=email_verify_enabled)

        # 邮箱验证（仅在开启时要求）
        if email_verify_enabled:
            if not email:
                return render_template('register.html', error='请输入邮箱地址',
                                       email_verify_enabled=email_verify_enabled)
            if not email_code:
                return render_template('register.html', error='请输入邮箱验证码',
                                       email_verify_enabled=email_verify_enabled)
            from services.email_code import email_code_service
            if not email_code_service.verify(email, email_code):
                return render_template('register.html', error='邮箱验证码错误或已过期',
                                       email_verify_enabled=email_verify_enabled)
        else:
            email = ''

        conn = get_db()
        try:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                return render_template('register.html', error='该用户名已被注册',
                                       email_verify_enabled=email_verify_enabled)

            password_hash = hash_password(password)
            conn.execute(
                "INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, email, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return render_template('register.html', error='注册失败，请稍后重试',
                                   email_verify_enabled=email_verify_enabled)
        finally:
            conn.close()
        return redirect(url_for('main.login', registered=1))

    return render_template('register.html', email_verify_enabled=email_verify_enabled)


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        captcha_input = request.form.get('captcha', '').strip()
        captcha_id = request.form.get('captcha_id', '').strip()

        # 验证码校验（服务端内存存储，一次性删除防止重放）
        if not captcha_service.verify(captcha_id, captcha_input):
            return render_template('login.html', error='验证码错误或已过期')

        if not username or not password:
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
            return render_template('login.html', error='用户名或密码错误')

        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = bool(user['is_admin'])
        session.permanent = True

        next_page = request.args.get('next') or request.form.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        return redirect(url_for('main.home'))

    user = get_current_user()
    if user:
        return redirect(url_for('main.home'))
    return render_template('login.html')


@main_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.home'))


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
        flash('用户名修改成功！', 'success')
    except Exception:
        conn.rollback()
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
    if len(new_password) < 6:
        flash('新密码至少 6 位', 'error')
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
        flash('密码修改成功！', 'success')
    except Exception:
        conn.rollback()
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
            from services.email_code import email_code_service
            if not email_code_service.verify(new_email, email_code):
                flash('邮箱验证码错误或已过期', 'error')
                return redirect(url_for('main.settings') + '#email')

        conn.execute("UPDATE users SET email = ? WHERE id = ?", (new_email, user['id']))
        conn.commit()
        flash('邮箱修改成功！', 'success')
    except Exception:
        conn.rollback()
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
    except Exception:
        conn.rollback()
        flash('注销失败，请重试', 'error')
        return redirect(url_for('main.settings') + '#delete')
    finally:
        conn.close()

    session.clear()
    flash('账号已注销', 'success')
    return redirect(url_for('main.home'))


@main_bp.route('/performance')
def performance_page():
    """服务器性能监控页面（仅管理员可访问）。"""
    user = get_current_user()
    # 鉴权：未登录跳转登录页，非管理员 403
    if not user:
        return redirect(url_for('main.login', next=request.path))
    if not user.get('is_admin'):
        abort(403)
    return render_template('performance.html', user=user)
