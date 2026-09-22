"""统一调度模块测试 —— 时间计算、注册表派发、执行隔离、失败处理。

运行：pytest scripts/tests/test_scheduler.py
"""

import threading
import time
from datetime import datetime, timedelta

import pytest

from utils.shared.scheduler import register_task, unregister_task
from utils.shared.scheduler.executors import TaskExecutor
from utils.shared.scheduler.registry import TaskRegistry
from utils.shared.scheduler.task import ScheduledTask, compute_backoff, parse_clock_time


# ---------------------------------------------------------------------------
# 纯算法：时间解析 / 退避
# ---------------------------------------------------------------------------

class TestClockParsing:

    @pytest.mark.parametrize('value,expected', [
        ('03:00', (3, 0)),
        ('23:59', (23, 59)),
        ('9:5', (9, 5)),
        ('12', (12, 0)),
        ('', (3, 0)),
        (None, (3, 0)),
        ('abc', (3, 0)),
        ('99:99', (23, 59)),
    ])
    def test_parse_clock_time(self, value, expected):
        assert parse_clock_time(value) == expected


class TestBackoff:

    @pytest.mark.parametrize('interval,failures,factor,cap,expected', [
        (60, 0, 5.0, 60.0, 60),
        (60, 3, 0, 0, 60),          # 未启用退避
        (60, 3, 5.0, 0, 75),        # 不封顶
        (60, 3, 5.0, 70, 70),       # 封顶
        (60, 3, 5.0, 60, 60),       # 封顶等于基准
    ])
    def test_compute_backoff(self, interval, failures, factor, cap, expected):
        assert compute_backoff(interval, failures, factor, cap) == expected


# ---------------------------------------------------------------------------
# ScheduledTask：时间计算
# ---------------------------------------------------------------------------

def _is_past_today(hour, minute, now):
    return now.hour > hour or (now.hour == hour and now.minute >= minute)


class TestScheduledTask:

    def test_requires_schedule_mode(self):
        with pytest.raises(ValueError):
            ScheduledTask('x', lambda: True)

    def test_default_run_immediately(self):
        assert ScheduledTask('a', lambda: True, interval=10).run_immediately is True
        assert ScheduledTask('b', lambda: True, run_at='03:00').run_immediately is False

    def test_interval_first_and_next(self):
        task = ScheduledTask('i', lambda: True, interval=10, run_immediately=True)
        task.schedule_first()
        assert task.next_run_at <= time.monotonic()          # 立即触发
        task.schedule_next()
        assert task.next_run_at >= time.monotonic() + 9.5    # 10 秒后
        task.failures = 2
        task.schedule_next()                                 # 未配置退避 → 间隔不变
        assert task.next_run_at >= time.monotonic() + 9.5

    def test_interval_with_backoff(self):
        task = ScheduledTask('b', lambda: True, interval=10,
                             run_immediately=False, backoff_factor=5.0, backoff_max=20.0)
        task.schedule_first()
        assert task.next_run_at >= time.monotonic() + 9.5
        task.failures = 2
        task.schedule_next()
        assert task.next_run_at >= time.monotonic() + 19.5   # 10 + 2*5，封顶 20

    def test_clock_future_time(self):
        now = datetime.now()
        target = now + timedelta(minutes=30)
        task = ScheduledTask('clock-f', lambda: True, run_at=target.strftime('%H:%M'),
                             run_immediately=False)
        task.schedule_first()
        remaining = task.next_run_at - time.monotonic()
        if target.date() == now.date():
            # 目标时刻在今天未来 → 排期到该时刻
            assert 29 * 60 - 2 < remaining <= 31 * 60
        else:
            # 午夜边界：格式化后的时刻今天已过 → 补执行一次
            assert remaining <= 0.1

    def test_clock_past_time_completes_once(self):
        now = datetime.now()
        past = now - timedelta(minutes=30)
        hour, minute = past.hour, past.minute
        task = ScheduledTask('clock-p', lambda: True, run_at=f'{hour:02d}:{minute:02d}',
                             run_immediately=False)
        task.schedule_first()
        if _is_past_today(hour, minute, now):
            assert task.next_run_at <= time.monotonic() + 0.01   # 当天时刻已过 → 补执行
            task.schedule_next()                                 # 执行完成后顺延到明天
            assert task.next_run_at > time.monotonic() + 12 * 3600
        else:
            # 午夜边界：该时刻实际在今天未来 → 正常排期
            assert task.next_run_at > time.monotonic()

    def test_clock_mark_done_skips_today(self):
        now = datetime.now()
        target = now + timedelta(minutes=30)
        task = ScheduledTask('clock-m', lambda: True, run_at=target.strftime('%H:%M'),
                             run_immediately=False)
        task.schedule_first()
        task.mark_done()                                         # 手动完成后跳过当天
        assert task.next_run_at > time.monotonic() + 12 * 3600


# ---------------------------------------------------------------------------
# TaskRegistry：注册 / 派发 / 失败 / 注销
# ---------------------------------------------------------------------------

def _make_registry(tick=0.05):
    return TaskRegistry(executor=TaskExecutor(pool_size=2), tick=tick)


class TestTaskRegistry:

    def test_duplicate_register_raises(self):
        reg = _make_registry()
        reg.register(ScheduledTask('dup', lambda: True, interval=60, run_immediately=False))
        with pytest.raises(ValueError):
            reg.register(ScheduledTask('dup', lambda: True, interval=60, run_immediately=False))

    def test_unregister_unknown_returns_false(self):
        reg = _make_registry()
        assert reg.unregister('no-such-task') is False

    def test_dispatch_repeats(self):
        reg = _make_registry()
        counter = {'n': 0}
        lock = threading.Lock()

        def action():
            with lock:
                counter['n'] += 1
            return True

        task = ScheduledTask('repeat', action, interval=0.1, run_immediately=False)
        reg.register(task)
        reg.start()
        time.sleep(0.55)
        reg.stop()
        with lock:
            n = counter['n']
        assert n >= 3                       # 0.55 秒内按 0.1 秒间隔应执行多次
        assert not task.removed
        assert task.next_run_at > time.monotonic()   # 执行完成后已重排

    def test_failure_counting(self):
        reg = _make_registry()
        task = ScheduledTask('fail', lambda: False, interval=0.1, run_immediately=True)
        reg.register(task)
        reg.start()
        time.sleep(0.45)
        reg.stop()
        assert task.failures >= 3           # 返回 False 记为失败

    def test_thread_mode_runs(self):
        reg = _make_registry()
        called = threading.Event()

        def action():
            called.set()
            return True

        task = ScheduledTask('thread', action, interval=0.1, run_immediately=True, mode='thread')
        reg.register(task)
        reg.start()
        assert called.wait(1)
        reg.stop()

    def test_unregister_during_run_skips_reschedule(self):
        reg = _make_registry()
        started = threading.Event()
        release = threading.Event()
        calls = {'n': 0}

        def action():
            calls['n'] += 1
            started.set()
            release.wait(2)
            return True

        task = ScheduledTask('during', action, interval=0.1, run_immediately=True)
        reg.register(task)
        reg.start()
        assert started.wait(1)              # 任务已在执行
        assert reg.unregister('during') is True
        release.set()
        time.sleep(0.4)
        reg.stop()
        assert calls['n'] == 1              # 执行完成后不再重排，不再触发
        assert task.removed is True


# ---------------------------------------------------------------------------
# 全局 API
# ---------------------------------------------------------------------------

class TestGlobalAPI:

    def test_register_and_unregister(self):
        calls = {'n': 0}

        def action():
            calls['n'] += 1
            return True

        task = register_task('api-test', action, interval=60, run_immediately=False)
        assert task.name == 'api-test'
        assert unregister_task('api-test') is True
        assert unregister_task('api-test') is False
