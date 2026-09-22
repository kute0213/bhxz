"""WSGI 服务器 —— 启动、关闭、优雅退出。"""

import os
import socket
import signal
import ssl
import threading

from core.system.logger import log

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

    from services.backup import BackupScheduler
    from services.mail import email_service
    from services.sitemap_cache import sitemap_cache
    from core.db import get_db

    # 先停止接收新请求
    if _server is not None:
        try:
            _server.stop()
        except Exception as exc:
            log('WARNING', 'App', f'HTTP 服务关闭异常: {exc}')

    # 停止高性能防火墙（黑名单镜像同步 / DDoS 检测后台线程）
    try:
        from routes.firewall import firewall
        firewall.stop_monitor()
    except Exception as exc:
        log('WARNING', 'App', f'防火墙关闭异常: {exc}')

    # 停止统一任务注册表（tick 线程 + 执行器）
    try:
        from utils.shared.scheduler import stop_task_scheduler
        stop_task_scheduler()
    except Exception as exc:
        log('WARNING', 'App', f'任务注册表关闭异常: {exc}')

    BackupScheduler().stop()
    email_service.stop()
    sitemap_cache.stop()
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


def run_server(app, port=5000, app_root=None):
    """使用 Cheroot 作为 WSGI 服务器，可选 SSL。"""
    global _server

    from routes.firewall import firewall
    wrapped_app = firewall.wrap(app)

    log('INFO', 'App', f'工作目录: {os.getcwd()}')
    log('INFO', 'App', f'APP_ROOT: {app_root}')

    if is_port_in_use(port):
        log('ERROR', 'App', f'端口 {port} 已被占用，请先关闭其他程序')
        return

    ssl_dir = os.path.join(app_root, 'ssl') if app_root else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ssl')
    key_path = os.path.join(ssl_dir, 'private.key')
    cert_path = os.path.join(ssl_dir, 'fullchain.pem')

    enable_ssl = os.environ.get('ENABLE_SSL', '0').lower() in ('1', 'true', 'yes', 'on')
    has_ssl = enable_ssl and os.path.isfile(key_path) and os.path.isfile(cert_path)

    try:
        from cheroot.wsgi import Server as CherootServer
    except ImportError:
        log('ERROR', 'App', 'Cheroot 未安装，请执行: pip install cheroot')
        log('WARNING', 'App', '回退到 Flask 内置服务器（WSGI 防火墙仍生效）')
        firewall.start_monitor()
        from werkzeug.serving import run_simple
        ssl_context = None
        if has_ssl:
            try:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(cert_path, key_path)
            except Exception as e:
                log('WARNING', 'App', f'SSL 加载失败 ({e})，回退到 HTTP')
        protocol = 'HTTPS' if ssl_context else 'HTTP'
        log('INFO', 'App', f'使用 run_simple（{protocol} 模式）')
        run_simple(
            '0.0.0.0', port, wrapped_app,
            threaded=True, ssl_context=ssl_context,
        )
        return

    log('INFO', 'App', '使用 Cheroot 服务器')
    from routes.firewall import firewall, FirewallServer
    server = FirewallServer(
        ('0.0.0.0', port),
        wrapped_app,
        request_queue_size=100,
        numthreads=20,
    )
    _server = server
    # 启动高性能防火墙（黑名单镜像同步 + DDoS 检测 + 黑名单连接强制关闭）
    firewall.attach_server(server)
    firewall.start_monitor()

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
                'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS',
            )
            ctx.session_stats()
            server.ssl_adapter.context = ctx
        except ImportError as e:
            log('WARNING', 'App', f'无法加载 SSL 适配器 ({e})，回退到 HTTP 模式')
            log('WARNING', 'App', f'HTTP 模式运行 (端口 {port})')
    else:
        log('INFO', 'App', f'HTTP 模式运行 (端口 {port})')

    try:
        server.start()
    except KeyboardInterrupt:
        shutdown_application(signal.SIGINT)
    except Exception as e:
        log('ERROR', 'App', f'服务器启动失败: {e}')
        raise
    finally:
        shutdown_application()