"""防火墙 —— 高性能模块，集连接级阻断、DDoS 防护、IP 管理于一体。

架构层次（自底向上）：
  1. DuckDB 引擎 — 独立高性能数据库，存放封禁/白名单/警告/攻击日志
  2. 统一业务层 — 封禁 IP、白名单管理、警告系统等路由级 API
  3. 连接过滤器 — BanFilterConnection 在 Cheroot 连接层直接断开黑名单 TCP 连接
  4. DDoS 监测 — 按窗口统计请求数、自动封禁（静态资源/媒体下载等不计入）
  5. 后台监控 — 同步黑名单镜像、强制关闭黑名单连接、定时清理过期数据
  6. WSGI 门禁 — 在进入 Flask 前二次拦截（兜底）

使用方式（路由/服务中）：
    from routes.firewall import ban_ip, unban_ip, is_banned, is_whitelisted, ...

安全说明：
    - 白名单 IP 不会被执行任何封禁操作
    - 连接级拦截执行于请求解析之前，不产生任何 HTTP 响应
    - DuckDB 文件位于 db/firewall.duckdb，独立于主站业务数据库
"""

from routes.firewall.service import (
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
    # 账号封禁
    ban_account,
    unban_account,
    unban_account_by_user,
    is_account_banned,
    get_account_bans,
    get_account_ban,
    # 刷屏记录
    record_spam,
    get_spam_log,
    get_user_spam_count,
    clear_spam_log,
    # 警告系统
    add_warning,
    get_warnings,
    get_warning_count,
    get_all_warnings,
    clear_warnings,
    # 账号白名单
    get_account_whitelist,
    whitelist_account,
    unwhitelist_account,
    # 封禁详情
    get_ban_detail_service,
    # 手动封禁（自动推送上下文）
    ban_ip_manual,
    ban_account_manual,
    # 常量
    SYSTEM_BANNER_ID,
)

from routes.firewall.connection_filter import BanFilterConnection, FirewallGateway, FirewallServer
from routes.firewall.wrappers import FirewallWSGIWrapper
from routes.firewall.monitor import FirewallMonitor

# 发布内容注入检测
from routes.firewall.content_filter import check_content_injection

from routes.firewall.service import get_combined_bans

# 防火墙全局单例（集成连接过滤器 + WSGI 门禁 + 后台监控）
class Firewall:
    """防火墙主入口：管理连接过滤器、WSGI 门禁与后台监控。

    用法：
        from routes.firewall import firewall

        # 在 server.py 中使用 FirewallServer
        from routes.firewall.connection_filter import FirewallServer
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
        self._state_lock = __import__('threading').Lock()
        self._server = None
        self._monitor = None

    # ---- 黑名单查询 ----

    def is_banned(self, ip):
        """O(1) 黑名单查询（使用数据库层内存缓存）。"""
        if not ip or ip in ('127.0.0.1', '::1', 'localhost'):
            return False
        from routes.firewall.database import is_ip_banned_cache
        return is_ip_banned_cache(ip)[0]

    def is_account_banned(self, user_id):
        """O(1) 账号封禁查询（使用数据库层内存缓存）。"""
        from routes.firewall.database import is_account_banned_cache
        return is_account_banned_cache(user_id)[0]

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