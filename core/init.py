"""应用初始化 —— 启动检查、数据库、蓝图、钩子、后台服务。"""

import os
import sys

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
    from services.logging import log_cleaner
    from services.backup import BackupScheduler
    from services.email import email_service
    from services.sitemap_cache import sitemap_cache
    from services.rcon import player_tracker

    log_cleaner.start()
    scheduler.start()
    BackupScheduler().start()
    email_service.start()
    sitemap_cache.start()
    player_tracker.start()
    log('INFO', 'App', '后台服务启动完成')


def init_app(app, app_root):
    """初始化应用：启动检查、数据库、蓝图、钩子、模板上下文、后台服务。"""
    from core.startup_checks import run_startup_checks
    from core.db import init_db

    # 确保工作目录始终是项目根目录
    os.chdir(app_root)

    # 先初始化数据库，确保 settings 等表已存在，再执行健康检查。
    # 注意：run_startup_checks 中的 _check_database() 会再次调用 init_db()（幂等操作）。
    log('INFO', 'App', '正在初始化数据库...')
    try:
        init_db()
    except Exception as e:
        import traceback
        print(f'[FATAL] 数据库初始化失败: {e}', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise
    log('INFO', 'App', '数据库初始化完成')

    # 数据库就绪后刷新日志等级缓存（从 settings 表读取）
    from core.logger import refresh_log_level
    refresh_log_level()

    # 每次启动执行服务器健康检查（自动修复，不删文件）
    run_startup_checks(app_root)

    log('INFO', 'App', '正在注册蓝图...')
    from routes.registry import register_blueprints
    try_serve_public = register_blueprints(app)

    register_hooks(app, try_serve_public)

    # 注册模板上下文处理器
    register_template_context(app)

    log('INFO', 'App', '正在启动后台服务...')
    start_background_services()

    log('INFO', 'App', '应用初始化完成')