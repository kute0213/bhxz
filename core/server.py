"""WSGI 服务器 —— 启动、关闭、优雅退出。"""

import os
import socket
import signal
import ssl
import threading

from flask import Flask, render_template

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

    from services.logging import log_writer, log_cleaner
    from services.scheduler import scheduler
    from services.backup import BackupScheduler
    from services.email import email_service
    from services.sitemap_cache import sitemap_cache
    from core.db import get_db

    # 先停止接收新请求
    if _server is not None:
        try:
            _server.stop()
        except Exception as exc:
            log('WARNING', 'App', f'HTTP 服务关闭异常: {exc}')

    BackupScheduler().stop()
    email_service.stop()
    scheduler.stop()
    sitemap_cache.stop()
    log_cleaner.stop()
    # 日志写入器最后停止
    log_writer.stop()
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
        return render_template('404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('403.html'), 403


def run_server(app, port=5000, app_root=None):
    """使用 Cheroot 作为 WSGI 服务器，可选 SSL。"""
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

    from cheroot.wsgi import Server
    server = Server(
        ('0.0.0.0', port),
        app,
        request_queue_size=100,
        numthreads=20,
    )
    _server = server

    if has_ssl:
        log('INFO', 'App', f'HTTPS 模式运行 (端口 {port})')
        log('INFO', 'App', f'证书: {cert_path}')
        log('INFO', 'App', f'私钥: {key_path}')
        try:
            from cheroot.ssl.builtin import BuiltinSSLAdapter
            server.ssl_adapter = BuiltinSSLAdapter(
                certificate=cert_path,
                private_key=key_path,
                certificate_chain=None,
                ciphers='ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS',
            )
            # 配置 SSL 会话上下文（启用会话缓存）
            ctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
            ctx.set_ciphers(
                'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS'
            )
            # 通过 session_stats 触发会话缓存初始化
            ctx.session_stats()
            server.ssl_adapter.context = ctx
        except ImportError as e:
            log('WARNING', 'App', f'无法加载 SSL 适配器 ({e})，回退到 HTTP 模式')
            log('WARNING', 'App', f'HTTP 模式运行 (端口 {port})')
    else:
        log('WARNING', 'App', f'未找到 SSL 证书文件 ({cert_path} 或 {key_path})')
        log('WARNING', 'App', f'回退到 HTTP 模式运行 (端口 {port})')

    try:
        server.start()
    except KeyboardInterrupt:
        shutdown_application(signal.SIGINT)
    except Exception as e:
        log('ERROR', 'App', f'服务器启动失败: {e}')
        raise
    finally:
        shutdown_application()