from flask import request
from services.ip import get_client_ip, get_ip_info
from services.log_writer import log_writer
from core.auth import get_current_user

SKIP_PATHS = ('/static/', '/favicon.ico', '/uploads/',
              '/api/admin/logs/refresh', '/api/performance')


def log_access():
    """记录访问日志（非阻塞）。

    IP 信息查询使用缓存，不阻塞请求；
    日志写入通过队列异步完成，不阻塞请求；
    日志清理由 log_cleaner 后台线程定期执行。
    """
    if any(request.path.startswith(p) for p in SKIP_PATHS):
        return

    try:
        ip = get_client_ip()
        ip_info = get_ip_info(ip)
        user = get_current_user()

        log_writer.enqueue({
            'ip_address': ip,
            'country': ip_info['country'],
            'region': ip_info['region'],
            'city': ip_info['city'],
            'isp': ip_info['isp'],
            'user_id': user['id'] if user else None,
            'username': user['username'] if user else None,
            'path': request.path,
            'method': request.method,
            'user_agent': request.headers.get('User-Agent', '')[:500],
        })
    except Exception:
        pass
