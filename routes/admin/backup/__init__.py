"""数据备份路由：备份页面、启动备份、进度查询、历史列表、下载、删除。"""

import os
import sys
import json
import subprocess
from datetime import datetime

from flask import jsonify, send_file

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.db import get_db
from config import DB_PATH, UPLOAD_DIR, get_config_value, get_backup_dir
from routes.admin import admin_bp
from core.system.logger import log


@admin_bp.route('/admin/db-backup')
@admin_required
def db_backup_page():
    """数据备份管理页面。"""
    conn = get_db()
    try:
        # 数据量统计
        db_size = 0
        try:
            if os.path.exists(DB_PATH):
                db_size = os.path.getsize(DB_PATH)
        except Exception:
            pass

        # /uploads/ 目录总大小
        uploads_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(UPLOAD_DIR):
                for f in filenames:
                    try:
                        fp = os.path.join(dirpath, f)
                        if os.path.isfile(fp):
                            uploads_size += os.path.getsize(fp)
                    except Exception:
                        pass
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

    return render_page(
        'admin/db_backup.html',
        db_size=db_size,
        uploads_size=uploads_size,
        backups=backups,
        max_backups=get_config_value('MAX_BACKUPS', 30),
        backup_dir=get_backup_dir(),
        backup_dir_setting=get_config_value('BACKUP_DIR', '../bhxz_backups'),
    )


@admin_bp.route('/admin/api/db-backup/start', methods=['POST'])
@admin_required
def api_db_backup_start():
    """启动手动数据备份（异步执行）。"""
    user = get_current_user()

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
@admin_required
def api_db_backup_progress():
    """获取当前备份进度。"""
    user = get_current_user()

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
@admin_required
def api_db_backup_list():
    """获取备份历史列表。"""
    user = get_current_user()

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


@admin_bp.route('/admin/api/db-backup/<int:backup_id>/download')
@admin_required
def api_db_backup_download(backup_id):
    """下载备份文件到本地。"""
    user = get_current_user()

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM db_backups WHERE id = ?", (backup_id,)
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '备份记录不存在'}), 404

        backup = dict(row)
        backup_path = backup.get('backup_path')

        if not backup_path or not os.path.exists(backup_path):
            return jsonify({'success': False, 'message': '备份文件不存在'}), 404

        backup_name = backup.get('backup_name') or os.path.basename(backup_path)
        return send_file(
            backup_path,
            as_attachment=True,
            download_name=backup_name,
            mimetype='application/zip',
        )
    except Exception as e:
        log('ERROR', 'BackupManager', f'下载备份失败: {e}')
        return jsonify({'success': False, 'message': f'下载失败: {e}'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/api/db-backup/<int:backup_id>/delete', methods=['POST', 'DELETE'])
@admin_required
def api_db_backup_delete(backup_id):
    """删除指定备份（文件 + 记录）。"""
    user = get_current_user()

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
                log('ERROR', 'BackupManager', f'删除备份文件失败 {backup_path}: {e}')

        # 删除数据库记录
        conn.execute("DELETE FROM db_backups WHERE id = ?", (backup_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': '备份已删除'})