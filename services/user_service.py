"""用户业务服务：注册、登录、改密、改邮箱、改用户名、注销、找回密码、管理员操作。

所有函数均为 Flask 无关的纯业务逻辑，接收必要参数，返回 (success, data_or_error) 元组。
"""

import json
import os
from datetime import datetime

from core.auth import hash_password, validate_password, verify_password
from core.db import get_db
from config import REGISTER_VERIFY_CODE, UPLOAD_DIR, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_TIME, get_config_value
from services.captcha import captcha_service
from services.email import normalize_email, email_code_service
from services.ratelimit import register_limiter, login_limiter
from core.logger import log
from services.attachment_service import clean_attachment_json



# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _clean_user_attachments(conn, user_id):
    """清理用户相关的所有附件（board_replies 中的附件）。"""
    replies = conn.execute(
        "SELECT attachment FROM board_replies WHERE user_id = ?", (user_id,)
    ).fetchall()
    for r in replies:
        if r['attachment']:
            clean_attachment_json(r['attachment'])

    # 清理用户创建的主题下的回复附件
    topic_rows = conn.execute(
        "SELECT id FROM board_topics WHERE user_id = ?", (user_id,)
    ).fetchall()
    for tr in topic_rows:
        tid = tr['id']
        reply_rows = conn.execute(
            "SELECT attachment FROM board_replies WHERE topic_id = ?", (tid,)
        ).fetchall()
        for rr in reply_rows:
            if rr['attachment']:
                clean_attachment_json(rr['attachment'])


def _get_user_media_keys(conn, user_id):
    """读取账号关联的图片文件路径，供数据库提交后清理。"""
    row = conn.execute(
        "SELECT avatar_key FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return []
    return [row['avatar_key']] if row['avatar_key'] else []


def _clean_user_media(keys, user_id):
    """账号删除成功后清理本地图片文件；异常不回滚已完成的账号注销。"""
    import os
    for filepath in keys:
        try:
            if filepath and os.path.isfile(filepath):
                os.remove(filepath)
        except Exception as exc:
            log('UserMedia', '账号图片清理失败', user_id=user_id,
                filepath=filepath, error=str(exc))


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def check_username_available(username):
    """按不区分大小写的规则检查用户名是否可以注册。"""
    username = (username or '').strip()
    if len(username) < 2 or len(username) > 20:
        return False, '用户名长度应为 2-20 个字符'

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

    # IP 频率限制
    if not register_limiter.check(ip_address or 'unknown'):
        log('Register', '注册请求过于频繁', ip=ip_address, username=username)
        return False, '注册请求过于频繁，请稍后再试'

    # 验证输入
    if len(username) < 2 or len(username) > 20:
        log('Register', '用户名长度不符合要求', username=username, ip=ip_address)
        return False, '用户名长度应为 2-20 个字符'

    pwd_err = validate_password(password)
    if pwd_err:
        log('Register', '密码不符合要求', username=username, ip=ip_address)
        return False, pwd_err

    if password != confirm:
        log('Register', '两次密码不一致', username=username, ip=ip_address)
        return False, '两次输入的密码不一致'

    # Web 端以服务端 session 中的验证结果为准；保留 verify_code 兼容服务层调用。
    if not group_code_verified and verify_code != REGISTER_VERIFY_CODE:
        log('Register', '群内验证码错误', username=username, ip=ip_address)
        return False, '群内验证码错误，请在QQ群公告中获取正确验证码'

    # 邮箱验证（仅在开启时要求）。这里只检查输入，验证码在数据库校验后验证，
    # 避免用户名或邮箱已存在时提前消费验证码。
    if email_verify_enabled:
        if not email:
            log('Register', '邮箱为空', username=username, ip=ip_address)
            return False, '请输入邮箱地址'
        if not email_code:
            log('Register', '邮箱验证码为空', username=username, ip=ip_address)
            return False, '请输入邮箱验证码'
    else:
        email = ''

    # 图形验证码校验
    if not captcha_service.verify(captcha_id, captcha_input):
        log('Register', '图形验证码错误', username=username, ip=ip_address)
        return False, '验证码错误或已过期'

    try:
        # 注册检查与写入必须持有同一数据库锁，避免并发请求交叉使用共享游标。
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

            # 在释放数据库锁前读取本次插入结果，避免共享游标被其他线程覆盖。
            new_user = conn.execute(
                "SELECT id, username, is_admin FROM users WHERE username = ?",
                (username,)
            ).fetchone()

        # 数据库事务成功后才消费验证码，失败时用户可直接重试。
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


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

def login(username, password, captcha_input, captcha_id, ip_address):
    """登录验证。返回 (success, data_or_error)。"""

    if not login_limiter.check(ip_address or 'unknown'):
        log('Login', '登录请求过于频繁', ip=ip_address, username=username)
        return False, '登录请求过于频繁，请稍后再试'

    if not username or not password:
        log('Login', '用户名或密码为空', ip=ip_address)
        return False, '请输入用户名和密码'

    # 测试/自动化环境：设置 TRAE_TEST_BYPASS_CAPTCHA=1 时跳过图形验证码，
    # 便于 E2E 冒烟测试。切勿在生产环境开启此环境变量。
    if os.environ.get('TRAE_TEST_BYPASS_CAPTCHA', '0') != '1' and \
            not captcha_service.verify(captcha_id, captcha_input):
        log('Login', '验证码错误', username=username, ip=ip_address)
        return False, '验证码错误或已过期'

    # 一次图形验证码只允许发起一次登录尝试，防止重复用于密码枚举。
    if os.environ.get('TRAE_TEST_BYPASS_CAPTCHA', '0') != '1':
        captcha_service.consume(captcha_id)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        # 共享 DuckDB 游标的 execute/fetch 必须处于同一锁区间。
        with get_db() as conn:
            user = conn.execute(
                "SELECT id, username, password_hash, is_admin, "
                "login_attempts, locked_until FROM users "
                "WHERE lower(username) = lower(?) LIMIT 1",
                (username,)
            ).fetchone()

            if user:
                # ---- 账户锁定检查 ----
                locked_until_str = user['locked_until'] or ''
                if locked_until_str and locked_until_str > now_str:
                    log('Login', '账户已被锁定', username=username, user_id=user['id'],
                        ip=ip_address, locked_until=locked_until_str)
                    return False, '账户已被锁定，请稍后再试'

                # ---- 密码校验 ----
                if not verify_password(password, user['password_hash']):
                    # 失败：递增 login_attempts，达到阈值时锁定
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

            # 无此用户
            if not user:
                log('Login', '用户名或密码错误', username=username, ip=ip_address)
                return False, '用户名或密码错误'

            # ---- 登录成功：重置锁定计数 ----
            if (user['login_attempts'] or 0) > 0 or (user['locked_until'] or ''):
                conn.execute(
                    "UPDATE users SET login_attempts = 0, locked_until = '' WHERE id = ?",
                    (user['id'],)
                )
                conn.commit()

            # 历史 SHA-256 密码在首次成功登录时透明升级，不影响旧账号使用。
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


# ---------------------------------------------------------------------------
# 找回密码
# ---------------------------------------------------------------------------

def forgot_password(username, email, captcha_input, captcha_id, email_code,
                    new_password, confirm_password, ip_address):
    """找回密码。返回 (success, message)。"""

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


# ---------------------------------------------------------------------------
# 修改用户名
# ---------------------------------------------------------------------------

def change_username(user_id, current_username, new_username, current_password, ip_address):
    """修改用户名。返回 (success, message)。"""

    if len(new_username) < 2 or len(new_username) > 20:
        return False, '用户名长度应为 2-20 个字符'

    if not current_password:
        return False, '请输入当前密码'

    conn = get_db()
    try:
        db_user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not db_user or not verify_password(current_password, db_user['password_hash']):
            return False, '当前密码错误'

        existing = conn.execute(
            "SELECT id FROM users WHERE lower(username) = lower(?) LIMIT 1",
            (new_username,)
        ).fetchone()
        if existing and existing['id'] != user_id:
            return False, '该用户名已被使用'

        conn.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user_id))
        conn.execute("UPDATE access_logs SET username = ? WHERE user_id = ?", (new_username, user_id))
        conn.commit()
        log('ChangeUsername', '用户名修改成功', user_id=user_id,
            old_username=current_username, new_username=new_username, ip=ip_address)
        return True, '用户名修改成功！'
    except Exception:
        conn.rollback()
        log('ChangeUsername', '用户名修改失败', user_id=user_id, username=current_username, ip=ip_address)
        return False, '修改失败，请重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 修改密码
# ---------------------------------------------------------------------------

def change_password(user_id, username, current_password, new_password, confirm_password, ip_address):
    """修改密码。返回 (success, message)。"""

    if not current_password:
        return False, '请输入当前密码'

    pwd_err = validate_password(new_password)
    if pwd_err:
        return False, pwd_err

    if new_password != confirm_password:
        return False, '两次输入的新密码不一致'

    conn = get_db()
    try:
        db_user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not db_user or not verify_password(current_password, db_user['password_hash']):
            return False, '当前密码错误'

        new_hash = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        conn.commit()
        log('ChangePassword', '密码修改成功', user_id=user_id, username=username, ip=ip_address)
        return True, '密码修改成功！'
    except Exception:
        conn.rollback()
        log('ChangePassword', '密码修改失败', user_id=user_id, username=username, ip=ip_address)
        return False, '修改失败，请重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 修改邮箱
# ---------------------------------------------------------------------------

def change_email(user_id, username, new_email, email_code, current_password, ip_address):
    """修改邮箱。返回 (success, message)。"""

    if not current_password:
        return False, '请输入当前密码'

    conn = get_db()
    try:
        db_user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not db_user or not verify_password(current_password, db_user['password_hash']):
            return False, '当前密码错误'

        if not new_email:
            return False, '请输入新邮箱地址'

        # 邮箱验证码校验
        if get_config_value('EMAIL_ENABLED', False) and get_config_value('REGISTER_EMAIL_VERIFY', False):
            if not email_code:
                return False, '请输入邮箱验证码'
            if not email_code_service.verify(new_email, email_code, purpose='修改邮箱'):
                return False, '邮箱验证码错误或已过期'

        # 邮箱唯一性检查
        if new_email:
            email_exists = conn.execute(
                "SELECT id FROM users WHERE email = ? AND email != '' AND id != ?",
                (new_email, user_id)
            ).fetchone()
            if email_exists:
                return False, '该邮箱已被其他账号使用，一个邮箱只可注册一个账号'

        conn.execute("UPDATE users SET email = ? WHERE id = ?", (new_email, user_id))
        conn.commit()
        log('ChangeEmail', '邮箱修改成功', user_id=user_id, username=username,
            new_email=new_email, ip=ip_address)
        return True, '邮箱修改成功！'
    except Exception:
        conn.rollback()
        log('ChangeEmail', '邮箱修改失败', user_id=user_id, username=username, ip=ip_address)
        return False, '修改失败，请重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 注销账号
# ---------------------------------------------------------------------------

def delete_account(user_id, username, confirm_username, ip_address):
    """注销用户，级联清理所有关联数据。返回 (success, message)。"""

    if confirm_username != username:
        return False, '用户名确认不匹配'

    conn = get_db()
    try:
        media_keys = _get_user_media_keys(conn, user_id)
        # 清理附件
        _clean_user_attachments(conn, user_id)

        # 手动级联删除
        conn.execute("DELETE FROM poll_votes WHERE user_id = ?", (user_id,))
        topic_rows = conn.execute(
            "SELECT id FROM board_topics WHERE user_id = ?", (user_id,)
        ).fetchall()
        for tr in topic_rows:
            tid = tr['id']
            reply_rows = conn.execute(
                "SELECT attachment FROM board_replies WHERE topic_id = ?", (tid,)
            ).fetchall()
            for rr in reply_rows:
                if rr['attachment']:
                    clean_attachment_json(rr['attachment'])
            conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM board_topics WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM board_replies WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        _clean_user_media(media_keys, user_id)
        log('DeleteAccount', '账号注销成功', user_id=user_id, username=username, ip=ip_address)
        return True, '账号已注销'
    except Exception:
        conn.rollback()
        log('DeleteAccount', '账号注销失败', user_id=user_id, username=username, ip=ip_address)
        return False, '注销失败，请重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 管理员：删除用户
# ---------------------------------------------------------------------------

def admin_delete_user(admin_user, target_user_id, ip_address):
    """管理员删除用户，级联清理所有关联数据。返回 (success, message)。"""

    if target_user_id == admin_user['id']:
        return False, '不能删除自己'

    conn = get_db()
    try:
        media_keys = _get_user_media_keys(conn, target_user_id)
        # 清理用户附件
        _clean_user_attachments(conn, target_user_id)

        # 手动级联删除
        conn.execute("DELETE FROM poll_votes WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM board_replies WHERE user_id = ?", (target_user_id,))
        topic_rows = conn.execute(
            "SELECT id FROM board_topics WHERE user_id = ?", (target_user_id,)
        ).fetchall()
        for tr in topic_rows:
            tid = tr['id']
            conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM board_topics WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))
        conn.commit()
        _clean_user_media(media_keys, target_user_id)
        log('Admin', '删除用户', admin_user=admin_user['username'],
            target_user_id=target_user_id, ip=ip_address)
        return True, '用户已删除'
    except Exception:
        conn.rollback()
        log('Admin', '删除用户失败', admin_user=admin_user['username'],
            target_user_id=target_user_id, ip=ip_address)
        return False, '删除失败，请重试'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 管理员：切换管理员权限
# ---------------------------------------------------------------------------

def admin_toggle_admin(admin_user, target_user_id, ip_address):
    """切换用户管理员权限。返回 (success, message)。"""

    if target_user_id == admin_user['id']:
        return False, '不能修改自己的管理员权限'

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, is_admin FROM users WHERE id = ?", (target_user_id,)
        ).fetchone()
        if not target:
            return False, '用户不存在'

        new_status = 0 if target['is_admin'] else 1
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, target_user_id))
        conn.commit()
        log('Admin', '切换管理员权限', admin_user=admin_user['username'],
            target_user_id=target_user_id, new_status=new_status, ip=ip_address)
        return True, '管理员权限已更新'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, '操作失败'
    finally:
        conn.close()
