"""应用初始化 —— 按依赖关系分层加载。

加载顺序（自底向上）：
  1. 工作目录 & 数据库（基础设施层）
  2. 日志等级 & 健康检查（监控层）
  3. 蓝图注册（路由层）
  4. 请求钩子（中间件层）
  5. 模板上下文（视图层）
  6. 后台服务（服务层）
"""

import os
import sys

from core.system.logger import log
from core.template_context import register_template_context


def register_hooks(app, try_serve_public):
    """注册请求钩子。"""
    log('INFO', 'App', '正在注册请求钩子...')
    from core.middleware import register_hooks as _register_hooks
    _register_hooks(app, try_serve_public)


def start_background_services():
    """启动所有后台服务。"""
    from core.shared.scheduler import start_task_scheduler
    from services.backup import BackupScheduler
    from services.mail import email_service
    from services.sitemap_cache import sitemap_cache
    from services.rcon import player_tracker
    from services.cleanup_service import cleanup_scheduler
    from services.game_server_ban import game_ban_scheduler

    # 先启动统一任务注册表（每秒检测，全站定时任务共用，见 core/shared/scheduler/）
    start_task_scheduler()
    BackupScheduler().start()
    email_service.start()
    sitemap_cache.start()
    player_tracker.start()
    # 被驳回内容自动清理（指南/背景图片超 24 小时删除）—— 导入即完成注册
    # 游戏服务器封禁到期自动解封（每 60 秒检查一次）—— 导入即完成注册
    log('INFO', 'App', '后台服务启动完成')


def init_app(app, app_root):
    """初始化应用：启动检查、数据库、蓝图、钩子、模板上下文、后台服务。"""
    # ============================================================
    # 第 1 层：基础设施 — 工作目录 & 数据库
    # ============================================================
    from core.db import init_db

    # 确保工作目录始终是项目根目录
    os.chdir(app_root)

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

    # ============================================================
    # 第 2 层：监控 — 日志等级 & 健康检查
    # ============================================================

    # 数据库就绪后刷新日志等级缓存（从 settings 表读取）
    from core.system.logger import refresh_log_level
    refresh_log_level()

    # 每次启动执行服务器健康检查（自动修复，不删文件）
    from core.system.startup_checks import run_startup_checks
    run_startup_checks(app_root)

    # ============================================================
    # 第 3 层：路由 — 蓝图中注册
    # ============================================================

    log('INFO', 'App', '正在注册蓝图...')
    from routes import register_blueprints
    try_serve_public = register_blueprints(app)

    # ============================================================
    # 第 4 层：中间件 — 请求钩子（依赖蓝图注册完毕）
    # ============================================================

    register_hooks(app, try_serve_public)

    # ============================================================
    # 第 5 层：视图 — 模板上下文
    # ============================================================

    register_template_context(app)

    # ============================================================
    # 第 6 层：服务 — 后台异步服务（最后一层，不阻塞启动）
    # ============================================================

    log('INFO', 'App', '正在启动后台服务...')
    start_background_services()

    log('INFO', 'App', '应用初始化完成')