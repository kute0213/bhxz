"""WSGI 服务器 —— 启动、关闭、优雅退出。"""

import os
import socket
import signal
import ssl
import threading

from flask import render_template

from core.logger import log

_server = None
_shutdown_started = False
_shutdown_lock = threading.Lock()


def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def shutdown_application(signum=None):
    """幂等地停止 HTTP 服务、后台服务并提交剩余数据库事务。"""
    global _shutdown_started

    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    if signum is not None:
        log('INFO', 'App', f'收到信号 {signum}，正在关闭服务器...')

    from services.logging import log_cleaner
    from services.scheduler import scheduler
    from services.backup import BackupScheduler
    from services.email import email_service
    from services.sitemap_cache import sitemap_cache
    from core.db import get_db

    # 先停止接收新请求
    if _server is not None:
        try:
            _server.close()
        except Exception as exc:
            log('WARNING', 'App', f'HTTP 服务关闭异常: {exc}')

    BackupScheduler().stop()
    email_service.stop()
    scheduler.stop()
    sitemap_cache.stop()
    log_cleaner.stop()
    try:
        conn = get_db()
        conn.commit()
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


def register_error_handlers(app):
    """注册全局错误处理页面。"""

    @app.errorhandler(404)
    def page_not_found(e):
        from core.auth import get_current_user
        return render_template('404.html', user=get_current_user()), 404

    @app.errorhandler(403)
    def forbidden(e):
        from core.auth import get_current_user
        return render_template('403.html', user=get_current_user()), 403


def run_server(app, port=5000, app_root=None):
    """使用 Waitress 作为 WSGI 服务器，可选 SSL。

    优先使用 Waitress（生产级），若未安装则回退到 Flask 内置服务器。
    """
    global _server

    log('INFO', 'App', f'工作目录: {os.getcwd()}')
    log('INFO', 'App', f'APP_ROOT: {app_root}')

    if is_port_in_use(port):
        log('ERROR', 'App', f'端口 {port} 已被占用，请先关闭其他程序')
        return

    ssl_dir = os.path.join(app_root, 'ssl') if app_root else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ssl')
    key_path = os.path.join(ssl_dir, 'private.key')
    cert_path = os.path.join(ssl_dir, 'fullchain.pem')

    enable_ssl = os.environ.get('ENABLE_SSL', '0').lower() in ('1', 'true', 'yes', 'on')
    has_ssl = enable_ssl and os.path.isfile(key_path) and os.path.isfile(cert_path)

    # 尝试使用 Waitress（生产级 WSGI 服务器）
    try:
        import waitress
        log('INFO', 'App', '使用 Waitress 服务器')
        server = waitress.create_server(
            app,
            host='0.0.0.0',
            port=port,
            threads=20,
        )
        _server = server
        if has_ssl:
            log('WARNING', 'App', 'Waitress 不支持 SSL 终端，请使用反向代理（如 Nginx）处理 HTTPS')
            log('WARNING', 'App', f'HTTP 模式运行 (端口 {port})')
        try:
            server.run()
        except KeyboardInterrupt:
            shutdown_application(signal.SIGINT)
        except Exception as e:
            log('ERROR', 'App', f'服务器错误: {e}')
            raise
        finally:
            shutdown_application()
        return
    except ImportError:
        log('WARNING', 'App', 'Waitress 未安装，回退到 Flask 内置服务器')

    # 使用 Waitress 失败，使用 Flask 内置服务器
    protocol = 'HTTPS' if has_ssl else 'HTTP'
    log('INFO', 'App', f'使用 Flask 内置服务器（{protocol} 模式）')
    log('WARNING', 'App', '建议安装 Waitress 获取更好的性能：pip install waitress')

    if has_ssl:
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(cert_path, key_path)
            app.run(host='0.0.0.0', port=port, ssl_context=ssl_context, threaded=True, debug=False)
        except Exception as e:
            log('WARNING', 'App', f'SSL 加载失败 ({e})，回退到 HTTP')
            app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
    else:
        app.run(host='0.0.0.0', port=port, threaded=True, debug=False)