import os
import socket
from flask import Flask, render_template, abort

from config import SECRET_KEY, MAX_CONTENT_LENGTH
from core.database import init_db
from core.middleware import log_access
from routes.main import main_bp
from routes.community import community_bp
from routes.admin import admin_bp
from routes.api import monitoring_bp, stats_bp, polls_bp, admin_api_bp
from routes.cmd import cmd_bp
from routes.scheduled import scheduled_bp
from routes.docs import docs_bp
from services.scheduler import scheduler
from services.log_cleaner import log_cleaner
from services.log_writer import log_writer
from services.backup_scheduler import BackupScheduler


def is_port_in_use(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = True

init_db()

app.before_request(log_access)

# 启动后台服务（异步线程）
log_writer.start()
log_cleaner.start()
scheduler.start()
BackupScheduler().start()

app.register_blueprint(main_bp)
app.register_blueprint(community_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(monitoring_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(polls_bp)
app.register_blueprint(admin_api_bp)
app.register_blueprint(cmd_bp)
app.register_blueprint(scheduled_bp)
app.register_blueprint(docs_bp)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


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
