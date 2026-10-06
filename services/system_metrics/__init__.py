"""系统指标采样服务 —— 后台定期采样 CPU / 内存 / 网络并缓存。

网络速率（上行 / 下行）必须由两次采样求差才能得到。若把换算放在前端，
用户打开状态页时要等到第二次轮询才会有速率数据。本服务在后台每
SAMPLE_INTERVAL 秒采样一次累计收发字节数并换算速率写入缓存，
前端直接读取缓存值，打开即有效，且与轮询时刻无关。

接口：
  - sample()      —— 采样一次并更新缓存（由统一定时任务驱动）
  - get_metrics() —— 读取最近一次采样结果（只读，不触发采样）

说明：cpu_percent 使用非阻塞模式，其数值是「距上次调用」的平均占用率，
因此采样间隔（SAMPLE_INTERVAL）即是 CPU 使用率的统计窗口；首次调用返回 0。
"""

import threading
import time

from core.shared.scheduler import register_task
from core.system.logger import log

# 采样间隔（秒）：与状态页轮询周期一致
SAMPLE_INTERVAL = 5

_lock = threading.Lock()

# 最近一次采样结果（无样本时以默认值占位）
_cache = {
    'cpu_percent': 0.0,
    'memory_percent': 0.0,
    'memory_used': 0,
    'memory_total': 0,
    'net_sent': 0,        # 累计发送字节（自开机）
    'net_recv': 0,        # 累计接收字节（自开机）
    'net_up': 0.0,        # 上行速率（字节/秒）
    'net_down': 0.0,      # 下行速率（字节/秒）
    'sampled_at': 0.0,    # 最近采样时间（wall clock，仅供调试）
    'ready': False,       # 是否已有有效样本
}

# 上一次网络计数采样：(sent, recv, monotonic 时间戳)
_prev_net = None


def _read_net_counters(psutil):
    """读取累计收发字节数；平台不支持时返回 (0, 0)。"""
    reader = getattr(psutil, 'net_io_counters', None)
    try:
        counters = reader() if callable(reader) else None
    except Exception:
        counters = None
    if counters is None:
        return 0, 0
    return counters.bytes_sent, counters.bytes_recv


def sample():
    """采样一次系统指标并写入缓存。

    采样失败时保留上一次缓存值（不抛异常），避免后台任务因单次异常中断。
    """
    global _prev_net
    try:
        import psutil
    except Exception:
        return

    try:
        # interval=None：非阻塞，返回自上次调用以来的平均 CPU 占用率
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        net_sent, net_recv = _read_net_counters(psutil)

        now = time.monotonic()
        up = down = 0.0
        prev = _prev_net
        if prev is not None:
            dt = now - prev[2]
            if dt > 0:
                # 计数器回绕 / 重置时可能为负，钳到 0
                up = max(0.0, (net_sent - prev[0]) / dt)
                down = max(0.0, (net_recv - prev[1]) / dt)
        _prev_net = (net_sent, net_recv, now)

        with _lock:
            _cache.update(
                cpu_percent=cpu_percent,
                memory_percent=mem.percent,
                memory_used=mem.used,
                memory_total=mem.total,
                net_sent=net_sent,
                net_recv=net_recv,
                net_up=up,
                net_down=down,
                sampled_at=time.time(),
                ready=True,
            )
    except Exception as exc:
        log('WARNING', 'SystemMetrics', '采样系统指标失败', error=str(exc))


def get_metrics():
    """返回缓存指标副本；尚无样本时返回默认值（ready=False）。"""
    with _lock:
        return dict(_cache)


# 首次采样：建立网络计数基线，后续采样即可算出速率
sample()

# 统一定时任务：每 SAMPLE_INTERVAL 秒采样一次（注册后立即触发一次）
metrics_scheduler = register_task(
    name='system-metrics-sampler',
    action=sample,
    interval=SAMPLE_INTERVAL,
)
