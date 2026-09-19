"""定时任务定义 —— 时间计算、重调度、失败退避（纯算法，不包含线程逻辑）。

本模块只负责「一个任务何时该执行」，不负责何时检查、如何执行，
便于单独做单元测试与时间推演。
"""

import time
from datetime import datetime, timedelta


def parse_clock_time(time_str, default_hour=3, default_minute=0):
    """解析 "HH:MM" 时间字符串为 (hour, minute)。

    非法输入回退到默认时间；小时限制 0-23，分钟限制 0-59。
    """
    try:
        parts = str(time_str).strip().split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return max(0, min(23, hour)), max(0, min(59, minute))
    except (ValueError, IndexError, AttributeError):
        return default_hour, default_minute


def compute_backoff(base_interval, failures, factor=0.0, max_interval=0.0):
    """失败退避算法：base + failures * factor，封顶 max_interval。

    factor 或 max_interval 为 0 时表示不启用退避，恒返回 base_interval。
    """
    if failures <= 0 or factor <= 0:
        return base_interval
    upper = max_interval if max_interval > 0 else float('inf')
    return min(base_interval + failures * factor, upper)


class ScheduledTask:
    """统一注册表中的最小单元：一种调度模式 + 一个回调。

    调度模式（interval 与 run_at 二选一，同时给出时优先 interval）：
      - interval：固定间隔（秒），连续失败时可按 backoff_factor/backoff_max 退避
      - run_at：每日时间点 "HH:MM"，或返回该字符串的可调用对象（支持配置热重载）
               每天至多执行一次（当天去重）；若注册时当天时刻已过则补执行一次

    执行方式（mode，见 core/shared/scheduler/executors.py）：
      - 'pool'：共享守护线程池（默认）
      - 'thread'：每次执行新建独立守护线程
    """

    def __init__(self, name, action, *, interval=None, run_at=None,
                 run_immediately=None, backoff_factor=0.0, backoff_max=0.0,
                 mode='pool'):
        if interval is None and run_at is None:
            raise ValueError('interval 与 run_at 至少指定一个')
        self.name = name
        self.action = action
        self.interval = interval
        self.run_at = run_at
        self.backoff_factor = backoff_factor
        self.backoff_max = backoff_max
        self.mode = mode
        if run_immediately is None:
            run_immediately = interval is not None
        self.run_immediately = run_immediately
        # 调度状态（time.monotonic 基准，不受系统时间跳变影响）
        self.next_run_at = 0.0      # 下次执行时间（monotonic 秒）
        self.failures = 0           # 连续失败次数（退避依据）
        self.running = False        # 是否正在执行
        self.removed = False        # 是否已注销（执行期间注销则不再重排）
        self._run_today = False     # 时钟模式：今天是否已执行

    # ------------------------------------------------------------------
    # 时间计算
    # ------------------------------------------------------------------

    def _clock_spec(self):
        """获取时钟配置；支持可调用对象实现热重载。"""
        return self.run_at() if callable(self.run_at) else self.run_at

    def _today_mono_delta(self):
        """今天 (HH:MM) 距现在的秒数；今天时刻已过返回 None。"""
        hour, minute = parse_clock_time(self._clock_spec())
        target = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        delta = (target - datetime.now()).total_seconds()
        return delta if delta > 0 else None

    def _tomorrow_mono_delta(self):
        """距明天 (HH:MM) 的秒数。"""
        hour, minute = parse_clock_time(self._clock_spec())
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        return (tomorrow - now).total_seconds()

    # ------------------------------------------------------------------
    # 排期
    # ------------------------------------------------------------------

    def schedule_first(self):
        """注册时的首次排期（按 run_immediately 决定是否立即触发）。"""
        now = time.monotonic()
        if self.interval is not None:
            self.next_run_at = now if self.run_immediately else now + self.interval
            return
        # 时钟模式：今天时刻未到 → 今天触发；已过且今天未执行 → 立即补执行一次；
        # 否则顺延到明天
        today_delta = self._today_mono_delta()
        if today_delta is not None:
            self.next_run_at = now + today_delta
        elif not self._run_today:
            self.next_run_at = now
        else:
            self.next_run_at = now + self._tomorrow_mono_delta()

    def schedule_next(self):
        """执行完成后的重调度（失败退避 / 时钟当天去重）。"""
        now = time.monotonic()
        if self.interval is not None:
            wait = compute_backoff(self.interval, self.failures,
                                   self.backoff_factor, self.backoff_max)
            self.next_run_at = now + wait
            return
        # 时钟模式：执行完成标记今天已执行，下次排到明天
        self._run_today = True
        self.next_run_at = now + self._tomorrow_mono_delta()

    def mark_done(self):
        """时钟模式手动标记今天已完成（如手动刷新），跳过今天的定时触发。"""
        if self.interval is None:
            self._run_today = True
            self.next_run_at = time.monotonic() + self._tomorrow_mono_delta()
