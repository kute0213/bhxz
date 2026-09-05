"""用户业务服务 - 个人资料管理（修改用户名、密码、邮箱、注销账号）。"""

import os
from datetime import datetime

from core.auth import hash_password, validate_password, verify_password
from core.db import get_db
from config import get_config_value
from services.email import email_code_service
from core.logger import log
from services.attachment_service import clean_attachment_json


def _clean_user_attachments(conn, user_id):
    """清理用户相关的所有附件（board_replies 中的附件）。"""
    replies = conn.execute(
        "SELECT attachment FROM board_replies WHERE user_id = ?", (user_id,)
    ).fetchall()
    for r in replies:
        if r['attachment']:
            clean_attachment_json(r['attachment'])

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
    for filepath in keys:
        try:
            if filepath and os.path.isfile(filepath):
                os.remove(filepath)
        except Exception as exc:
            log('UserMedia', '账号图片清理失败', user_id=user_id,
                filepath=filepath, error=str(exc))


def change_username(user_id, current_username, new_username, current_password, ip_address):
    """修改用户名。返回 (success, message)。"""

    from services.validation import validate_website_username
    valid, err = validate_website_username(new_username)
    if not valid:
        return False, err

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

        if get_config_value('EMAIL_ENABLED', False) and get_config_value('REGISTER_EMAIL_VERIFY', False):
            if not email_code:
                return False, '请输入邮箱验证码'
            if not email_code_service.verify(new_email, email_code, purpose='修改邮箱'):
                return False, '邮箱验证码错误或已过期'

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


def delete_account(user_id, username, confirm_username, ip_address):
    """注销用户，级联清理所有关联数据。返回 (success, message)。"""

    if confirm_username != username:
        return False, '用户名确认不匹配'

    conn = get_db()
    try:
        media_keys = _get_user_media_keys(conn, user_id)
        _clean_user_attachments(conn, user_id)

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