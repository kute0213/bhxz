"""定时任务调度引擎。

后台线程定期扫描数据库中到期的任务，通过线程池异步执行命令，
执行完成后将输出写入 scheduled_task_logs 表。
"""

import datetime
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from config import (
    TASK_SCHEDULER_INTERVAL,
    TASK_EXECUTION_TIMEOUT,
    TASK_EXECUTOR_POOL_SIZE,
)
from core.database import get_db


class TaskScheduler:
    """定时任务调度器，单例模式。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._thread = None
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=TASK_EXECUTOR_POOL_SIZE,
            thread_name_prefix='task-exec',
        )
        self._running_tasks = set()
        self._running_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name='task-scheduler', daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # 调度主循环
    # ------------------------------------------------------------------

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f'[Scheduler] 调度异常: {e}', flush=True)
            self._stop_event.wait(TASK_SCHEDULER_INTERVAL)

    def _tick(self):
        """扫描到期任务并提交执行。"""
        now = datetime.datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db()
        try:
            tasks = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE is_enabled = 1 AND next_run_at <= ?",
                (now_str,),
            ).fetchall()
        finally:
            conn.close()

        for task in tasks:
            task_id = task['id']
            with self._running_lock:
                if task_id in self._running_tasks:
                    continue
                self._running_tasks.add(task_id)

            self._executor.submit(self._execute_task, dict(task))

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------

    def _execute_task(self, task: dict):
        """在子线程中执行单个定时任务。"""
        task_id = task['id']
        started_at = datetime.datetime.now()
        started_str = started_at.strftime('%Y-%m-%d %H:%M:%S')

        print(f"[Scheduler] 执行任务 #{task_id} '{task['name']}': {task['command']}", flush=True)

        success = False
        output = ''
        exit_code = None

        try:
            result = subprocess.run(
                task['command'],
                shell=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=TASK_EXECUTION_TIMEOUT,
            )
            output = (result.stdout or '') + (result.stderr or '')
            exit_code = result.returncode
            success = result.returncode == 0
        except subprocess.TimeoutExpired:
            output = f'执行超时（>{TASK_EXECUTION_TIMEOUT}秒）'
        except Exception as e:
            output = f'执行异常: {e}'
        finally:
            finished_at = datetime.datetime.now()
            duration = (finished_at - started_at).total_seconds()
            self._log_task_result(
                task, output, exit_code, success,
                started_str, finished_at.strftime('%Y-%m-%d %H:%M:%S'),
                duration,
            )
            self._update_task_schedule(task, finished_at)
            with self._running_lock:
                self._running_tasks.discard(task_id)

    def _log_task_result(self, task, output, exit_code, success,
                         started_str, finished_str, duration):
        """记录任务执行结果到数据库。"""
        # 截断过长的输出
        if len(output) > 10000:
            output = output[:10000] + '\n...(输出已截断)'

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO scheduled_task_logs "
                "(task_id, task_name, command, output, exit_code, success, "
                " started_at, finished_at, duration_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task['id'], task['name'], task['command'],
                    output, exit_code, success,
                    started_str, finished_str, duration,
                ),
            )
            conn.commit()
        except Exception as e:
            print(f'[Scheduler] 记录日志失败: {e}', flush=True)
        finally:
            conn.close()

    def _update_task_schedule(self, task: dict, finished_at: datetime.datetime):
        """更新任务的下次执行时间。"""
        now_str = finished_at.strftime('%Y-%m-%d %H:%M:%S')
        next_run = self._calc_next_run(task, finished_at)

        conn = get_db()
        try:
            if next_run is None:
                # 一次性任务，执行后自动禁用
                conn.execute(
                    "UPDATE scheduled_tasks SET last_run_at = ?, next_run_at = NULL, "
                    "is_enabled = 0, run_count = run_count + 1 WHERE id = ?",
                    (now_str, task['id']),
                )
            else:
                conn.execute(
                    "UPDATE scheduled_tasks SET last_run_at = ?, next_run_at = ?, "
                    "run_count = run_count + 1 WHERE id = ?",
                    (now_str, next_run, task['id']),
                )
            conn.commit()
        except Exception as e:
            print(f'[Scheduler] 更新任务调度失败: {e}', flush=True)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 调度时间计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_next_run(task: dict, base: datetime.datetime) -> str:
        """根据任务类型计算下次执行时间。"""
        schedule_type = task['schedule_type']

        if schedule_type == 'once':
            return None  # 一次性任务不需要下次执行时间

        if schedule_type == 'interval':
            seconds = task['interval_seconds'] or 3600
            next_time = base + datetime.timedelta(seconds=seconds)
            return next_time.strftime('%Y-%m-%d %H:%M:%S')

        if schedule_type == 'daily':
            execute_at = task['execute_at'] or '00:00'
            try:
                hour, minute = map(int, execute_at.split(':'))
            except (ValueError, AttributeError):
                hour, minute = 0, 0
            next_time = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_time <= base:
                next_time += datetime.timedelta(days=1)
            return next_time.strftime('%Y-%m-%d %H:%M:%S')

        # 默认间隔1小时
        next_time = base + datetime.timedelta(hours=1)
        return next_time.strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def calc_initial_next_run(schedule_type: str, interval_seconds: int = 3600,
                              execute_at: str = None) -> str:
        """创建任务时计算初始下次执行时间。"""
        now = datetime.datetime.now()
        return TaskScheduler._calc_next_run(
            {
                'schedule_type': schedule_type,
                'interval_seconds': interval_seconds,
                'execute_at': execute_at,
            },
            now,
        )

    # ------------------------------------------------------------------
    # 手动触发
    # ------------------------------------------------------------------

    def trigger_now(self, task_id: int):
        """手动触发某个任务立即执行。"""
        conn = get_db()
        try:
            task = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        finally:
            conn.close()

        if not task:
            return False

        with self._running_lock:
            if task_id in self._running_tasks:
                return False
            self._running_tasks.add(task_id)

        self._executor.submit(self._execute_task, dict(task))
        return True


# 全局单例
scheduler = TaskScheduler()
