"""防火墙后台监控 —— 单线程 1 秒周期，集中执行所有定时任务。

职责（按执行频率排列）：
  [1s] 同步所有内存缓存（IP 封禁、账号封禁、白名单）
  [1s] 强制关闭黑名单 IP 的现存连接
  [60s] 清理过期的 IP 封禁与账号封禁
  [120s] 清理过期的 DDoS 计数与违规记录
  [3600s] VACUUM 回收存储空间

架构优势：
  - 单一 daemon 线程，无需多线程协调
  - 使用 time.monotonic() 高精度计时，避免系统时间跳变影响
  - 所有任务共用同一个 1 秒 tick 循环，零额外开销
"""

import threading
import time
import weakref

from core.system.logger import log

# ---- 执行间隔（秒） ----
SYNC_INTERVAL = 1.0        # 缓存同步
CLOSE_INTERVAL = 1.0       # 强制关闭连接
CLEANUP_INTERVAL = 60.0    # 清理过期封禁
DDOS_PRUNE_INTERVAL = 120.0  # 清理 DDoS 计数
SPAM_PRUNE_INTERVAL = 120.0  # 清理刷屏记录
VACUUM_INTERVAL = 3600.0   # VACUUM


class FirewallMonitor:
    """防火墙后台监控器 —— 单线程 1 秒 tick 循环。"""

    def __init__(self, firewall_instance):
        self._fw = firewall_instance
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._tick_loop, name='fw-tick', daemon=True
        )
        self._thread.start()
        log('INFO', 'Firewall', '防火墙后台监控已启动 (1s tick)')

    def stop(self):
        self._stop.set()
        if self._thread:
            try:
                self._thread.join(timeout=3)
            except Exception:
                pass
            self._thread = None
        log('INFO', 'Firewall', '防火墙后台监控已停止')

    def _tick_loop(self):
        """1 秒 tick 循环 —— 所有定时任务在此集中调度。"""
        # 初始化时间基准
        tick_count = 0
        last_sync = 0.0
        last_close = 0.0
        last_cleanup = 0.0
        last_ddos_prune = 0.0
        last_spam_prune = 0.0
        last_vacuum = 0.0

        while not self._stop.is_set():
            now = time.monotonic()

            # ---- [1s] 同步内存缓存 ----
            if now - last_sync >= SYNC_INTERVAL:
                try:
                    from core.firewall.database import sync_all_to_cache
                    sync_all_to_cache()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'缓存同步异常: {exc}')
                last_sync = now

            # ---- [1s] 强制关闭黑名单连接 ----
            if now - last_close >= CLOSE_INTERVAL:
                try:
                    self._force_close_banned()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'强制关闭连接异常: {exc}')
                last_close = now

            # ---- [60s] 清理过期封禁（IP + 账号） ----
            if now - last_cleanup >= CLEANUP_INTERVAL:
                try:
                    self._cleanup_expired_bans()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'清理过期封禁异常: {exc}')
                last_cleanup = now

            # ---- [120s] 清理 DDoS 计数 ----
            if now - last_ddos_prune >= DDOS_PRUNE_INTERVAL:
                try:
                    self._prune_ddos()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'DDoS 清理异常: {exc}')
                last_ddos_prune = now

            # ---- [120s] 清理刷屏记录 ----
            if now - last_spam_prune >= SPAM_PRUNE_INTERVAL:
                try:
                    from core.firewall.spam import prune_spam
                    prune_spam()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'刷屏记录清理异常: {exc}')
                last_spam_prune = now

            # ---- [3600s] VACUUM ----
            if now - last_vacuum >= VACUUM_INTERVAL:
                try:
                    from core.firewall.database import vacuum
                    vacuum()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'VACUUM 异常: {exc}')
                last_vacuum = now

            tick_count += 1
            # 等待 1 秒（或被 stop 唤醒）
            self._stop.wait(1.0)

    # ------------------------------------------------------------------
    # 强制关闭黑名单连接
    # ------------------------------------------------------------------

    def _force_close_banned(self):
        """强制关闭所有黑名单 IP 的现存连接。"""
        self._scan_server_connections()
        fw = self._fw
        with fw._state_lock:
            conns = getattr(fw, '_conns', None)
            if not conns:
                return
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
                if addr:
                    from core.firewall.database import is_ip_banned_cache
                    if is_ip_banned_cache(addr)[0]:
                        try:
                            conn.linger = False
                            conn.close()
                            log('Security', '防火墙: 监控强制关闭黑名单连接', ip=addr)
                        except Exception:
                            pass
                        dead.append(key)
            for key in dead:
                conns.pop(key, None)

    def _scan_server_connections(self):
        """从 Cheroot 连接管理器登记活跃连接。"""
        server = self._fw._server
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

    def _track_connection(self, conn):
        """登记活跃连接（弱引用）。"""
        fw = self._fw
        if not hasattr(fw, '_conns') or fw._conns is None:
            fw._conns = {}
        try:
            fw._conns[id(conn)] = weakref.ref(conn)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 清理过期封禁
    # ------------------------------------------------------------------

    def _cleanup_expired_bans(self):
        """清理所有过期的 IP 封禁和账号封禁记录。"""
        from core.firewall.database import get_db
        deleted_ip = 0
        deleted_account = 0
        try:
            with get_db() as conn:
                result = conn.execute(
                    "DELETE FROM firewall_bans "
                    "WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP"
                )
                try:
                    deleted_ip = result.fetchone()[0]
                except Exception:
                    pass
        except Exception as exc:
            log('WARNING', 'fw-tick', f'清理过期 IP 封禁失败: {exc}')

        try:
            with get_db() as conn:
                result = conn.execute(
                    "DELETE FROM firewall_account_bans "
                    "WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP"
                )
                try:
                    deleted_account = result.fetchone()[0]
                except Exception:
                    pass
        except Exception as exc:
            log('WARNING', 'fw-tick', f'清理过期账号封禁失败: {exc}')

        if deleted_ip or deleted_account:
            log('INFO', 'Firewall', f'过期封禁清理: IP={deleted_ip}, 账号={deleted_account}')

    # ------------------------------------------------------------------
    # DDoS 计数清理
    # ------------------------------------------------------------------

    def _prune_ddos(self):
        """清理过期的 DDoS 计数。"""
        from config import get_config_value
        fw = self._fw
        detector = getattr(fw, '_ddos_detector', None)
        if detector is not None:
            detector.prune(get_config_value)