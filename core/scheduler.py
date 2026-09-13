"""统一定时调度算法 —— 只提供「调度机制」，不包含任何具体业务。

支持两种调度模式（由构造参数决定）：
  1. 固定间隔模式（interval）：每 interval 秒执行一次；连续失败时可按退避算法延长间隔
  2. 时间点模式（run_at）：每天在指定时刻 HH:MM 执行一次（当天去重）

通用特性：
  - 优雅停止：threading.Event 停止信号 + 分片等待，停止信号及时响应
  - 失败计数：action 抛异常或返回 False 记为一次失败，用于退避与排障
  - 线程管理：后台守护线程，start / stop / is_running 幂等接口

用法：
    scheduler = Scheduler('my-task', action=my_func, interval=60)
    scheduler.start()
    ...
    scheduler.stop()

约定：
  - action 为具体业务回调，本模块不关心其内容，只负责调度；
    返回 False 或抛异常视为一次失败，其余视为成功。
  - run_at 支持 "HH:MM" 字符串或返回该字符串的可调用对象（支持动态读取配置）。
"""

import threading
from datetime import datetime

from core.logger import log


# ---------------------------------------------------------------------------
# 纯算法函数
# ---------------------------------------------------------------------------

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


def is_clock_time_reached(hour, minute, now=None):
    """当前时间是否已达到目标时刻 (hour, minute)。"""
    now = now or datetime.now()
    return now.hour > hour or (now.hour == hour and now.minute >= minute)


def wait_chunked(stop_event, seconds, chunk=1.0):
    """分片等待：将长等待拆为 chunk 秒的短等待，等待期间及时响应停止信号。

    基于 Event.wait 实现，停止信号置位时立即返回，比 time.sleep 更及时。
    """
    waited = 0.0
    while waited < seconds:
        step = min(chunk, seconds - waited)
        if stop_event.wait(step):
            return
        waited += step


def compute_backoff(base_interval, failures, factor=0.0, max_interval=0.0):
    """失败退避算法：base + failures * factor，封顶 max_interval。

    factor 或 max_interval 为 0 时表示不启用退避，恒返回 base_interval。
    """
    if failures <= 0 or factor <= 0:
        return base_interval
    upper = max_interval if max_interval > 0 else float('inf')
    return min(base_interval + failures * factor, upper)


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------

class Scheduler:
    """统一定时调度器（算法层）。

    Args:
        name: 调度器名称（线程名与日志标识）
        action: 任务回调；返回 False 或抛异常记为一次失败，其余视为成功
        interval: 固定间隔（秒），与 run_at 二选一；同时给出时优先 interval
        run_at: 时间点 "HH:MM"，或返回该字符串的可调用对象；每天至多执行一次
        run_immediately: True 启动后立即执行一次；None 时按模式自动选择
                         （间隔模式默认立即执行，时间点模式默认等待）
        stop_event: 外部停止信号，None 时内部创建
        backoff_factor: 退避系数（每次失败增加的秒数），0 表示不启用
        backoff_max: 退避上限（秒），0 表示不封顶
        tick: 等待分片粒度（秒），同时作为时间点模式的检查周期
    """

    def __init__(self, name, action, *, interval=None, run_at=None,
                 run_immediately=None, stop_event=None,
                 backoff_factor=0.0, backoff_max=0.0, tick=1.0):
        if interval is None and run_at is None:
            raise ValueError('interval 与 run_at 至少指定一个')
        self._name = name
        self._action = action
        self._interval = interval
        self._run_at = run_at
        self._backoff_factor = backoff_factor
        self._backoff_max = backoff_max
        self._tick = tick
        if run_immediately is None:
            run_immediately = interval is not None
        self._run_immediately = run_immediately
        self._stop = stop_event or threading.Event()
        self._thread = None
        self._failures = 0          # 连续失败次数（退避依据）
        self._last_run_date = None  # 时间点模式：上次执行日期，避免当天重复

    # ------------------------------------------------------------------
    # 生命周期（幂等）
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """启动后台线程；已运行时返回 False。"""
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._failures = 0
        self._thread = threading.Thread(
            target=self._run, name=self._name, daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        """停止后台线程并等待其退出（幂等）。"""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def failures(self) -> int:
        """当前连续失败次数。"""
        return self._failures

    def mark_done(self):
        """标记当前周期已完成（时间点模式下当天不再重复执行）。"""
        self._last_run_date = datetime.now().strftime('%Y-%m-%d')

    # ------------------------------------------------------------------
    # 调度循环（算法核心）
    # ------------------------------------------------------------------

    def _run(self):
        if self._run_immediately:
            self._execute()
        while not self._stop.is_set():
            if self._interval is not None:
                # 固定间隔模式：按退避后的间隔等待，然后执行
                wait_seconds = compute_backoff(
                    self._interval, self._failures,
                    self._backoff_factor, self._backoff_max,
                )
                wait_chunked(self._stop, wait_seconds, self._tick)
                if self._stop.is_set():
                    break
                self._execute()
            else:
                # 时间点模式：按 tick 周期检查，命中且当天未执行时触发
                wait_chunked(self._stop, self._tick, self._tick)
                if self._stop.is_set():
                    break
                self._check_clock()

    def _check_clock(self):
        spec = self._run_at() if callable(self._run_at) else self._run_at
        hour, minute = parse_clock_time(spec)
        now = datetime.now()
        if not is_clock_time_reached(hour, minute, now):
            return
        today = now.strftime('%Y-%m-%d')
        if self._last_run_date == today:
            return
        self._last_run_date = today
        self._execute()

    def _execute(self):
        """执行一次任务并更新失败计数（异常或返回 False 记为失败）。"""
        try:
            ok = self._action()
        except Exception as e:
            self._failures += 1
            log('ERROR', self._name, '任务执行异常', error=str(e))
            return
        if ok is False:
            self._failures += 1
        else:
            self._failures = 0
