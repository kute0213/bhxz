import os
import sys


def _set_child_env():
    """标记当前进程为 multiprocessing 子进程。"""
    os.environ['_BH_CHILD_PROCESS'] = '1'


def _is_mp_spawn_child():
    """检测当前进程是否是 multiprocessing spawn/forkserver 启动的子进程。

    此函数必须在所有其他导入和业务逻辑之前调用，以确保子进程不会
    尝试初始化数据库或启动后台服务。

    检测策略（按优先级）：
    1. 环境变量 _BH_CHILD_PROCESS=1 已被设置
    2. __name__ == '__mp_main__'（fork 模式）
    3. sys.argv 包含 multiprocessing spawn 特征（-c + spawn_main / --multiprocessing-fork）
    """
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


import socket
from flask import Flask, render_template, abort

from config import SECRET_KEY, MAX_CONTENT_LENGTH


app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Session Cookie 安全选项：防止 JS 读取 Cookie、限制跨站携带
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


def _init_app():
    """初始化应用：数据库、后台服务、蓝图注册。仅在主进程执行。"""
    from core.db import init_db
    from core.middleware import log_access
    from routes.main import main_bp
    from routes.community import community_bp
    from routes.admin import admin_bp
    from routes.api import monitoring_bp, stats_bp, polls_bp, admin_api_bp, captcha_bp, email_code_bp
    from routes.cmd import cmd_bp
    from routes.scheduled import scheduled_bp
    from routes.docs import docs_bp
    from routes.guides import guides_bp
    from routes.public_files import public_bp, try_serve_public
    from services.scheduler import scheduler
    from services.logging import log_cleaner, log_writer
    from services.backup import BackupScheduler
    from services.email import email_service

    init_db()

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

    log_writer.start()
    log_cleaner.start()
    scheduler.start()
    BackupScheduler().start()
    email_service.start()

    app.register_blueprint(public_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(polls_bp)
    app.register_blueprint(admin_api_bp)
    app.register_blueprint(captcha_bp)
    app.register_blueprint(email_code_bp)
    app.register_blueprint(cmd_bp)
    app.register_blueprint(scheduled_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(guides_bp)


if not _is_child:
    _init_app()


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def run_server(port=5000):
    """使用 CherryPy 作为 WSGI 服务器，支持 SSL 证书。

    若 ./ssl/private.key 与 ./ssl/fullchain.pem 存在则启用 HTTPS，
    否则打印警告并以 HTTP 模式继续运行。
    """
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


if __name__ == '__main__':
    run_server(5000)
