import os
import json
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, abort
from core.auth import login_required, get_current_user
from core.database import get_db
from config import REGISTER_VERIFY_CODE, UPLOAD_DIR
from services.monitoring import get_cpu_usage, get_cpu_temperature, get_memory_info, get_system_info
from services.ip import get_client_ip

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
@login_required
def admin_page():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    stats = {
        'total_users': conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c'],
        'total_polls': conn.execute("SELECT COUNT(*) AS c FROM polls").fetchone()['c'],
        'total_votes': conn.execute("SELECT COUNT(*) AS c FROM poll_votes").fetchone()['c'],
        'total_board_topics': conn.execute("SELECT COUNT(*) AS c FROM board_topics").fetchone()['c'],
        'total_board_replies': conn.execute("SELECT COUNT(*) AS c FROM board_replies").fetchone()['c'],
        'total_mod_intros': conn.execute("SELECT COUNT(*) AS c FROM mod_intros").fetchone()['c'],
    }
    conn.close()

    return render_template('admin.html', user=user, stats=stats)


@admin_bp.route('/admin/users')
@login_required
def admin_users():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    users_list = conn.execute("""
        SELECT id, username, is_admin, created_at
        FROM users
        ORDER BY id DESC
    """).fetchall()
    users_list = [dict(u) for u in users_list]
    conn.close()

    return render_template('admin_users.html', user=user, users_list=users_list)


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
    target = conn.execute("SELECT id, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        conn.close()
        abort(404)

    new_status = 0 if target['is_admin'] else 1
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, user_id))
    conn.commit()
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
        flash('用户已删除', 'success')
    except Exception:
        conn.rollback()
        flash('删除失败，请重试', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/admin/logs')
@login_required
def admin_logs():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    total = conn.execute("SELECT COUNT(*) AS c FROM access_logs").fetchone()['c']
    total_pages = (total + per_page - 1) // per_page

    logs = conn.execute("""
        SELECT * FROM access_logs
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset)).fetchall()
    logs = [dict(log) for log in logs]
    conn.close()

    return render_template(
        'admin_logs.html',
        user=user,
        logs=logs,
        page=page,
        total_pages=total_pages,
        total=total
    )


@admin_bp.route('/admin/logs/clear', methods=['POST'])
@login_required
def admin_logs_clear():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    conn.execute("DELETE FROM access_logs")
    conn.commit()
    conn.close()
    flash('访问日志已清空', 'success')
    return redirect(url_for('admin.admin_logs'))


@admin_bp.route('/admin/debug/headers')
@login_required
def admin_debug_headers():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    headers = dict(request.headers)
    current_ip = get_client_ip()
    remote_addr = request.remote_addr

    return render_template(
        'admin_debug_headers.html',
        user=user,
        headers=headers,
        current_ip=current_ip,
        remote_addr=remote_addr
    )


@admin_bp.route('/admin/mod-intros')
@login_required
def manage_mod_intros():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    intros = conn.execute("SELECT * FROM mod_intros ORDER BY id ASC").fetchall()
    intros = [dict(r) for r in intros]
    conn.close()

    return render_template('manage_mod_intros.html', user=user, mod_intros=intros)


@admin_bp.route('/admin/mod-intros/add', methods=['POST'])
@login_required
def add_mod_intro():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    icon = request.form.get('icon', 'box').strip()
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if title and content:
        conn = get_db()
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO mod_intros (icon, title, content, created_at) VALUES (?, ?, ?, ?)",
            (icon, title, content, now)
        )
        conn.commit()
        conn.close()
        flash('模组介绍已添加', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


@admin_bp.route('/admin/mod-intros/<int:intro_id>/edit', methods=['POST'])
@login_required
def edit_mod_intro(intro_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    icon = request.form.get('icon', 'box').strip()
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if title and content:
        conn = get_db()
        conn.execute(
            "UPDATE mod_intros SET icon = ?, title = ?, content = ? WHERE id = ?",
            (icon, title, content, intro_id)
        )
        conn.commit()
        conn.close()
        flash('模组介绍已更新', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


@admin_bp.route('/admin/mod-intros/<int:intro_id>/delete', methods=['POST'])
@login_required
def delete_mod_intro(intro_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    conn.execute("DELETE FROM mod_intros WHERE id = ?", (intro_id,))
    conn.commit()
    conn.close()
    flash('模组介绍已删除', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


# ---------------------------------------------------------------------------
# 数据库备份与优化
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/db-backup')
@login_required
def db_backup_page():
    """数据库备份管理页面。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()

    # 数据库文件大小
    db_size = 0
    try:
        import os
        from config import DB_PATH
        if os.path.exists(DB_PATH):
            db_size = os.path.getsize(DB_PATH)
    except Exception:
        pass

    # 最近 20 条备份记录
    backup_rows = conn.execute("""
        SELECT * FROM db_backups
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    backups = [dict(b) for b in backup_rows]
    conn.close()

    return render_template(
        'admin_db_backup.html',
        user=user,
        db_size=db_size,
        backups=backups,
    )


@admin_bp.route('/admin/api/db-backup/start', methods=['POST'])
@login_required
def api_db_backup_start():
    """启动手动数据库备份（异步执行）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'message': '无权限'}), 403

    from services.backup_manager import BackupManager
    backup_id, thread = BackupManager().start_backup(
        backup_type='manual',
        progress_callback=None,
    )

    if backup_id is None:
        return jsonify({
            'success': False,
            'message': '已有备份在进行中，请稍后再试',
        })

    return jsonify({
        'success': True,
        'backup_id': backup_id,
        'message': '备份已启动',
    })


@admin_bp.route('/admin/api/db-backup/progress')
@login_required
def api_db_backup_progress():
    """获取当前备份进度。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'message': '无权限'}), 403

    from services.backup_manager import BackupManager
    bm = BackupManager()
    progress = bm.get_progress()
    last_backup = bm.get_last_backup()

    return jsonify({
        'in_progress': progress is not None,
        'percent': progress if progress is not None else 0,
        'last_backup': last_backup,
    })


@admin_bp.route('/admin/api/db-backup/list')
@login_required
def api_db_backup_list():
    """获取备份历史列表。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'message': '无权限'}), 403

    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM db_backups
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    backups = [dict(b) for b in rows]
    conn.close()

    return jsonify({'backups': backups})
