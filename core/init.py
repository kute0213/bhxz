"""应用初始化 —— 数据库、迁移、蓝图、钩子、后台服务。"""

import os
import sys
import subprocess

from flask import Flask

from core.logger import log
from core.template_context import register_template_context


def register_hooks(app, try_serve_public):
    """注册请求钩子。"""
    log('INFO', 'App', '正在注册请求钩子...')
    from core.middleware import register_hooks as _register_hooks
    _register_hooks(app, try_serve_public)


def start_background_services():
    """启动所有后台服务。"""
    from services.scheduler import scheduler
    from services.logging import log_cleaner, log_writer
    from services.backup import BackupScheduler
    from services.email import email_service
    from services.sitemap_cache import sitemap_cache

    log_writer.start()
    log_cleaner.start()
    scheduler.start()
    BackupScheduler().start()
    email_service.start()
    sitemap_cache.start()
    log('INFO', 'App', '后台服务启动完成')


def run_pending_migrations(app_root):
    """检查并执行标记为待处理的清理与迁移脚本。

    在 init_db() 之前执行，此时服务器尚未打开数据库连接，无锁冲突。
    一键更新在 updater.py 中设置 UPLOADS_MIGRATION_PENDING=1 标记，
    重启后在此处执行，避免在服务器运行中直接操作数据库导致锁冲突。
    """
    try:
        from services.settings_manager import get_setting, set_setting
        if get_setting('UPLOADS_MIGRATION_PENDING', '0') != '1':
            return

        log('INFO', 'App', '检测到待执行的清理与迁移任务，正在运行...')
        uploads_script = os.path.join(app_root, 'scripts', 'uploads.py')
        if not os.path.isfile(uploads_script):
            log('WARNING', 'App', 'scripts/uploads.py 不存在，跳过迁移')
            try:
                set_setting('UPLOADS_MIGRATION_PENDING', '0')
            except Exception:
                pass
            return

        proc = subprocess.Popen(
            [sys.executable, uploads_script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in iter(proc.stdout.readline, ''):
            line = line.rstrip('\n\r')
            if line:
                log('INFO', 'App', f'  | {line}')
        proc.wait(timeout=120)
        if proc.returncode == 0:
            log('INFO', 'App', '清理与迁移完成')
        else:
            log('WARNING', 'App', f'清理脚本返回码: {proc.returncode}')
        proc.stdout.close()

        try:
            set_setting('UPLOADS_MIGRATION_PENDING', '0')
        except Exception:
            pass
    except Exception as e:
        log('WARNING', 'App', f'执行清理与迁移失败: {e}')


def init_app(app, app_root):
    """初始化应用：数据库、迁移、蓝图、钩子、模板上下文、后台服务。"""
    from core.db import init_db

    # 确保工作目录始终是项目根目录
    os.chdir(app_root)

    # 检查是否有待执行的清理与迁移脚本
    run_pending_migrations(app_root)

    log('INFO', 'App', '正在初始化数据库...')
    init_db()
    log('INFO', 'App', '数据库初始化完成')

    log('INFO', 'App', '正在注册蓝图...')
    from routes.registry import register_blueprints
    try_serve_public = register_blueprints(app)

    register_hooks(app, try_serve_public)

    # 注册模板上下文处理器
    register_template_context(app)

    log('INFO', 'App', '正在启动后台服务...')
    start_background_services()