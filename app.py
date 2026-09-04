import os
import sys
import signal
import socket
import threading
from flask import Flask, render_template
from config import SECRET_KEY, MAX_CONTENT_LENGTH
from core.logger import log


# 项目根目录（确保工作目录正确，不受快捷方式启动影响）
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# multiprocessing 子进程检测 —— 必须在任何其他导入之前执行
# ---------------------------------------------------------------------------

def _set_child_env():
    os.environ['_BH_CHILD_PROCESS'] = '1'


def _is_mp_spawn_child():
    """检测当前进程是否是 multiprocessing spawn/forkserver 启动的子进程。"""
    if os.environ.get('_BH_CHILD_PROCESS') == '1':
        return True
    if globals().get('__name__') == '__mp_main__':
        _set_child_env()
        return True
    try:
        argv_str = ' '.join(sys.argv).lower()
        if '--multiprocessing-fork' in argv_str:
            _set_child_env()
            return True
        if '-c' in argv_str and 'spawn_main' in argv_str:
            _set_child_env()
            return True
        if 'multiprocessing' in argv_str and ('spawn' in argv_str or 'fork' in argv_str):
            _set_child_env()
            return True
    except Exception:
        pass
    return False


_is_child = _is_mp_spawn_child()


# ---------------------------------------------------------------------------
# Flask 应用
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = os.environ.get('FLASK_ENV') == 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# HTTPS 环境下启用 Secure 标志，防止会话 Cookie 被中间人劫持
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('ENABLE_SSL', '0').lower() in ('1', 'true', 'yes', 'on')

# Cheroot 实例必须在信号处理函数中显式 stop，否则其工作线程会阻止 Python 退出。
_server = None
_shutdown_started = False
_shutdown_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 请求钩子
# ---------------------------------------------------------------------------

def _register_hooks(try_serve_public):
    """统一注册请求钩子。"""
    log('INFO', 'App', '正在注册请求钩子...')
    from core.middleware import register_hooks
    register_hooks(app, try_serve_public)


# ---------------------------------------------------------------------------
# 后台服务
# ---------------------------------------------------------------------------

def _register_template_context():
    """注册模板上下文处理器，使全局配置在所有模板中可用。"""
    from config import get_config_value
    from flask import session
    from services import background_service
    from core.csrf import get_csrf_token
    from markupsafe import Markup

    @app.context_processor
    def inject_global_config():
        # 获取已启用的背景图片，根据屏幕宽度选择最合适的图片
        # 我们在模板中根据屏幕尺寸选择，这里简单取第一个
        active_bgs = background_service.get_active_backgrounds()

        # CSRF 模板辅助函数
        def csrf_field():
            token = get_csrf_token()
            return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')

        def csrf_token_str():
            return get_csrf_token()

        return {
            # 登录欢迎语只展示一次，避免刷新页面后重复打扰用户。
            'login_welcome_username': session.pop('login_welcome_username', None),
            'active_backgrounds': active_bgs,
            'csrf_field': csrf_field,
            'csrf_token': csrf_token_str,
            # 备案号（热重载）
            'show_beian': get_config_value('SHOW_BEIAN', False),
            'icp_beian': get_config_value('ICP_BEIAN', ''),
            'police_beian': get_config_value('POLICE_BEIAN', ''),
            'copyright_year': get_config_value('COPYRIGHT_YEAR', '2024'),
            'copyright_site_name': get_config_value('COPYRIGHT_SITE_NAME', '滨海小镇'),
        }


def _start_background_services():
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





# ---------------------------------------------------------------------------
# 启动迁移
# ---------------------------------------------------------------------------

def _run_pending_migrations():
    """检查并执行标记为待处理的清理与迁移脚本。

    在 init_db() 之前执行，此时服务器尚未打开数据库连接，无锁冲突。
    子进程内会自行初始化数据库连接。
    一键更新在 updater.py 中设置 UPLOADS_MIGRATION_PENDING=1 标记，
    重启后在此处执行，避免在服务器运行中直接操作数据库导致锁冲突。
    """
    try:
        from services.settings_manager import get_setting, set_setting
        if get_setting('UPLOADS_MIGRATION_PENDING', '0') != '1':
            return

        log('INFO', 'App', '检测到待执行的清理与迁移任务，正在运行...')
        uploads_script = os.path.join(_APP_ROOT, 'scripts', 'uploads.py')
        if not os.path.isfile(uploads_script):
            log('WARNING', 'App', 'scripts/uploads.py 不存在，跳过迁移')
            try:
                set_setting('UPLOADS_MIGRATION_PENDING', '0')
            except Exception:
                pass
            return

        import subprocess
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

        # 清除标记，避免下次启动重复执行
        try:
            set_setting('UPLOADS_MIGRATION_PENDING', '0')
        except Exception:
            pass
    except Exception as e:
        log('WARNING', 'App', f'执行清理与迁移失败: {e}')


# ---------------------------------------------------------------------------
# 应用初始化
# ---------------------------------------------------------------------------

def _init_app():
    """初始化应用：数据库、蓝图、钩子、后台服务。仅在主进程执行。"""
    from core.db import init_db

    # 确保工作目录始终是项目根目录（避免快捷方式启动时跑到桌面）
    os.chdir(_APP_ROOT)

    # 检查是否有待执行的清理与迁移脚本（由一键更新标记）
    # 在 init_db() 之前执行，此时服务器尚未打开数据库连接，无锁冲突
    _run_pending_migrations()

    log('INFO', 'App', '正在初始化数据库...')
    init_db()
    log('INFO', 'App', '数据库初始化完成')

    log('INFO', 'App', '正在注册蓝图...')
    from routes.registry import register_blueprints
    try_serve_public = register_blueprints(app)

    _register_hooks(try_serve_public)

    # 注册模板上下文处理器
    _register_template_context()

    log('INFO', 'App', '正在启动后台服务...')
    _start_background_services()


if not _is_child:
    _init_app()


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


# ---------------------------------------------------------------------------
# WSGI 服务器
# ---------------------------------------------------------------------------

def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def run_server(port=5000):
    """使用 Cheroot 作为 WSGI 服务器，可选 SSL。"""
    global _server
    from cheroot.wsgi import Server

    log('INFO', 'App', f'工作目录: {os.getcwd()}')
    log('INFO', 'App', f'APP_ROOT: {os.path.dirname(os.path.abspath(__file__))}')

    if is_port_in_use(port):
        log('ERROR', 'App', f'端口 {port} 已被占用，请先关闭其他程序')
        return

    ssl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ssl')
    key_path = os.path.join(ssl_dir, 'private.key')
    cert_path = os.path.join(ssl_dir, 'fullchain.pem')

    enable_ssl = os.environ.get('ENABLE_SSL', '0').lower() in ('1', 'true', 'yes', 'on')
    has_ssl = enable_ssl and os.path.isfile(key_path) and os.path.isfile(cert_path)

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
            )
        except ImportError as e:
            log('WARNING', 'App', f'无法加载 SSL 适配器 ({e})，回退到 HTTP 模式')
            log('WARNING', 'App', f'HTTP 模式运行 (端口 {port})')
    else:
        log('WARNING', 'App', f'未找到 SSL 证书文件 ({cert_path} 或 {key_path})')
        log('WARNING', 'App', f'回退到 HTTP 模式运行 (端口 {port})')

    try:
        server.start()
    except KeyboardInterrupt:
        # 未安装信号处理器的嵌入式运行场景仍需要进入统一关闭流程。
        _shutdown_application(signal.SIGINT)
    except Exception as e:
        log('ERROR', 'App', f'服务器启动失败: {e}')
        raise
    finally:
        _shutdown_application()


# ---------------------------------------------------------------------------
# 优雅关闭
# ---------------------------------------------------------------------------

def _shutdown_application(signum=None):
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

    # 先停止接收新请求，Cheroot 会关闭监听 socket 并回收工作线程。
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
    # 日志写入器最后停止，尽量落下其他服务关闭过程中产生的日志。
    log_writer.stop()
    try:
        conn = get_db()
        conn.commit()
    except Exception as exc:
        log('WARNING', 'App', f'关闭前提交数据库失败: {exc}')
    log('INFO', 'App', '服务器已关闭')


def _graceful_shutdown(signum, frame):
    """收到终止信号时触发统一关闭流程。"""
    # 不在 Python 信号回调栈内同步 join Cheroot 工作线程，否则 Windows 下
    # 可能因主线程仍停留在 serve() 中而互相等待。独立线程完成实际回收。
    shutdown_thread = threading.Thread(
        target=_shutdown_application,
        args=(signum,),
        name='app-shutdown',
        daemon=False,
    )
    shutdown_thread.start()


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


if __name__ == '__main__':
    run_server(5000)
