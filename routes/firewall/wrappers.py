"""防火墙 WSGI 门禁 —— 在进入 Flask 前直接断开封禁 IP 连接。

职责：
  1. WSGI 级黑名单拦截：被封 IP 的连接直接断开 socket，不产生任何 HTTP 响应
  2. 登记活跃连接（供监控线程追踪连接状态）
  3. DDoS 请求计数（超阈值自动封禁）

设计原则：
  - 被封 IP 的请求在 WSGI 层直接断开，不进入 Flask 处理管道
  - 除 DDOS 计数外，不产生任何日志/数据库/内存分配开销
  - 线程安全：多线程下每请求独立调用 __call__，无共享状态竞争
"""

import weakref

from routes.firewall.database import push_ban_context


class FirewallWSGIWrapper:
    """WSGI 包装器：黑名单快速断开 + 连接登记 + DDoS 计数。

    被封 IP 的连接在 __call__ 中被识别后立即关闭底层 socket，
    不调用 Flask 应用，不产生 HTTP 响应——从 TCP 层面断开。

    用法：
        wrapper = FirewallWSGIWrapper(wsgi_app, firewall_instance)
        server = FirewallServer(..., wrapper)
    """

    def __init__(self, wsgi_app, firewall_instance):
        self._app = wsgi_app
        self._fw = firewall_instance
        self._ddos_detector = None

    @property
    def ddos_detector(self):
        if self._ddos_detector is None:
            from routes.firewall.ddos import DDoSDetector
            self._ddos_detector = DDoSDetector()
            self._fw._ddos_detector = self._ddos_detector
        return self._ddos_detector

    def __call__(self, environ, start_response):
        ip = environ.get('REMOTE_ADDR') or ''

        if ip:
            if ip in ('127.0.0.1', '::1', 'localhost'):
                return self._app(environ, start_response)

            # 黑名单拦截：直接断开连接，不返回任何 HTTP 响应
            if self._fw.is_banned(ip):
                self._close_connection(environ)
                return self._empty_response(start_response)

            # 登记活跃连接
            conn = environ.get('cheroot.connection')
            if conn is not None:
                self._track_connection(conn)

            # DDoS 计数 — 先推送请求上下文，供 ban_ip 自动记录封禁详情
            from config import get_config_value
            enabled = get_config_value('DDOS_GUARD_ENABLED', True)
            intensity = str(
                get_config_value('DDOS_GUARD_INTENSITY', 'medium') or 'medium'
            ).lower()
            path = environ.get('PATH_INFO') or ''
            push_ban_context(
                request_path=path,
                request_method=environ.get('REQUEST_METHOD', ''),
                user_agent=environ.get('HTTP_USER_AGENT', ''),
                referer=environ.get('HTTP_REFERER', ''),
                query_string=environ.get('QUERY_STRING', ''),
                action_ip=ip,
            )
            self.ddos_detector.record(ip, path, enabled, intensity)

        return self._app(environ, start_response)

    def _close_connection(self, environ):
        """通过 Cheroot 连接对象关闭底层连接，避免 HTTP 响应产生。"""
        conn = environ.get('cheroot.connection')
        if conn is not None:
            conn.linger = False
            conn.close()

    @staticmethod
    def _empty_response(start_response):
        """返回完全空的 HTTP 响应——无内容、无额外头、关连接。

        这是 WSGI 协议下的最小可行响应；真正的断开由 _close_connection
        在更高层已完成，此处仅为让 WSGI 服务器不要继续等待而发送的最后哨兵。
        """
        start_response('403 Forbidden', [('Connection', 'close')])
        return []

    def _track_connection(self, conn):
        """登记活跃连接（弱引用）。"""
        fw = self._fw
        if not hasattr(fw, '_conns') or fw._conns is None:
            fw._conns = {}
        fw._conns[id(conn)] = weakref.ref(conn)