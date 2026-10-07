"""WSGI 服务器 —— 启动、关闭、优雅退出。"""

import os
import socket
import signal
import threading

from core.system.logger import log, log_fatal, install_waitress_logging

_server = None
_shutdown_started = False
_shutdown_lock = threading.Lock()

# 工作线程数：0 表示不限制时，按下面的范围智能推算
_DEFAULT_THREADS = 100
_MIN_AUTO_THREADS = 32
_MAX_AUTO_THREADS = 512


def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def resolve_thread_count(max_threads=None):
    """把「工作线程数」设置解析为 Waitress 实际工作线程数。

    - ``max_threads > 0``：直接使用该值（用户显式设定了上限）
    - ``max_threads == 0``：不限制，按 CPU 核数与可用内存智能推算
    """
    if max_threads is None:
        try:
            from config import WAITRESS_THREADS
            max_threads = WAITRESS_THREADS
        except Exception:
            max_threads = _DEFAULT_THREADS

    try:
        max_threads = int(max_threads)
    except (TypeError, ValueError):
        max_threads = _DEFAULT_THREADS

    if max_threads > 0:
        return max(1, max_threads)

    # 0 = 不限制：按 CPU 核数与可用内存智能推算
    cpu = os.cpu_count() or 4
    smart = max(_MIN_AUTO_THREADS, cpu * 16)
    try:
        import psutil
        avail_mb = psutil.virtual_memory().available // (1024 * 1024)
        # 每个工作线程预留约 4MB（线程栈 + 请求缓冲），据此设内存上限
        smart = min(smart, max(_MIN_AUTO_THREADS, avail_mb // 4))
    except Exception:
        pass
    return max(_MIN_AUTO_THREADS, min(int(smart), _MAX_AUTO_THREADS))


def get_configured_threads():
    """读取当前设置中的工作线程数（数据库优先，回退 config.py 默认值）。"""
    from config import WAITRESS_THREADS
    try:
        from config import get_config_value
        return int(get_config_value('WAITRESS_THREADS', WAITRESS_THREADS))
    except Exception:
        return int(WAITRESS_THREADS)


def apply_thread_count():
    """热加载工作线程数（设置变更后调用，无需重启服务器）。

    Returns:
        实际生效的线程数；服务器未启动时返回 None。
    """
    if _server is None:
        return None
    try:
        count = resolve_thread_count(get_configured_threads())
        _server.task_dispatcher.set_thread_count(count)
        log('INFO', 'App', f'工作线程数已热加载为 {count}')
        return count
    except Exception as exc:
        log('WARNING', 'App', f'工作线程数热加载失败: {exc}')
        return None


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

    threads = resolve_thread_count(get_configured_threads())
    server = create_server(
        wrapped_app,
        host='0.0.0.0',
        port=port,
        threads=threads,
        connection_limit=1000,
        channel_timeout=300,
        asyncore_use_poll=True,
        # Waitress 3.x 默认会剥离「不可信来源」的代理头（X-Forwarded-For /
        # X-Forwarded-Proto / X-Real-IP 等）。内网穿透与反向代理正是靠这些头
        # 传递客户端真实 IP 与原始协议，被剥离后 REMOTE_ADDR 恒为回环地址，
        # 导致 DDoS 统计/封禁与 Session Cookie 的 Secure 判断全部失效。
        # 这里交回应用自行判断：core.shared.ip.is_trusted_proxy 只采信回环/
        # 内网/TRUSTED_PROXIES 转发的头，公网直连伪造的头一律忽略。
        clear_untrusted_proxy_headers=False,
    )
    _server = server

    # 启动高性能防火墙（黑名单镜像同步 + DDoS 检测后台线程）
    firewall.start_monitor()
    log('INFO', 'App', f'使用 Waitress 服务器，HTTP 模式运行 (端口 {port})')
    log('INFO', 'App', f'Waitress 工作线程数: {threads}')

    try:
        server.run()
    except KeyboardInterrupt:
        shutdown_application(signal.SIGINT)
    except Exception as e:
        log_fatal('CRITICAL', 'App', '服务器启动失败，进程退出', error=str(e))
        raise
    finally:
        shutdown_application()
