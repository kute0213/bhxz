"""MSPT/TPS 追踪器 —— 后台线程定时通过 /spark tps 获取服务器性能数据。

设计：
- 独立线程，每 5 秒执行一次 /spark tps 命令
- 缓存结果，外部通过 read-only 接口获取最新数据
- 连接失败时自动降级，不抛异常
- 连续失败时自动降低轮询频率（退避），恢复后重置
- 使用 threading.Event 实现优雅关闭
"""

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from core.logger import log
from services.rcon.client import execute_command


@dataclass
class MSPTData:
    """解析后的 MSPT/TPS 数据。"""
    # TPS (last 5s, 10s, 1m, 5m, 15m)
    tps_5s: float = 0.0
    tps_10s: float = 0.0
    tps_1m: float = 0.0
    tps_5m: float = 0.0
    tps_15m: float = 0.0
    # Tick durations (min/med/95%ile/max ms) - last 10s
    tick_min_10s: float = 0.0
    tick_med_10s: float = 0.0
    tick_p95_10s: float = 0.0
    tick_max_10s: float = 0.0
    # Tick durations (min/med/95%ile/max ms) - last 1m
    tick_min_1m: float = 0.0
    tick_med_1m: float = 0.0
    tick_p95_1m: float = 0.0
    tick_max_1m: float = 0.0
    # CPU usage
    cpu_system: float = 0.0
    cpu_process: float = 0.0
    # 综合指标
    mspt_current: float = 0.0   # 当前 MSPT（取 med_10s）
    raw: str = ''
    error: Optional[str] = None
    updated_at: float = 0.0


# 正则：TPS 行
# [⚡]  4.4, 4.49, 11.19, 13.15, 16.58
_TPS_PATTERN = re.compile(
    r'^\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*$',
)

# 正则：Tick durations 行
# [⚡]  119.7/204.4/248.2/749.6;  32.9/47.4/215.4/749.6
_TICK_PATTERN = re.compile(
    r'^\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*;\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*$',
)

# 正则：CPU usage 行
# [⚡]  37%, 26%, 20%  (system)
# [⚡]  23%, 20%, 18%  (process)
_CPU_SYSTEM_PATTERN = re.compile(r'^\s*([\d.]+)%.*\(system\)')
_CPU_PROCESS_PATTERN = re.compile(r'^\s*([\d.]+)%.*\(process\)')


def parse_mspt_data(raw: str) -> MSPTData:
    """解析 /spark tps 命令的应答文本。

    Args:
        raw: /spark tps 命令的原始应答

    Returns:
        解析后的 MSPTData
    """
    result = MSPTData(raw=raw.strip(), updated_at=time.time())

    if not raw:
        result.error = 'RCON 无应答'
        return result

    # 检测 execute_command 返回的错误信息（以 "RCON" 开头）
    error_prefixes = (
        'RCON 连接失败', 'RCON 密码未配置',
        'RCON 连接超时', 'RCON 连接被拒绝',
        'RCON 连接被重置', 'RCON 网络错误',
        'RCON 参数错误', 'RCON 连接异常',
        'RCON 命令执行异常',
    )
    stripped = raw.strip()
    if stripped.startswith(error_prefixes):
        result.error = stripped
        return result

    lines = raw.strip().split('\n')

    # 移除 Spark 前缀标记 [⚡] 或 [Spark]
    clean_lines = []
    for line in lines:
        line = re.sub(r'^\[[^\]]*\]\s*', '', line).strip()
        if line:
            clean_lines.append(line)

    for line in clean_lines:
        # 尝试匹配 TPS 行
        m = _TPS_PATTERN.match(line)
        if m:
            result.tps_5s = float(m.group(1))
            result.tps_10s = float(m.group(2))
            result.tps_1m = float(m.group(3))
            result.tps_5m = float(m.group(4))
            result.tps_15m = float(m.group(5))
            continue

        # 尝试匹配 Tick durations 行
        m = _TICK_PATTERN.match(line)
        if m:
            result.tick_min_10s = float(m.group(1))
            result.tick_med_10s = float(m.group(2))
            result.tick_p95_10s = float(m.group(3))
            result.tick_max_10s = float(m.group(4))
            result.tick_min_1m = float(m.group(5))
            result.tick_med_1m = float(m.group(6))
            result.tick_p95_1m = float(m.group(7))
            result.tick_max_1m = float(m.group(8))
            # 取 med_10s 作为当前 MSPT
            result.mspt_current = result.tick_med_10s
            continue

        # 尝试匹配 CPU 行
        m = _CPU_SYSTEM_PATTERN.match(line)
        if m:
            result.cpu_system = float(m.group(1))
            continue

        m = _CPU_PROCESS_PATTERN.match(line)
        if m:
            result.cpu_process = float(m.group(1))
            continue

    # 如果没有任何数据被解析，标记错误
    if result.tps_5s == 0.0 and result.tps_10s == 0.0 and result.tick_min_10s == 0.0:
        log('WARNING', 'RCON', f'MSPT 原始数据无法解析: {stripped[:300]}')
        result.error = '无法解析 MSPT 数据'

    return result


class MSPTTracker:
    """MSPT/TPS 后台追踪器。

    启动后在独立线程中每 5 秒执行一次 /spark tps 命令，
    解析结果并缓存，外部通过 get_mspt_data() 获取最新数据。

    连续失败时自动降低轮询频率，最多退避到 60 秒，
    恢复成功后立即重置回正常间隔。
    """

    def __init__(self, interval: float = 5.0):
        self._interval = interval
        self._lock = threading.Lock()
        self._cache: MSPTData = MSPTData()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._name = 'rcon-mspt-tracker'
        self._consecutive_failures = 0
        self._max_backoff = 60.0

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_mspt_data(self) -> MSPTData:
        """获取缓存的 MSPT 数据（线程安全）。"""
        with self._lock:
            return self._cache

    def start(self):
        """启动追踪线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._consecutive_failures = 0
        self._thread = threading.Thread(
            target=self._run_loop,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        log('INFO', 'RCON', 'MSPT 追踪器已启动')

    def stop(self):
        """停止追踪线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log('INFO', 'RCON', 'MSPT 追踪器已停止')

    def reset(self):
        """重置缓存和失败计数。"""
        with self._lock:
            self._cache = MSPTData()
            self._consecutive_failures = 0

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get_current_interval(self) -> float:
        """根据连续失败次数计算当前轮询间隔（退避）。"""
        failures = self._consecutive_failures
        if failures <= 0:
            return self._interval
        backoff = min(self._interval + failures * 5, self._max_backoff)
        return backoff

    def _run_loop(self):
        """后台循环：每 5 秒执行一次 /spark tps，失败时自动退避。"""
        while not self._stop_event.is_set():
            try:
                raw = execute_command('/spark tps', timeout=5)
                parsed = parse_mspt_data(raw)
                with self._lock:
                    self._cache = parsed
                    if parsed.error:
                        self._consecutive_failures += 1
                        if self._consecutive_failures == 1 or self._consecutive_failures % 6 == 0:
                            log('WARNING', 'RCON',
                                f'MSPT 获取失败 ({self._consecutive_failures}次): {parsed.error}')
                    else:
                        if self._consecutive_failures > 0:
                            log('INFO', 'RCON', 'MSPT 追踪已恢复')
                        self._consecutive_failures = 0
            except Exception as exc:
                with self._lock:
                    self._consecutive_failures += 1
                log('WARNING', 'RCON', f'MSPT 追踪异常: {exc}')

            current_interval = self._get_current_interval()
            self._stop_event.wait(current_interval)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# 模块级单例
mspt_tracker = MSPTTracker()