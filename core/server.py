"""WSGI 服务器 —— 启动、关闭、优雅退出。"""

import os
import socket
import signal
import threading

from core.system.logger import log, log_fatal

_server = None
_shutdown_started = False
_shutdown_lock = threading.Lock()


def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def _stop_server():
    """停止 Waitress 服务器（幂等）。"""
    if _server is None:
        return
    try:
        _server.close()
    except Exception as exc:
        log('WARNING', 'App', f'HTTP 服务关闭异常: {exc}')


def shutdown_application(signum=None):
    """幂等地停止 HTTP 服务、后台服务并提交剩余数据库事务。"""
    global _shutdown_started

    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    if signum is not None:
        log('INFO', 'App', f'收到信号 {signum}，正在关闭服务器...')

    from services.backup import BackupScheduler
    from services.mail import email_service
    from services.sitemap_cache import sitemap_cache
    from core.db import get_db

    # 先停止接收新请求
    _stop_server()

    # 停止高性能防火墙（黑名单镜像同步 / DDoS 检测后台线程）
    try:
        from services.firewall import firewall
        firewall.stop_monitor()
    except Exception as exc:
        log('WARNING', 'App', f'防火墙关闭异常: {exc}')

    # 停止统一任务注册表（tick 线程 + 执行器）
    try:
        from core.shared.scheduler import stop_task_scheduler
        stop_task_scheduler()
    except Exception as exc:
        log('WARNING', 'App', f'任务注册表关闭异常: {exc}')

    BackupScheduler().stop()
    email_service.stop()
    sitemap_cache.stop()
    try:
        conn = get_db()
        conn.commit()
        # 强制 WAL checkpoint，确保所有待刷数据落盘（避免进程被杀导致 WAL 文件残留）
        try:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except Exception:
            pass
    except Exception as exc:
        log('WARNING', 'App', f'关闭前提交数据库失败: {exc}')
    log('INFO', 'App', '服务器已关闭')


def graceful_shutdown(signum, frame):
    """收到终止信号时触发统一关闭流程。"""
    shutdown_thread = threading.Thread(
        target=shutdown_application,
        args=(signum,),
        name='app-shutdown',
        daemon=False,
    )
    shutdown_thread.start()


def run_server(app, port=5000, app_root=None):
    """使用 Waitress 作为生产 WSGI 服务器。

    SSL 不在应用层处理：证书与 HTTPS 由内网穿透 / 反向代理层统一终结，
    应用仅监听 HTTP。被防火墙拦截的请求由 WSGI 门禁直接断开连接。
    """
    global _server

    from services.firewall import firewall
    wrapped_app = firewall.wrap(app)

    log('INFO', 'App', f'工作目录: {os.getcwd()}')
    log('INFO', 'App', f'APP_ROOT: {app_root}')

    if is_port_in_use(port):
        log_fatal('CRITICAL', 'App', '端口已被占用，服务器退出', port=port)
        return

    try:
        from waitress import create_server
    except ImportError:
        log('ERROR', 'App', 'Waitress 未安装，请执行: pip install waitress')
        log('WARNING', 'App', '回退到 Flask 内置服务器（WSGI 防火墙仍生效）')
        firewall.start_monitor()
        from werkzeug.serving import run_simple
        log('INFO', 'App', f'使用 run_simple（HTTP 模式，端口 {port}）')
        run_simple('0.0.0.0', port, wrapped_app, threaded=True)
        return

    server = create_server(
        wrapped_app,
        host='0.0.0.0',
        port=port,
        threads=20,
        connection_limit=1000,
        channel_timeout=300,
        asyncore_use_poll=True,
    )
    _server = server

    # 启动高性能防火墙（黑名单镜像同步 + DDoS 检测后台线程）
    firewall.start_monitor()
    log('INFO', 'App', f'使用 Waitress 服务器，HTTP 模式运行 (端口 {port})')

    try:
        server.run()
    except KeyboardInterrupt:
        shutdown_application(signal.SIGINT)
    except Exception as e:
        log_fatal('CRITICAL', 'App', '服务器启动失败，进程退出', error=str(e))
        raise
    finally:
        shutdown_application()
