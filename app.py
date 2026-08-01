import os
import sys
import signal
import socket
from flask import Flask, render_template, abort
from config import SECRET_KEY, MAX_CONTENT_LENGTH


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


# ---------------------------------------------------------------------------
# 蓝图注册
# ---------------------------------------------------------------------------

def _register_blueprints():
    """注册所有蓝图。"""
    from routes.main import main_bp
    from routes.community import community_bp
    from routes.admin import admin_bp
    from routes.api import api_bp, admin_api_bp, captcha_bp, email_code_bp
    from routes.cmd import cmd_bp
    from routes.scheduled import scheduled_bp
    from routes.docs import docs_bp
    from routes.guides import guides_bp
    from routes.discussion import discussion_bp
    from routes.public_files import public_bp, try_serve_public

    blueprints = [
        public_bp, main_bp, community_bp, admin_bp,
        api_bp, admin_api_bp, captcha_bp, email_code_bp,
        cmd_bp, scheduled_bp, docs_bp, guides_bp, discussion_bp,
    ]
    for bp in blueprints:
        app.register_blueprint(bp)
    print(f'[INFO] 蓝图注册完成，共 {len(blueprints)} 个', flush=True)

    return try_serve_public


# ---------------------------------------------------------------------------
# 请求钩子
# ---------------------------------------------------------------------------

def _register_hooks(try_serve_public):
    """注册 before_request 钩子。"""
    from core.middleware import log_access

    @app.before_request
    def serve_public_files_hook():
        from flask import request
        from werkzeug.exceptions import HTTPException
        path = request.path
        if path.startswith('/static/') or path.startswith('/admin') or \
           path.startswith('/api/') or path.startswith('/cmd/') or \
           path.startswith('/scheduled') or path.startswith('/community') or \
           path.startswith('/docs') or path in ('/login', '/register', '/logout',
                                                '/settings', '/performance'):
            return None
        try:
            resp = try_serve_public(path.lstrip('/'))
            if resp is not None:
                return resp
        except HTTPException:
            raise
        except Exception:
            pass
        return None

    app.before_request(log_access)


# ---------------------------------------------------------------------------
# 后台服务
# ---------------------------------------------------------------------------

def _start_background_services():
    """启动所有后台服务。"""
    from services.scheduler import scheduler
    from services.logging import log_cleaner, log_writer
    from services.backup import BackupScheduler
    from services.email import email_service

    log_writer.start()
    log_cleaner.start()
    scheduler.start()
    BackupScheduler().start()
    email_service.start()
    print('[INFO] 后台服务启动完成', flush=True)


# ---------------------------------------------------------------------------
# 应用初始化
# ---------------------------------------------------------------------------

def _init_app():
    """初始化应用：数据库、蓝图、钩子、后台服务。仅在主进程执行。"""
    from core.db import init_db

    print('[INFO] 正在初始化数据库...', flush=True)
    init_db()
    print('[INFO] 数据库初始化完成', flush=True)

    print('[INFO] 正在注册蓝图...', flush=True)
    try_serve_public = _register_blueprints()

    _register_hooks(try_serve_public)

    print('[INFO] 正在启动后台服务...', flush=True)
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
    from cheroot.wsgi import Server

    print(f'[INFO] 工作目录: {os.getcwd()}', flush=True)
    print(f'[INFO] APP_ROOT: {os.path.dirname(os.path.abspath(__file__))}', flush=True)

    if is_port_in_use(port):
        print(f'[ERROR] 端口 {port} 已被占用，请先关闭其他程序', flush=True)
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

    if has_ssl:
        print(f'[INFO] HTTPS 模式运行 (端口 {port})', flush=True)
        print(f'[INFO]   证书: {cert_path}', flush=True)
        print(f'[INFO]   私钥: {key_path}', flush=True)
        try:
            from cheroot.ssl.builtin import BuiltinSSLAdapter
            server.ssl_adapter = BuiltinSSLAdapter(
                certificate=cert_path,
                private_key=key_path,
            )
        except ImportError as e:
            print(f'[WARNING] 无法加载 SSL 适配器 ({e})，回退到 HTTP 模式', flush=True)
            print(f'[WARNING] HTTP 模式运行 (端口 {port})', flush=True)
    else:
        print(f'[WARNING] 未找到 SSL 证书文件 ({cert_path} 或 {key_path})', flush=True)
        print(f'[WARNING] 回退到 HTTP 模式运行 (端口 {port})', flush=True)

    try:
        server.start()
    except KeyboardInterrupt:
        print('\n[INFO] 服务器已停止', flush=True)
    except Exception as e:
        print(f'[ERROR] 服务器启动失败: {e}', flush=True)
        raise


# ---------------------------------------------------------------------------
# 优雅关闭
# ---------------------------------------------------------------------------

def _graceful_shutdown(signum, frame):
    """收到终止信号时优雅关闭服务器。"""
    print(f'\n[INFO] 收到信号 {signum}，正在关闭服务器...', flush=True)
    from services.logging import log_writer, log_cleaner
    from services.scheduler import scheduler
    from core.db import get_db

    log_writer.stop()
    log_cleaner.stop()
    scheduler.stop()
    try:
        conn = get_db()
        conn.commit()
    except Exception:
        pass
    print('[INFO] 服务器已关闭', flush=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


if __name__ == '__main__':
    run_server(5000)