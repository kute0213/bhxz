import os
import sys
import signal
from flask import Flask
import config
from core.init import init_app
from core.server import register_error_handlers, run_server, graceful_shutdown
from core.logger import log


# 项目根目录
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

from datetime import timedelta

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = os.environ.get('FLASK_ENV') == 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('ENABLE_SSL', '0').lower() in ('1', 'true', 'yes', 'on')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=config.SESSION_LIFETIME)


# ---------------------------------------------------------------------------
# 应用初始化
# ---------------------------------------------------------------------------

if not _is_child:
    init_app(app, _APP_ROOT)


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

register_error_handlers(app)


# ---------------------------------------------------------------------------
# 信号处理
# ---------------------------------------------------------------------------

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    run_server(app, port=5000, app_root=_APP_ROOT)