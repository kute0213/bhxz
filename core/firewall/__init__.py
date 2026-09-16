"""防火墙 —— 高性能模块，集连接级阻断、DDoS 防护、IP 管理于一体。

架构层次（自底向上）：
  1. DuckDB 引擎 — 独立高性能数据库，存放封禁/白名单/警告/攻击日志
  2. 统一业务层 — 封禁 IP、白名单管理、警告系统等路由级 API
  3. 连接过滤器 — BanFilterConnection 在 Cheroot 连接层直接断开黑名单 TCP 连接
  4. DDoS 监测 — 按窗口统计请求数、自动封禁（静态资源/媒体下载等不计入）
  5. 后台监控 — 同步黑名单镜像、强制关闭黑名单连接、定时清理过期数据
  6. WSGI 门禁 — 在进入 Flask 前二次拦截（兜底）

使用方式（路由/服务中）：
    from core.firewall import ban_ip, unban_ip, is_banned, is_whitelisted, ...

安全说明：
    - 白名单 IP 不会被执行任何封禁操作
    - 连接级拦截执行于请求解析之前，不产生任何 HTTP 响应
    - DuckDB 文件位于 db/firewall.duckdb，独立于主站业务数据库
"""

from core.firewall.service import (
    ban_ip,
    unban_ip,
    unban_by_ip,
    is_banned,
    validate_ip,
    get_bans,
    get_ban,
    cleanup_expired,
    get_whitelist,
    is_whitelisted,
    whitelist_add,
    whitelist_remove,
    auto_ban,
    ban_suspicious_ip,
    add_warning,
    get_warnings,
    get_warning_count,
    get_all_warnings,
    clear_warnings,
    SYSTEM_BANNER_ID,
)

from core.firewall.connection_filter import BanFilterConnection, FirewallGateway, FirewallServer
from core.firewall.wrappers import FirewallWSGIWrapper
from core.firewall.monitor import FirewallMonitor

# 防火墙全局单例（集成连接过滤器 + WSGI 门禁 + 后台监控）
class Firewall:
    """防火墙主入口：管理连接过滤器、WSGI 门禁与后台监控。

    用法：
        from core.firewall import firewall

        # 在 server.py 中使用 FirewallServer
        from core.firewall.connection_filter import FirewallServer
        server = FirewallServer(..., firewall.wrap(app))

        # 注册后台监控
        firewall.attach_server(server)
        firewall.start_monitor()
    """

    _instance = None
    _lock = __import__('threading').Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True
        # 黑名单内存镜像（O(1) 查询热路径）
        self._banned_set = set()
        self._banned_reasons = {}
        self._state_lock = __import__('threading').Lock()
        # Cheroot 服务器引用
        self._server = None
        # 监控器
        self._monitor = None

    # ---- 黑名单镜像（连接过滤器 / WSGI 门禁快速查询）----

    def is_banned(self, ip):
        """O(1) 黑名单查询（供连接过滤器在请求解析前快速拦截）。

        内置安全 IP（127.0.0.1、::1）永远返回未封禁。
        """
        if not ip or ip in ('127.0.0.1', '::1', 'localhost'):
            return False
        return ip in self._banned_set

    def sync_blacklist(self):
        """从 DuckDB 同步有效封禁到内存镜像（排除内置安全 IP）。"""
        try:
            from core.firewall.database import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT ip_address, reason FROM firewall_bans "
                    "WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP"
                ).fetchall()
            banned = {}
            safe = {'127.0.0.1', '::1', 'localhost'}
            for row in rows:
                if row[0] not in safe:
                    banned[row[0]] = row[1] or ''
            with self._state_lock:
                self._banned_set = set(banned.keys())
                self._banned_reasons = banned
        except Exception:
            pass

    # ---- WSGI 包装 ----

    def wrap(self, wsgi_app):
        """包装 WSGI 应用返回 FirewallWSGIWrapper 实例。

        返回的包装器同时作为 WSGI 应用与自定义连接容器的共享状态。
        """
        wrapper = FirewallWSGIWrapper(wsgi_app, self)
        return wrapper

    # ---- 连接跟踪与强制关闭 ----

    def attach_server(self, server):
        """绑定 Cheroot 服务器实例（供监控线程扫描其连接管理器中的活跃连接）。"""
        self._server = server

    @property
    def server(self):
        return self._server

    # ---- 后台监控 ----

    def start_monitor(self):
        """启动防火墙后台监控线程。"""
        if self._monitor is None:
            self._monitor = FirewallMonitor(self)
            self._monitor.start()

    def stop_monitor(self):
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None


# 全局单例
firewall = Firewall()