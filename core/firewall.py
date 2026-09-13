"""极高性能多线程防火墙 —— 运行在 WSGI 入口，先于一切 Flask 业务逻辑。

设计目标：
1. IP 黑名单快速拦截：进程内维护黑名单内存镜像（O(1) 集合查询），
   命中黑名单的请求在进入 Flask 前即被终结，不参与路由、模板、数据库、
   公共文件服务等任何逻辑处理；已建立的连接由后台监控线程利用
   Cheroot 连接特性直接强制关闭（linger=False + close），客户端表现为
   连接被重置而非收到页面。
2. DDoS 攻击检测：按检测强度统计单位时间窗口内每个 IP 的请求数，
   超阈值立即封禁（限时封禁）；屡教不改（多次触发）自动升级为永久封禁。
   检测强度（低/中/高）与封禁时长可在管理后台 → 系统设置中热更新。
3. 多线程后台监控：监控线程定期从数据库同步黑名单镜像、强制关闭黑名单
   IP 的现存连接、清理过期的请求计数与违规记录。

线程安全说明：黑名单镜像的「读」发生在每请求热路径（集合 in 查询，
CPython GIL 下与写入并发时最多短暂滞后、不会崩溃），「写」仅在监控
线程与 DDoS 触发时加锁执行。
"""

import threading
import time
import weakref
from collections import deque

from cheroot.wsgi import Gateway_10, Server as CherootWSGIServer

from core.logger import log

# DDoS 检测强度预设：单位检测窗口（秒）内允许的最大请求数
# low=宽松（只拦明显洪泛） / medium=中等 / high=严格（对突发敏感）
DDOS_INTENSITY_PRESETS = {
    'low': 300,
    'medium': 150,
    'high': 80,
}

# 固定检测窗口（秒），与强度预设共同决定封禁触发条件
DDOS_WINDOW_SECONDS = 10

# 黑名单镜像同步周期（秒）
SYNC_INTERVAL = 0.5

# 强制关闭连接扫描周期（秒）
CLOSE_INTERVAL = 0.5


class FirewallGateway(Gateway_10):
    """在 WSGI environ 中注入 Cheroot 连接对象，供防火墙强制关闭黑名单连接。"""

    def get_environ(self):
        env = super().get_environ()
        try:
            env['cheroot.connection'] = self.req.conn
        except Exception:
            pass
        return env


class FirewallServer(CherootWSGIServer):
    """启用防火墙网关的 Cheroot WSGI 服务器（environ 携带连接对象）。"""

    def __init__(self, bind_addr, wsgi_app, **kwargs):
        super().__init__(bind_addr, wsgi_app, **kwargs)
        # 覆盖网关：WSGIGateway 实例化后注入 cheroot.connection
        self.gateway = FirewallGateway


class Firewall:
    """极高性能多线程防火墙（单例）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # 黑名单内存镜像 {ip: reason}（快速路径仅用 set 语义判断）
        self._banned = set()
        self._banned_reasons = {}
        self._state_lock = threading.Lock()
        # 当前活跃的连接（id -> weakref），供监控线程强制关闭
        self._conns = {}
        # DDoS 请求计数 {ip: deque[timestamp, ...]}
        self._counters = {}
        # DDoS 违规记录 {ip: [触发次数, 最近触发时间]}
        self._offenses = {}
        # 配置缓存（5 秒 TTL，避免每请求读设置）
        self._cfg_cache = {}
        self._cfg_ts = 0.0
        self._started = False
        self._stop = threading.Event()
        self._threads = []
        # 绑定的 Cheroot 服务器（监控线程通过其连接管理器扫描活跃连接）
        self._server = None

    # ------------------------------------------------------------------
    # 配置读取（带 5 秒 TTL 缓存）
    # ------------------------------------------------------------------

    def _cfg(self, key, default):
        now = time.time()
        if now - self._cfg_ts > 5:
            self._cfg_cache.clear()
            self._cfg_ts = now
        if key not in self._cfg_cache:
            try:
                from config import get_config_value
                self._cfg_cache[key] = get_config_value(key, default)
            except Exception:
                self._cfg_cache[key] = default
        return self._cfg_cache[key]

    # ------------------------------------------------------------------
    # WSGI 入口门禁（先于一切 Flask 逻辑）
    # ------------------------------------------------------------------

    def wrap(self, wsgi_app):
        """包装 WSGI 应用：黑名单快速拦截 + 连接登记 + DDoS 计数。"""
        def firewall_gate(environ, start_response):
            ip = environ.get('REMOTE_ADDR') or ''
            if ip:
                if ip in self._banned:
                    # 黑名单快速拦截：不进入 Flask，最小响应 + 连接关闭
                    body = (
                        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width, initial-scale=1">'
                        '<title>403 Forbidden</title>'
                        '<style>body{margin:0;min-height:100vh;display:flex;align-items:center;'
                        'justify-content:center;background:#0a0f0d;color:#f5efe0;'
                        'font-family:system-ui,sans-serif}.card{max-width:520px;padding:48px 24px;'
                        'text-align:center}h1{margin:0;font-size:96px;color:#f87171}'
                        '.t{font-size:22px;color:#f5efe0;margin:8px 0 24px}'
                        'p{color:#f5efe0aa;line-height:1.9;font-size:14px}</style>'
                        '</head><body><div class="card"><h1>403</h1>'
                        '<p class="t">Forbidden</p>'
                        '<p>原因：该 IP 已被封禁，如有疑问请联系管理员。</p>'
                        '<p>建议：被封禁期间请勿继续访问，否则可能延长封禁。</p>'
                        '</div></body></html>'
                    ).encode('utf-8')
                    start_response(
                        '403 Forbidden',
                        [
                            ('Content-Type', 'text/html; charset=utf-8'),
                            ('Content-Length', str(len(body))),
                            ('Connection', 'close'),
                            ('X-Firewall', '1'),
                        ],
                    )
                    return [body]
                conn = environ.get('cheroot.connection')
                if conn is not None:
                    self._track_connection(conn)
                self._record(ip, environ.get('PATH_INFO') or '')
            return wsgi_app(environ, start_response)
        return firewall_gate

    # ------------------------------------------------------------------
    # 连接跟踪与强制关闭
    # ------------------------------------------------------------------

    def attach_server(self, server):
        """绑定 Cheroot 服务器实例，供监控线程扫描其连接管理器中的活跃连接。"""
        self._server = server

    def _track_connection(self, conn):
        """登记活跃连接（弱引用，连接回收后自动清理）。"""
        try:
            self._conns[id(conn)] = weakref.ref(conn)
        except Exception:
            pass

    def _force_close_banned(self):
        """强制关闭所有黑名单 IP 的现存连接（包括 keep-alive 空闲与处理中的请求）。"""
        self._scan_server_connections()
        if not self._conns:
            return
        with self._state_lock:
            conns = self._conns
            dead = []
            for key, ref in list(conns.items()):
                conn = ref()
                if conn is None:
                    dead.append(key)
                    continue
                try:
                    addr = conn.remote_addr
                except Exception:
                    dead.append(key)
                    continue
                if addr and addr in self._banned:
                    self._drop_connection(conn, addr)
                    dead.append(key)
            for key in dead:
                conns.pop(key, None)

    def _scan_server_connections(self):
        """从 Cheroot 连接管理器登记活跃连接（含 keep-alive 空闲连接）。

        处理中的请求连接由 WSGI 门禁登记；空闲 keep-alive 连接由
        连接管理器的 selector 维护，此处兜底登记，确保不留死角。
        """
        server = self._server
        if server is None:
            return
        try:
            cm = server._connections
            for _, conn in cm._selector.connections:
                if conn is server:
                    continue
                self._track_connection(conn)
        except Exception:
            pass

    @staticmethod
    def _drop_connection(conn, ip):
        """利用 Cheroot 连接特性强制关闭连接（linger=False 立即断开内核 socket）。"""
        try:
            conn.linger = False
            conn.close()
            log('Security', '防火墙强制关闭黑名单连接', ip=ip)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # DDoS 检测
    # ------------------------------------------------------------------

    def _record(self, ip, path):
        """每请求计数；超过强度阈值立即触发封禁。"""
        if not self._cfg('DDOS_GUARD_ENABLED', True):
            return
        # 静态资源不计入（避免正常页面加载多资源造成误判）
        if path.startswith('/static/'):
            return
        intensity = str(self._cfg('DDOS_GUARD_INTENSITY', 'medium') or 'medium').lower()
        threshold = DDOS_INTENSITY_PRESETS.get(intensity, DDOS_INTENSITY_PRESETS['medium'])
        now = time.time()
        with self._state_lock:
            q = self._counters.get(ip)
            if q is None:
                q = deque()
                self._counters[ip] = q
            q.append(now)
            while q and now - q[0] > DDOS_WINDOW_SECONDS:
                q.popleft()
            if len(q) >= threshold:
                # 触发封禁后清空计数，避免窗口内重复触发
                self._counters.pop(ip, None)
                self._ban_ddos_locked(ip, threshold)

    def _ban_ddos_locked(self, ip, threshold):
        """DDoS 封禁：首次限时封禁，屡教不改升级永久封禁。"""
        from services.ip_ban_service import is_whitelisted, create_ban, SYSTEM_BANNER_ID

        if is_whitelisted(ip):
            return
        if not ip or ip in self._banned:
            return

        # 屡教不改计数（DDOS_GUARD_OFFENSE_WINDOW_HOURS 小时内多次触发才累积）
        now = time.time()
        offense_hours = int(self._cfg('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24) or 24)
        permanent_after = int(self._cfg('DDOS_GUARD_PERMANENT_AFTER', 3) or 3)
        rec = self._offenses.get(ip)
        if rec and now - rec[1] <= offense_hours * 3600:
            rec[0] += 1
        else:
            rec = [1, now]
            self._offenses[ip] = rec
        offense_count = rec[0]
        permanent = offense_count >= permanent_after

        ban_minutes = int(self._cfg('DDOS_GUARD_BAN_MINUTES', 30) or 30)
        duration_days = None
        if not permanent and ban_minutes > 0:
            duration_days = ban_minutes / 1440.0

        if permanent:
            reason = 'DDoS 攻击（屡次触发，永久封禁）'
        else:
            reason = (
                f'DDoS 攻击（{DDOS_WINDOW_SECONDS} 秒内请求超过 {threshold} 次，'
                f'封禁 {ban_minutes} 分钟）'
            )

        try:
            success, _ = create_ban(
                ip_address=ip,
                reason=reason,
                banned_by=SYSTEM_BANNER_ID,
                duration_days=duration_days,
            )
        except Exception:
            success = False
        if success:
            with self._state_lock:
                self._banned.add(ip)
                self._banned_reasons[ip] = reason
            log('Security', 'DDoS 防护：自动封禁',
                ip=ip, threshold=threshold, window=DDOS_WINDOW_SECONDS,
                permanent=permanent, offense_count=offense_count,
                duration_minutes='永久' if permanent else ban_minutes)

    # ------------------------------------------------------------------
    # 黑名单同步与清理
    # ------------------------------------------------------------------

    def _sync_blacklist(self):
        """从数据库同步有效封禁到内存镜像。"""
        try:
            from services.ip_ban_service import get_banned_ips
            banned = get_banned_ips()
        except Exception:
            return
        with self._state_lock:
            self._banned = set(banned)
            self._banned_reasons = dict(banned)

    def _prune(self):
        """清理过期的 DDoS 计数与违规记录。"""
        now = time.time()
        with self._state_lock:
            stale = [
                ip for ip, q in self._counters.items()
                if not q or now - q[-1] > DDOS_WINDOW_SECONDS * 2
            ]
            for ip in stale:
                self._counters.pop(ip, None)
            offense_hours = int(self._cfg('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24) or 24)
            stale2 = [
                ip for ip, rec in self._offenses.items()
                if now - rec[1] > offense_hours * 3600
            ]
            for ip in stale2:
                self._offenses.pop(ip, None)

    # ------------------------------------------------------------------
    # 后台线程
    # ------------------------------------------------------------------

    def _monitor_loop(self):
        """监控线程：同步黑名单 + 强制关闭黑名单 IP 的现存连接。"""
        while not self._stop.is_set():
            try:
                self._sync_blacklist()
                self._force_close_banned()
            except Exception as exc:
                log('WARNING', 'Firewall', f'防火墙监控循环异常: {exc}')
            self._stop.wait(CLOSE_INTERVAL)

    def _ddos_loop(self):
        """DDoS 线程：定期清理过期的计数与违规记录。"""
        while not self._stop.is_set():
            try:
                self._prune()
            except Exception as exc:
                log('WARNING', 'Firewall', f'防火墙清理循环异常: {exc}')
            self._stop.wait(2)

    def start(self):
        """启动防火墙后台线程。"""
        if self._started:
            return
        self._started = True
        t1 = threading.Thread(target=self._monitor_loop, name='firewall-monitor', daemon=True)
        t2 = threading.Thread(target=self._ddos_loop, name='firewall-ddos', daemon=True)
        t1.start()
        t2.start()
        self._threads = [t1, t2]
        log('INFO', 'Firewall', '防火墙已启动（黑名单镜像 + DDoS 检测）')

    def stop(self):
        """停止防火墙后台线程。"""
        self._stop.set()
        for t in self._threads:
            try:
                t.join(timeout=2)
            except Exception:
                pass
        self._threads = []
        log('INFO', 'Firewall', '防火墙已停止')


# 全局单例
firewall = Firewall()
