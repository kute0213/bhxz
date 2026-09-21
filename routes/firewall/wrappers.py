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
from routes.firewall.connection_filter import _check_ipv6_block


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

            # IPv6 拦截：检查是否为 IPv6 连接且开启了拦截
            if ip and ':' in ip and ip != '::1':
                from routes.firewall.connection_filter import _check_ipv6_block
                _check_ipv6_block(ip, lambda ip_addr: self._close_connection(environ))

            # 1) 黑名单拦截：直接断开连接，不返回任何 HTTP 响应
            if self._fw.is_banned(ip):
                self._close_connection(environ)
                return self._empty_response(start_response)

            # 2) 登记活跃连接
            conn = environ.get('cheroot.connection')
            if conn is not None:
                self._track_connection(conn)

            # 3) DDoS 计数 — 先推送请求上下文，供 ban_ip 自动记录封禁详情
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
        """尝试在 WSGI 层关闭底层连接，避免 HTTP 响应产生。

        优先关闭 Cheroot 连接对象（连接级关闭，最彻底）；
        无 Cheroot 时尝试关闭 werkzeug 的原始 socket。
        """
        # 方案 A：通过 cheroot.connection 关闭
        conn = environ.get('cheroot.connection')
        if conn is not None:
            try:
                conn.linger = False
                conn.close()
                return
            except Exception:
                pass

        # 方案 B：werkzeug 环境，尝试关闭原始 socket
        try:
            sock = environ.get('werkzeug.socket')
            if sock is not None:
                sock.shutdown(2)  # SHUT_RDWR
                sock.close()
                return
        except Exception:
            pass

        # 方案 C：通过 wsgi.input 的 raw 流拿到 socket（run_simple 下有用）
        try:
            wsgi_input = environ.get('wsgi.input')
            if wsgi_input is not None:
                raw = getattr(wsgi_input, 'raw', None) or getattr(wsgi_input, '_sock', None)
                if raw is not None:
                    raw.shutdown(2)
                    raw.close()
                    return
        except Exception:
            pass

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
        try:
            fw._conns[id(conn)] = weakref.ref(conn)
        except Exception:
            pass