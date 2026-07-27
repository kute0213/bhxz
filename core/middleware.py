from flask import request, session
from services.ip import get_client_ip, get_ip_info
from services.log_writer import log_writer

SKIP_PATHS = ('/static/', '/favicon.ico', '/uploads/',
              '/api/admin/logs/refresh', '/api/performance')


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
