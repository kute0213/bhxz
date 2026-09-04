"""数据库备份路由：备份页面、启动备份、进度查询、历史列表、恢复。"""

import os
import sys
import json
import shutil
import subprocess
from datetime import datetime

from flask import render_template, jsonify, abort

from core.auth import admin_required, get_current_user
from core.db import get_db
from config import DB_PATH, BACKUP_DIR, APP_ROOT
from routes.admin import admin_bp
from core.logger import log


@admin_bp.route('/admin/db-backup')
@admin_required
def db_backup_page():
    """数据库备份管理页面。"""
    user = get_current_user()

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
        'admin/admin_db_backup.html',
        user=user,
        db_size=db_size,
        backups=backups,
        max_backups=get_config_value('MAX_BACKUPS', 30),
    )


@admin_bp.route('/admin/api/db-backup/start', methods=['POST'])
@admin_required
def api_db_backup_start():
    """启动手动数据库备份（异步执行）。"""
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


@admin_bp.route('/admin/api/db-backup/<int:backup_id>/delete', methods=['POST', 'DELETE'])
@admin_required
def api_db_backup_delete(backup_id):
    """删除指定备份（文件 + 记录）。"""
    user = get_current_user()

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
                log('ERROR', 'BackupManager', f'删除备份文件失败 {backup_path}: {e}')

        # 删除数据库记录
        conn.execute("DELETE FROM db_backups WHERE id = ?", (backup_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': '备份已删除'})


@admin_bp.route('/admin/api/db-backup/<int:backup_id>/restore', methods=['POST'])
@admin_required
def api_db_backup_restore(backup_id):
    """一键恢复数据库备份（在线恢复，无需重启服务器）。

    流程：
    1. 验证备份文件存在且有效
    2. 自动创建当前数据库的安全备份
    3. 使用 DuckDB COPY FROM DATABASE 在线恢复数据
    """
    user = get_current_user()

    conn = get_db()
    try:
        # 1. 查询备份记录
        row = conn.execute(
            "SELECT * FROM db_backups WHERE id = ?", (backup_id,)
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '备份记录不存在'}), 404

        backup = dict(row)
        backup_path = backup.get('backup_path')

        if not backup_path or not os.path.exists(backup_path):
            return jsonify({'success': False, 'message': '备份文件不存在'}), 404

        if backup.get('status') != 'success':
            return jsonify({'success': False, 'message': '只能恢复成功的备份'}), 400

        # 2. 自动创建当前数据库的安全备份
        safety_name = f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.duckdb"
        safety_path = os.path.join(BACKUP_DIR, safety_name)
        os.makedirs(BACKUP_DIR, exist_ok=True)

        try:
            conn.execute('CHECKPOINT')
            shutil.copy2(DB_PATH, safety_path)
            log('INFO', 'Backup', f'创建恢复前安全备份: {safety_name}')
        except Exception as e:
            log('ERROR', 'Backup', f'创建安全备份失败: {e}')
            return jsonify({'success': False, 'message': f'创建安全备份失败: {e}'}), 500

        # 记录安全备份到数据库
        try:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(
                "INSERT INTO db_backups (backup_name, backup_path, backup_type, status, size_bytes, started_at, finished_at) "
                "VALUES (?, ?, 'manual', 'success', ?, ?, ?)",
                (safety_name, safety_path, os.path.getsize(safety_path), now_str, now_str),
            )
            conn.commit()
        except Exception:
            pass  # 非关键，安全备份文件已存在

        # 3. 使用 DuckDB COPY FROM DATABASE 在线恢复
        try:
            # 获取当前数据库名
            db_rows = conn.execute(
                "SELECT database_name FROM duckdb_databases() WHERE database_name NOT IN ('system', 'temp')"
            ).fetchall()
            source_db = db_rows[0][0] if db_rows else 'main'

            sql_safe_backup_path = backup_path.replace('\\', '/').replace("'", "''")
            safe_source_db = source_db.replace('"', '""')

            # 先清空当前数据库的所有表（保留结构）
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
            for tbl in tables:
                tname = tbl[0]
                if tname in ('db_backups',):
                    continue  # 保留备份记录表
                conn.execute(f'DROP TABLE IF EXISTS "{tname.replace('"', '""')}" CASCADE')
            conn.commit()

            # 从备份附加并恢复
            conn.execute(f"ATTACH '{sql_safe_backup_path}' AS _restore_src (READ_ONLY)")
            conn.execute(f'COPY FROM DATABASE _restore_src TO "{safe_source_db}"')
            conn.execute("DETACH _restore_src")
            conn.commit()

            log('INFO', 'Backup', f'数据库已从备份恢复: {backup.get("backup_name")}',
                backup_id=backup_id, safety_backup=safety_name)

            return jsonify({
                'success': True,
                'message': '数据库已成功恢复，无需重启服务器',
                'safety_backup': safety_name,
            })
        except Exception as e:
            log('ERROR', 'Backup', f'数据库恢复失败: {e}')
            # 尝试从安全备份恢复
            try:
                log('INFO', 'Backup', '尝试从安全备份恢复...')
                db_rows = conn.execute(
                    "SELECT database_name FROM duckdb_databases() WHERE database_name NOT IN ('system', 'temp')"
                ).fetchall()
                source_db = db_rows[0][0] if db_rows else 'main'
                safe_source_db = source_db.replace('"', '""')
                sql_safe_path = safety_path.replace('\\', '/').replace("'", "''")
                conn.execute(f"ATTACH '{sql_safe_path}' AS _safety_src (READ_ONLY)")
                conn.execute(f'COPY FROM DATABASE _safety_src TO "{safe_source_db}"')
                conn.execute("DETACH _safety_src")
                conn.commit()
                log('INFO', 'Backup', f'已从安全备份恢复: {safety_name}')
            except Exception as e2:
                log('ERROR', 'Backup', f'安全备份恢复也失败: {e2}')
            return jsonify({'success': False, 'message': f'恢复失败: {e}'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/api/db-backup/<int:backup_id>/restart-restore', methods=['POST'])
@admin_required
def api_db_backup_restart_restore(backup_id):
    """一键恢复数据库备份（关闭服务器 → 替换数据库 → 启动服务器）。

    流程：
    1. 验证备份文件存在且有效
    2. 自动创建当前数据库的安全备份
    3. 生成恢复脚本参数并启动子进程
    4. 返回响应，服务器即将关闭
    """
    user = get_current_user()

    conn = get_db()
    try:
        # 1. 查询备份记录
        row = conn.execute(
            "SELECT * FROM db_backups WHERE id = ?", (backup_id,)
        ).fetchone()
        if not row:
            return jsonify({'success': False, 'message': '备份记录不存在'}), 404

        backup = dict(row)
        backup_path = backup.get('backup_path')

        if not backup_path or not os.path.exists(backup_path):
            return jsonify({'success': False, 'message': '备份文件不存在'}), 404

        if backup.get('status') != 'success':
            return jsonify({'success': False, 'message': '只能恢复成功的备份'}), 400

        # 2. 自动创建当前数据库的安全备份
        safety_name = f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.duckdb"
        safety_path = os.path.join(BACKUP_DIR, safety_name)
        os.makedirs(BACKUP_DIR, exist_ok=True)

        try:
            conn.execute('CHECKPOINT')
            shutil.copy2(DB_PATH, safety_path)
            log('INFO', 'Backup', f'创建恢复前安全备份: {safety_name}')
        except Exception as e:
            log('ERROR', 'Backup', f'创建安全备份失败: {e}')
            return jsonify({'success': False, 'message': f'创建安全备份失败: {e}'}), 500

        # 3. 启动恢复脚本
        python_exe = sys.executable
        restore_script = os.path.join(APP_ROOT, 'scripts', 'restore_db.py')

        if not os.path.isfile(restore_script):
            log('ERROR', 'Backup', f'恢复脚本不存在: {restore_script}')
            return jsonify({'success': False, 'message': '恢复脚本不存在'}), 500

        try:
            # 写入恢复标志文件（供恢复脚本读取）
            flag_file = os.path.join(BACKUP_DIR, '.restore_flag')
            flag_data = {
                'backup_path': backup_path,
                'safety_path': safety_path,
                'triggered_by': user['username'],
                'timestamp': datetime.now().isoformat(),
            }
            with open(flag_file, 'w') as f:
                json.dump(flag_data, f)

            # 启动恢复脚本，传入备份路径
            subprocess.Popen(
                [python_exe, restore_script, backup_path],
                cwd=APP_ROOT,
                close_fds=True,
            )
            log('INFO', 'Backup', f'数据库恢复脚本已启动',
                backup_id=backup_id, safety_backup=safety_name)

            return jsonify({
                'success': True,
                'message': '数据库正在恢复，服务器将自动重启，请稍后刷新页面...',
                'safety_backup': safety_name,
                'restarting': True,
            })
        except Exception as e:
            log('ERROR', 'Backup', f'启动恢复脚本失败: {e}')
            return jsonify({'success': False, 'message': f'启动恢复脚本失败: {e}'}), 500
    finally:
        conn.close()
