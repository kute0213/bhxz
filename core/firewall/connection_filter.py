"""防火墙连接过滤器 —— 在 Cheroot 连接层直接断开黑名单 IP 的 TCP 连接。

层次结构：
  - BanFilterConnection  → 继承 cheroot.server.HTTPConnection，在 communicate()
                            中检查客户端 IP，命中黑名单直接断开 socket
  - FirewallGateway       → 继承 cheroot.wsgi.Gateway_10，在 WSGI environ 中
                            注入连接对象，供 WSGI 门禁与监控线程追踪
  - FirewallServer        → 继承 cheroot.wsgi.Server，替换网关与连接类

线程安全：
  - 每连接独立线程（Cheroot 自身机制），多线程并发安全
  - close() 幂等去重，避免 double-close 触发 EBADF fatal
  - close() 先注销连接管理器的 selector 再关闭 socket，
    防止 worker 线程 put_conn() 重复注册已关闭 fd 触发 KeyError
"""

import socket
import threading

from cheroot.wsgi import Gateway_10, Server as CherootWSGIServer
from cheroot.server import HTTPConnection

from core.firewall import database
from core.system.logger import log


class BanFilterConnection(HTTPConnection):
    """黑名单连接过滤器：命中黑名单的 IP 在请求解析前直接断开 TCP 连接。

    覆盖新连接与 keep-alive 复用连接，命中即断、不返回 HTTP 响应。
    """

    def __init__(self, server, sock, makefile=None):
        super().__init__(server, sock, makefile)
        # 幂等关闭标记：避免 double-close 触发 Cheroot EBADF fatal
        self._fw_closed = False
        # 本连接已从连接管理器注销标记
        self._fw_unregistered = False

    def close(self):
        if self._fw_closed:
            return
        self._fw_closed = True
        # 空闲 keep-alive 连接已注册到连接管理器的 selector 中，
        # 关闭前必须注销，否则 worker 线程后续 put_conn() 重复注册
        # 同一 fd 会触发 KeyError 致命停服。
        if not self._fw_unregistered:
            try:
                fd = self.socket.fileno()
                if fd >= 0:
                    cm = getattr(self.server, '_connections', None)
                    if cm is not None:
                        cm._selector.unregister(fd)
                        self._fw_unregistered = True
            except (LookupError, ValueError, OSError, AttributeError):
                pass
            except Exception:
                pass
        super().close()

    def communicate(self):
        ip = self._peer_ip()
        from core.firewall import firewall
        if firewall.is_banned(ip):
            self._drop_banned(ip)
            return False
        return super().communicate()

    def _peer_ip(self):
        """读取对端 IP（连接可能已被客户端关闭，异常时返回空串跳过拦截）。"""
        try:
            return self.socket.getpeername()[0]
        except Exception:
            return ''

    def _drop_banned(self, ip):
        """直接关闭黑名单连接，不返回 HTTP 响应。"""
        self.linger = False
        self.close()
        log('Security', '防火墙: 黑名单连接强制断开', ip=ip)


class FirewallGateway(Gateway_10):
    """在 WSGI environ 中注入 Cheroot 连接对象，供 WSGI 门禁追踪连接。"""

    def get_environ(self):
        env = super().get_environ()
        try:
            env['cheroot.connection'] = self.req.conn
        except Exception:
            pass
        return env


class FirewallServer(CherootWSGIServer):
    """启用防火墙的 Cheroot WSGI 服务器。

    自动设置：
      - gateway → FirewallGateway（注入连接对象）
      - ConnectionClass → BanFilterConnection（连接级黑名单拦截）
    """

    def __init__(self, bind_addr, wsgi_app, **kwargs):
        super().__init__(bind_addr, wsgi_app, **kwargs)
        self.gateway = FirewallGateway
        self.ConnectionClass = BanFilterConnection