"""统一任务注册表 —— 时间有序、每秒检测、到期派发（tick 线程永不阻塞）。

数据组织：
  - `_tasks`：按 `next_run_at` 升序排列的有序表（队首即最早到期任务）
  - tick 线程每秒检测一次：队首任务到期 → 取出派发 → 继续检查下一个；
    队首未到期说明其后所有任务都未到期，直接进入下一轮等待
  - 任务执行期间不在表中（防重叠），执行完成由 on_done 回调重新入列

性能：
  - tick 只做 O(1) 队首比较 + 批量取出，不持有锁执行任务
  - 执行交给 TaskExecutor（共享线程池 / 独立线程），tick 线程永不阻塞
  - 有序插入用 bisect，任务数量通常 < 20，开销可忽略
"""

import bisect
import threading
import time

from core.system.logger import log
from utils.shared.scheduler.executors import TaskExecutor


class TaskRegistry:
    """统一任务注册表（全局单例，全站共享一个 tick 线程与线程池）。"""

    def __init__(self, executor=None, tick=1.0):
        self._tasks: list = []            # 按 next_run_at 升序
        self._by_name: dict = {}          # name -> ScheduledTask（禁止重复注册）
        self._lock = threading.Lock()
        self._executor = executor or TaskExecutor(pool_size=4)
        self._tick = max(0.05, float(tick))
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------
    # 注册 / 注销
    # ------------------------------------------------------------------

    def register(self, task):
        """注册一个已构造的任务并完成首次排期；返回任务本身。

        Raises:
            ValueError: 同名任务已注册
        """
        with self._lock:
            if task.name in self._by_name:
                raise ValueError(f'任务已注册: {task.name}')
            task.schedule_first()
            self._by_name[task.name] = task
            self._insert_locked(task)
        log('INFO', 'TaskRegistry', '任务已注册', name=task.name)
        return task

    def unregister(self, name) -> bool:
        """注销任务：立即从注册表移除；执行中的任务结束后不再重排。"""
        with self._lock:
            task = self._by_name.pop(name, None)
            if task is None:
                return False
            task.removed = True
            self._tasks = [t for t in self._tasks if t is not task]
        log('INFO', 'TaskRegistry', '任务已注销', name=name)
        return True

    def get(self, name):
        """按名称获取任务句柄；未注册返回 None。"""
        with self._lock:
            return self._by_name.get(name)

    # ------------------------------------------------------------------
    # 生命周期（幂等）
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """启动 tick 线程；已运行时返回 False。"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._tick_loop, name='task-registry', daemon=True)
            self._thread.start()
        return True

    def stop(self):
        """停止 tick 线程与执行器（幂等；执行中的任务不被中断）。"""
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._executor.shutdown()

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def pending_count(self) -> int:
        """当前等待执行的任务数（执行中/已注销的不计）。"""
        with self._lock:
            return len(self._tasks)

    # ------------------------------------------------------------------
    # tick 检测（每秒）
    # ------------------------------------------------------------------

    def _tick_loop(self):
        while not self._stop.wait(self._tick):
            self._dispatch_due()

    def _dispatch_due(self):
        """取出所有已到期任务并派发（排序保证队首即最早到期）。"""
        now = time.monotonic()
        due = []
        with self._lock:
            while self._tasks and self._tasks[0].next_run_at <= now:
                task = self._tasks.pop(0)
                if task.removed:
                    continue
                due.append(task)
        for task in due:
            self._executor.submit(task, self._on_done)

    def _on_done(self, task, ok, error):
        """执行完成：更新失败计数并按调度模式重排（执行期间注销则丢弃）。"""
        if task.removed:
            return
        if error is not None or ok is False:
            task.failures += 1
        else:
            task.failures = 0
        task.schedule_next()
        with self._lock:
            if task.removed:
                return
            self._insert_locked(task)

    def _insert_locked(self, task):
        keys = [t.next_run_at for t in self._tasks]
        self._tasks.insert(bisect.bisect(keys, task.next_run_at), task)
