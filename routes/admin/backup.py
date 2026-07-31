"""数据库备份路由：备份页面、启动备份、进度查询、历史列表。"""

import os

from flask import render_template, jsonify, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from config import DB_PATH
from routes.admin import admin_bp


@admin_bp.route('/admin/db-backup')
@login_required
def db_backup_page():
    """数据库备份管理页面。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    from config import get_config_value

    conn = get_db()
    try:
        # 数据库文件大小
        db_size = 0
        try:
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
    finally:
        conn.close()

    return render_template(
        'admin_db_backup.html',
        user=user,
        db_size=db_size,
        backups=backups,
        max_backups=get_config_value('MAX_BACKUPS', 30),
    )


@admin_bp.route('/admin/api/db-backup/start', methods=['POST'])
@login_required
def api_db_backup_start():
    """启动手动数据库备份（异步执行）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'message': '无权限'}), 403

    from services.backup import BackupManager
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

    from services.backup import BackupManager
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
    try:
        rows = conn.execute("""
            SELECT * FROM db_backups
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()
        backups = [dict(b) for b in rows]
    finally:
        conn.close()

    return jsonify({'backups': backups})


@admin_bp.route('/admin/api/db-backup/<int:backup_id>/delete', methods=['POST', 'DELETE'])
@login_required
def api_db_backup_delete(backup_id):
    """删除指定备份（文件 + 记录）。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'message': '无权限'}), 403

    from config import BACKUP_DIR

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM db_backups WHERE id = ?", (backup_id,)
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '备份记录不存在'}), 404

        backup = dict(row)
        backup_path = backup.get('backup_path')

        # 删除文件
        if backup_path:
            try:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
            except Exception as e:
                print(f'[Backup] 删除备份文件失败 {backup_path}: {e}', flush=True)

        # 删除数据库记录
        conn.execute("DELETE FROM db_backups WHERE id = ?", (backup_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': '备份已删除'})
