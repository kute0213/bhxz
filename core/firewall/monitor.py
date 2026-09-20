"""防火墙后台监控 —— 单线程 1 秒周期，集中执行所有定时任务。

职责（按执行频率排列）：
  [1s] 同步所有内存缓存（IP 封禁、账号封禁、白名单）
  [1s] 使用过期堆清理已过期的 IP 封禁与账号封禁（每秒最多 10 条）
  [120s] 清理过期的 DDoS 计数与违规记录
  [3600s] VACUUM 回收存储空间

注意：连接强制关闭已移至 wrappers.py 响应式处理，不再在此处轮询。

架构优势：
  - 单一 daemon 线程，无需多线程协调
  - 使用 time.monotonic() 高精度计时，避免系统时间跳变影响
  - 所有任务共用同一个 1 秒 tick 循环，零额外开销
"""

import threading
import time

from core.system.logger import log

# ---- 执行间隔（秒） ----
SYNC_INTERVAL = 1.0        # 缓存同步
CLEANUP_INTERVAL = 1.0     # 清理过期封禁（使用过期堆）
DDOS_PRUNE_INTERVAL = 120.0  # 清理 DDoS 计数
AUTO_BAN_PRUNE_INTERVAL = 120.0  # 清理自动封禁违规记录
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
        last_cleanup = 0.0
        last_ddos_prune = 0.0
        last_auto_ban_prune = 0.0
        last_spam_prune = 0.0
        last_vacuum = 0.0

        while not self._stop.is_set():
            now = time.monotonic()

            # 启动后首次运行：加载过期堆
            if tick_count == 0:
                try:
                    from core.firewall.database import load_expiry_heap
                    load_expiry_heap()
                except Exception:
                    pass

            # ---- [1s] 同步内存缓存 ----
            if now - last_sync >= SYNC_INTERVAL:
                try:
                    from core.firewall.database import sync_all_to_cache
                    sync_all_to_cache()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'缓存同步异常: {exc}')
                last_sync = now

            # ---- [1s] 清理过期封禁（IP + 账号，使用过期堆） ----
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

            # ---- [120s] 清理自动封禁违规记录 ----
            if now - last_auto_ban_prune >= AUTO_BAN_PRUNE_INTERVAL:
                try:
                    from core.firewall.service import prune_auto_ban_offenses
                    prune_auto_ban_offenses()
                except Exception as exc:
                    log('WARNING', 'fw-tick', f'自动封禁违规记录清理异常: {exc}')
                last_auto_ban_prune = now

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
    # 清理过期封禁（使用过期堆，每秒最多处理 10 条）
    # ------------------------------------------------------------------

    def _cleanup_expired_bans(self):
        """使用过期堆逐个清理已过期的封禁（一次 tick 最多处理 10 条）。"""
        from core.firewall.database import pop_expired, get_db, invalidate_cache
        from core.system.logger import log

        expired = pop_expired()
        if not expired:
            return

        deleted_ip = 0
        deleted_account = 0
        for ts, ban_type, ban_id in expired[:10]:  # 每秒最多处理 10 条
            try:
                if ban_type == 'ip':
                    with get_db() as conn:
                        conn.execute(
                            "DELETE FROM firewall_bans WHERE id = ? AND "
                            "(expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP)",
                            (ban_id,)
                        )
                    deleted_ip += 1
                elif ban_type == 'account':
                    with get_db() as conn:
                        conn.execute(
                            "DELETE FROM firewall_account_bans WHERE id = ? AND "
                            "(expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP)",
                            (ban_id,)
                        )
                    deleted_account += 1
            except Exception:
                pass

        if deleted_ip or deleted_account:
            invalidate_cache()
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