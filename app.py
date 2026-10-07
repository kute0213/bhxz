import os
import sys
import signal
from flask import Flask
import config
from core.system.init import init_app
from core.server import run_server, graceful_shutdown
from core.errors import register_error_handlers



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

from flask.sessions import SecureCookieSessionInterface


class _ProxyAwareSessionInterface(SecureCookieSessionInterface):
    """Session Cookie 的 Secure 标志按「客户端原始协议」动态决定。

    当前 HTTPS 由内网穿透 / 反向代理在进入 Flask 之前终结，应用自身始终以
    HTTP 对外监听，Flask 侧看到的协议恒为 http（request.is_secure 恒为
    False）。因此既不能把 Secure 写死为 True（纯 HTTP 直连会因浏览器不回传
    Secure Cookie 而丢失登录态），也不能直接依赖 request.is_secure。
    这里改为读取可信代理写入的 X-Forwarded-Proto：原始协议是 https 时
    才给 Session Cookie 加 Secure。
    """

    @staticmethod
    def _original_proto():
        from flask import request
        from core.shared.ip import is_trusted_proxy
        # 仅采信可信代理（回环 / 内网 / TRUSTED_PROXIES）写入的协议头，
        # 公网直连忽略，避免伪造 X-Forwarded-Proto 影响 Cookie 属性
        if not is_trusted_proxy(request.remote_addr):
            return ''
        proto = (request.headers.get('X-Forwarded-Proto') or '').strip()
        # 形如 "https,http" 的链路取最左侧（最靠近客户端）的协议
        return proto.split(',')[0].strip().lower()

    def get_cookie_secure(self, app):
        proto = self._original_proto()
        if proto:
            return proto == 'https'
        from flask import request
        return bool(request.is_secure)


app = Flask(__name__, static_folder='templates/static')
app.secret_key = config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = os.environ.get('FLASK_ENV') == 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Session Cookie 的 Secure 由 _ProxyAwareSessionInterface 按原始协议动态决定：
# 穿透 / 反代以 HTTPS 对外时自动开启，本地 HTTP 直连时自动关闭
app.session_interface = _ProxyAwareSessionInterface()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=config.SESSION_LIFETIME)


# ---------------------------------------------------------------------------
# 应用初始化
# ---------------------------------------------------------------------------

if not _is_child:
    # 应用初始化：数据库 → 蓝图 → 中间件 → 后台服务
    try:
        init_app(app, _APP_ROOT)
    except Exception as e:
        import traceback
        from core.system.logger import log_fatal
        log_fatal('CRITICAL', 'App', '应用初始化失败，服务器退出', error=str(e))
        print(f'[FATAL] 应用初始化失败: {e}', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise


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