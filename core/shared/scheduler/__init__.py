"""统一任务调度模块 —— 全站所有定时执行功能的唯一入口。

架构（core/shared/scheduler/）：
  - task.py      ScheduledTask：任务定义 + 时间计算 + 失败退避（纯算法，不含线程）
  - executors.py TaskExecutor：到期任务的两种后台执行方式（线程池 / 独立线程）
  - registry.py  TaskRegistry：时间有序注册表，每秒检测到期任务并派发

特性：
  - 按下次执行时间排序，每秒检测队首（最早到期）任务，到期即派发并检查下一个
  - 派发不阻塞：执行走后台线程池（pool）/ 独立线程（thread），tick 永不阻塞
  - 防重叠：任务到期即从注册表取出，执行完成才重新入列
  - 固定间隔（含失败退避）与每日时间点两种调度模式
  - 防火墙（core/firewall）不使用本模块，保持独立实现

用法：
    from core.shared.scheduler import (
        register_task, unregister_task, start_task_scheduler, stop_task_scheduler,
    )

    task = register_task('my-task', action=my_func, interval=60)
    ...
    unregister_task('my-task')
"""

from core.shared.scheduler.executors import TaskExecutor
from core.shared.scheduler.registry import TaskRegistry
from core.shared.scheduler.task import ScheduledTask

# 全局单例：全站共享一个 tick 线程与执行线程池
registry = TaskRegistry()


def register_task(name, action, *, interval=None, run_at=None,
                  run_immediately=None, backoff_factor=0.0, backoff_max=0.0,
                  mode='pool') -> ScheduledTask:
    """注册一个定时任务到统一注册表，返回任务句柄。

    Args:
        name: 任务唯一名称（重复注册抛 ValueError）
        action: 任务回调；返回 False 或抛异常记为一次失败（用于退避）
        interval: 固定间隔（秒），与 run_at 二选一
        run_at: 每日时间点 "HH:MM"，或返回该字符串的可调用对象（热重载）
        run_immediately: True 注册后立即触发；None 时按模式自动选择
        backoff_factor / backoff_max: 失败退避（interval 模式）
        mode: 'pool' 共享线程池（默认）/ 'thread' 独立线程

    Returns:
        任务句柄，可调用 mark_done() 跳过当天时钟触发。
    """
    task = ScheduledTask(
        name, action, interval=interval, run_at=run_at,
        run_immediately=run_immediately,
        backoff_factor=backoff_factor, backoff_max=backoff_max, mode=mode,
    )
    return registry.register(task)


def unregister_task(name) -> bool:
    """从统一注册表注销任务；执行中的任务结束后不再重排。"""
    return registry.unregister(name)


def start_task_scheduler() -> bool:
    """启动统一注册表 tick 线程（幂等；全站启动时调用一次）。"""
    return registry.start()


def stop_task_scheduler():
    """停止统一注册表 tick 线程与执行器（幂等；进程退出时调用）。"""
    registry.stop()
