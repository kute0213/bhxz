"""性能数据后台追踪器 —— 定时采集 CPU、内存、系统信息并缓存。

与 PlayerTracker 逻辑一致：
- 独立后台线程，每 5 秒采集一次
- 缓存结果，外部通过 get_performance_data() 获取最新数据
- 连接失败时自动降级，不抛异常
- 使用 threading.Event 实现优雅关闭
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from core.logger import log
from services.monitoring.cpu import get_cpu_usage, get_cpu_temperature
from services.monitoring.memory import get_memory_info
from services.monitoring.system import get_system_info


@dataclass
class PerformanceData:
    """缓存的性能数据。"""
    cpu_usage: Optional[float] = None
    cpu_temp: Optional[float] = None
    memory: Optional[dict] = None
    system: Optional[dict] = None
    timestamp: str = ''
    updated_at: float = 0.0


class PerformanceTracker:
    """性能数据后台追踪器。

    启动后在独立线程中每 5 秒采集一次系统性能数据，
    解析结果并缓存，外部通过 get_performance_data() 获取最新数据。
    """

    def __init__(self, interval: float = 5.0):
        self._interval = interval
        self._lock = threading.Lock()
        self._cache: PerformanceData = PerformanceData()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._name = 'performance-tracker'

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_performance_data(self) -> PerformanceData:
        """获取缓存的性能数据（线程安全）。"""
        with self._lock:
            return self._cache

    def start(self):
        """启动追踪线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        log('INFO', 'Performance', '性能数据追踪器已启动')

    def stop(self):
        """停止追踪线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log('INFO', 'Performance', '性能数据追踪器已停止')

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _collect(self) -> PerformanceData:
        """采集一次所有性能数据。"""
        now = time.time()
        ts = datetime.now(timezone.utc).astimezone().strftime(
            '%Y-%m-%d %H:%M:%S %z'
        )
        return PerformanceData(
            cpu_usage=get_cpu_usage(),
            cpu_temp=get_cpu_temperature(),
            memory=get_memory_info(),
            system=get_system_info(),
            timestamp=ts,
            updated_at=now,
        )

    def _run_loop(self):
        """后台循环：每 5 秒采集一次。"""
        # 先立即采集一次，避免首次访问时数据为空
        try:
            data = self._collect()
            with self._lock:
                self._cache = data
        except Exception:
            pass

        while not self._stop_event.is_set():
            try:
                data = self._collect()
                with self._lock:
                    self._cache = data
            except Exception:
                pass
            self._stop_event.wait(self._interval)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# 模块级单例
performance_tracker = PerformanceTracker()