"""用户管理路由：用户列表、切换管理员、删除用户。"""

import os
import json

from flask import render_template, redirect, url_for, flash, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from config import UPLOAD_DIR
from routes.admin import admin_bp
from services.logger import log


@admin_bp.route('/admin/users')
@login_required
def admin_users():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        users_list = conn.execute("""
            SELECT id, username, is_admin, created_at
            FROM users
            ORDER BY id DESC
        """).fetchall()
        users_list = [dict(u) for u in users_list]
    finally:
        conn.close()

    return render_template('admin/admin_users.html', user=user, users_list=users_list)


@admin_bp.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
def admin_toggle_admin(user_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    if user_id == user['id']:
        flash('不能修改自己的管理员权限', 'error')
        return redirect(url_for('admin.admin_users'))

    conn = get_db()
    try:
        target = conn.execute("SELECT id, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            abort(404)

        new_status = 0 if target['is_admin'] else 1
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, user_id))
        conn.commit()
        log('Admin', '切换管理员权限', admin_user=user['username'], target_user_id=user_id, new_status=new_status, ip=request.remote_addr)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    if user_id == user['id']:
        flash('不能删除自己', 'error')
        return redirect(url_for('admin.admin_users'))

    conn = get_db()
    try:
        # 级联删除前清理用户回复中的附件文件
        replies = conn.execute("SELECT attachment FROM board_replies WHERE user_id = ?", (user_id,)).fetchall()
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
        conn.execute("DELETE FROM poll_votes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM board_replies WHERE user_id = ?", (user_id,))
        # 删除用户创建的投票（连带选项和投票记录）
        # 注意：polls 表没有 user_id，所以不删除投票，只删除该用户的投票记录
        # 删除用户创建的留言板主题（连带回复）
        topic_rows = conn.execute(
            "SELECT id FROM board_topics WHERE user_id = ?", (user_id,)
        ).fetchall()
        for tr in topic_rows:
            tid = tr['id'] if hasattr(tr, '__getitem__') and isinstance(tr[0], int) else tr[0]
            conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM board_topics WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        log('Admin', '删除用户', admin_user=user['username'], target_user_id=user_id, ip=request.remote_addr)
        flash('用户已删除', 'success')
    except Exception:
        conn.rollback()
        log('Admin', '删除用户失败', admin_user=user['username'], target_user_id=user_id, ip=request.remote_addr)
        flash('删除失败，请重试', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_users'))
