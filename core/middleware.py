"""请求中间件 —— 访问日志记录、公共文件服务、请求钩子注册。

设计原则：所有请求钩子在此模块集中管理，避免在 app.py 中散落。
"""

from flask import request, session
from werkzeug.exceptions import HTTPException

from services.ip import get_client_ip, get_ip_info
from services.logging import log_writer

# 跳过日志记录的路径前缀
SKIP_PATHS = ('/static/', '/favicon.ico', '/uploads/',
              '/api/admin/logs/refresh', '/api/performance')

# 跳过公共文件服务的路径前缀（这些路径由 Flask 蓝图处理）
ROUTE_PREFIXES = (
    '/static/', '/admin', '/api/', '/cmd/',
    '/scheduled', '/community', '/docs',
    '/login', '/register', '/logout', '/settings', '/performance',
)


def register_hooks(app, try_serve_public):
    """注册所有请求钩子。

    Args:
        app: Flask 应用实例
        try_serve_public: 公共文件服务函数（由 routes.public 提供）
    """

    @app.before_request
    def serve_public_files_hook():
        """优先检查公共静态文件，避免与蓝图路由冲突。"""
        path = request.path
        if path.startswith(ROUTE_PREFIXES):
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


def log_access():
    """记录访问日志（非阻塞）。

    IP 信息查询使用缓存，不阻塞请求；
    日志写入通过队列异步完成，不阻塞请求；
    用户信息直接从 session 读取，避免每次请求都查库。
    日志清理由 log_cleaner 后台线程定期执行。
    """
    if any(request.path.startswith(p) for p in SKIP_PATHS):
        return

    try:
        ip = get_client_ip()
        ip_info = get_ip_info(ip)

        # 直接从 session 读取用户信息（登录时已设置），无需查库
        user_id = session.get('user_id')
        username = session.get('username')

        log_writer.enqueue({
            'ip_address': ip,
            'country': ip_info['country'],
            'region': ip_info['region'],
            'city': ip_info['city'],
            'isp': ip_info['isp'],
            'user_id': user_id,
            'username': username,
            'path': request.path,
            'method': request.method,
            'user_agent': request.headers.get('User-Agent', '')[:500],
        })
    except Exception:
        pass