"""防火墙 WSGI 门禁 —— 在进入 Flask 前直接断开封禁 / 被拦截 IP 的连接。

职责：
  1. WSGI 级黑名单拦截：被封 IP 的连接直接断开，不产生任何 HTTP 响应
  2. IPv6 拦截：开启开关后断开除本地回环外的 IPv6 连接
  3. DDoS 请求计数（超阈值自动封禁）

设计原则：
  - 被拦截的请求在 WSGI 层直接断开，不进入 Flask 处理管道，不写任何字节
  - 除 DDoS 计数外，不产生任何日志/数据库/内存分配开销
  - 线程安全：多线程下每请求独立调用 __call__，无共享状态竞争

断开方式（waitress）：
  应用抛出 ``waitress.channel.ClientDisconnected`` 时，waitress 的
  ``HTTPChannel.service`` 会捕获它并标记「响应完成后关闭连接」，
  此时尚未调用 start_response、未写出任何响应头与响应体，因此客户端
  读到 0 字节后连接断开，等价于「直接断开、不返回任何数据」。
"""

from core.shared.ip import resolve_ip_from_environ
from services.firewall.service.database import push_ban_context

# 本机回环地址：只有确实来自本机（且无代理头部）的请求才会解析为此值，
# 这类请求不做 DDoS 计数，避免健康检查 / 本机监控被误判。
_LOCAL_IPS = frozenset({'127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1'})


class FirewallWSGIWrapper:
    """WSGI 包装器：黑名单 / IPv6 快速断开 + DDoS 计数。

    被封 IP 的连接在 __call__ 中被识别后立即断开，
    不调用 Flask 应用，不产生任何 HTTP 响应数据。

    用法：
        wrapper = FirewallWSGIWrapper(wsgi_app, firewall_instance)
        server = waitress.create_server(wrapper, ...)
    """

    def __init__(self, wsgi_app, firewall_instance):
        self._app = wsgi_app
        self._fw = firewall_instance
        self._ddos_detector = None

    @property
    def ddos_detector(self):
        if self._ddos_detector is None:
            from services.firewall.protection.ddos import DDoSDetector
            self._ddos_detector = DDoSDetector()
            self._fw._ddos_detector = self._ddos_detector
        return self._ddos_detector

    def __call__(self, environ, start_response):
        # 解析真实客户端 IP：内网穿透 / 反向代理下 REMOTE_ADDR 恒为回环地址，
        # 必须从可信代理头部还原攻击者真实 IP，否则封禁与 DDoS 统计全部失效。
        ip = resolve_ip_from_environ(environ)

        if ip and ip not in _LOCAL_IPS:
            # 黑名单拦截：直接断开连接，不返回任何 HTTP 响应（0 字节）
            if self._fw.is_banned(ip):
                return self._reject()

            # IPv6 拦截：非回环 IPv6 连接在开关开启时直接断开
            if ':' in ip and self._ipv6_block_enabled():
                from core.system.logger import log_firewall
                log_firewall('INFO', 'Firewall', 'IPv6 连接拦截断开', ip=ip)
                return self._reject()

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

    @staticmethod
    def _reject():
        """直接断开连接，不向客户端发送任何字节。

        waitress 捕获 ``ClientDisconnected`` 后会直接关闭连接且不写出任何
        响应数据；未安装 waitress 的开发环境（werkzeug）退化为 403 空响应。
        """
        try:
            from waitress.channel import ClientDisconnected
        except ImportError:  # pragma: no cover - 仅无 waitress 的开发环境
            from werkzeug.exceptions import Forbidden
            raise Forbidden()
        raise ClientDisconnected()

    @staticmethod
    def _ipv6_block_enabled():
        """读取「IPv6 拦截」开关（失败时按关闭处理）。"""
        try:
            from config import get_config_value, IPV6_BLOCK_ENABLED
            return bool(get_config_value('IPV6_BLOCK_ENABLED', IPV6_BLOCK_ENABLED))
        except Exception:
            return False
