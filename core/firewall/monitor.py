"""防火墙后台监控线程 —— 同步黑名单 + 强制关闭黑名单连接 + 定时清理。

职责：
  1. 每 0.5 秒从 DuckDB 同步有效封禁到内存黑名单镜像
  2. 每 0.5 秒扫描服务器活跃连接，强制关闭黑名单 IP 的连接
  3. 每 30 秒清理 DuckDB 中的过期封禁
  4. 每 5 分钟清理过期的 DDoS 计数与违规记录
  5. 每 1 小时执行 VACUUM 回收存储空间
"""

import threading
import time
import weakref

from core.system.logger import log

# 黑名单同步周期（秒）
SYNC_INTERVAL = 0.5
# 强制关闭连接扫描周期（秒）
CLOSE_INTERVAL = 0.5
# DDoS 清理周期（秒）
DDOS_PRUNE_INTERVAL = 30
# 过期封禁清理周期（秒）
CLEANUP_INTERVAL = 60
# VACUUM 周期（秒）
VACUUM_INTERVAL = 3600


class FirewallMonitor:
    """防火墙后台监控器。"""

    def __init__(self, firewall_instance):
        """
        Args:
            firewall_instance: Firewall 单例（拥有 _banned_set, _server, _state_lock 等）
        """
        self._fw = firewall_instance
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        if self._threads:
            return
        self._stop.clear()
        t1 = threading.Thread(target=self._monitor_loop, name='fw-monitor', daemon=True)
        t2 = threading.Thread(target=self._cleanup_loop, name='fw-cleanup', daemon=True)
        t1.start()
        t2.start()
        self._threads = [t1, t2]
        log('INFO', 'Firewall', '防火墙后台监控已启动')

    def stop(self):
        self._stop.set()
        for t in self._threads:
            try:
                t.join(timeout=2)
            except Exception:
                pass
        self._threads = []
        log('INFO', 'Firewall', '防火墙后台监控已停止')

    def _monitor_loop(self):
        """监控循环：同步黑名单 + 强制关闭黑名单连接。"""
        ddos_prune_time = time.time()
        while not self._stop.is_set():
            try:
                self._fw.sync_blacklist()
                self._force_close_banned()
                now = time.time()
                if now - ddos_prune_time > DDOS_PRUNE_INTERVAL:
                    self._prune_ddos()
                    ddos_prune_time = now
            except Exception as exc:
                log('WARNING', 'FirewallMonitor', f'监控循环异常: {exc}')
            self._stop.wait(CLOSE_INTERVAL)

    def _cleanup_loop(self):
        """清理循环：过期封禁 + VACUUM。"""
        vacuum_time = time.time()
        while not self._stop.is_set():
            self._stop.wait(CLEANUP_INTERVAL)
            try:
                from core.firewall.service import cleanup_expired
                cleanup_expired()
                now = time.time()
                if now - vacuum_time > VACUUM_INTERVAL:
                    from core.firewall.database import vacuum
                    vacuum()
                    vacuum_time = now
            except Exception as exc:
                log('WARNING', 'FirewallMonitor', f'清理循环异常: {exc}')

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
                if addr and addr in fw._banned_set:
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
        """从 Cheroot 连接管理器登记活跃连接（含 keep-alive 空闲连接）。"""
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

    def _prune_ddos(self):
        """清理过期的 DDoS 计数。"""
        from config import get_config_value
        from core.firewall.ddos import DDoSDetector
        # 访问 firewall 实例上的 _ddos_detector
        fw = self._fw
        detector = getattr(fw, '_ddos_detector', None)
        if detector is not None:
            detector.prune(get_config_value)