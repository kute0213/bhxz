"""防火墙 WSGI 门禁 —— 在进入 Flask 前进行二次拦截与 DDoS 计数。

职责：
  1. WSGI 级黑名单拦截兜底（即使连接过滤器因竞态漏过，在此处拦截）
  2. 登记活跃连接（供监控线程追踪）
  3. DDoS 请求计数（超阈值自动封禁）
"""

import weakref

from core.system.logger import log


class FirewallWSGIWrapper:
    """WSGI 包装器：黑名单快速拦截 + 连接登记 + DDoS 计数。

    用法：
        wrapper = FirewallWSGIWrapper(wsgi_app, firewall_instance)
        # 传入 CherootServer 或 Flask run_simple
        server = FirewallServer(..., wrapper)

    同时也是可调用对象（WSGI 应用），直接传入 server 或 run_simple。
    """

    def __init__(self, wsgi_app, firewall_instance):
        self._app = wsgi_app
        self._fw = firewall_instance
        # DDoS 检测器（延迟导入避免循环依赖）
        self._ddos_detector = None

    @property
    def ddos_detector(self):
        if self._ddos_detector is None:
            from core.firewall.ddos import DDoSDetector
            self._ddos_detector = DDoSDetector()
            # 绑定到 firewall 实例，供监控线程访问
            self._fw._ddos_detector = self._ddos_detector
        return self._ddos_detector

    def __call__(self, environ, start_response):
        ip = environ.get('REMOTE_ADDR') or ''

        if ip:
            # 内置安全 IP（127.0.0.1、::1）跳过所有防火墙检查
            if ip in ('127.0.0.1', '::1', 'localhost'):
                return self._app(environ, start_response)

            # 1) 黑名单拦截兜底
            if self._fw.is_banned(ip):
                conn = environ.get('cheroot.connection')
                if conn is not None:
                    try:
                        conn.linger = False
                        conn.close()
                    except Exception:
                        pass
                start_response(
                    '403 Forbidden',
                    [
                        ('Content-Type', 'text/plain; charset=utf-8'),
                        ('Content-Length', '0'),
                        ('Connection', 'close'),
                        ('X-Firewall', '1'),
                    ],
                )
                return [b'']

            # 2) 登记活跃连接
            conn = environ.get('cheroot.connection')
            if conn is not None:
                self._track_connection(conn)

            # 3) DDoS 计数
            from config import get_config_value
            enabled = get_config_value('DDOS_GUARD_ENABLED', True)
            intensity = str(
                get_config_value('DDOS_GUARD_INTENSITY', 'medium') or 'medium'
            ).lower()
            path = environ.get('PATH_INFO') or ''
            self.ddos_detector.record(ip, path, enabled, intensity)

        return self._app(environ, start_response)

    def _track_connection(self, conn):
        """登记活跃连接（弱引用）。"""
        fw = self._fw
        if not hasattr(fw, '_conns') or fw._conns is None:
            fw._conns = {}
        try:
            fw._conns[id(conn)] = weakref.ref(conn)
        except Exception:
            pass