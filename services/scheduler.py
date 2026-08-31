"""定时任务调度引擎。

后台线程定期扫描数据库中到期的任务，通过线程池异步执行命令，
执行完成后将输出写入 scheduled_task_logs 表。
"""

import datetime
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from config import (
    TASK_EXECUTOR_POOL_SIZE,
    get_config_value,
)
from core.db import get_db
from services.process_utils import run_process
from core.logger import log


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
        self._running_tasks = {}  # task_id -> started_at（时间戳），用于并发去重与运行中列表
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
        # 取消尚未开始的任务；正在执行的任务仍按原有超时策略自行结束。
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # 调度主循环
    # ------------------------------------------------------------------

    def _run_loop(self):
        """调度器主循环。

        每 1 秒判断一次（按到期时间排队），单次 _tick() 抛出的任何异常
        都被吞掉并记录，绝不影响后续判断——这是调度器高可用的关键。
        """
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log('ERROR', 'Scheduler', f'调度异常: {e}\n{traceback.format_exc()}')
            self._stop_event.wait(get_config_value('TASK_SCHEDULER_INTERVAL', 1))

    def _tick(self):
        """按到期时间顺序取出当期任务并提交执行。

        只勾选 next_run_at <= now 的任务，并按 next_run_at 升序排队，
        避免每次对整个任务表做全量扫描；配合 _running_tasks 去重，
        保证已提交执行的任务不会被重复判断。
        """
        now = datetime.datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')

        try:
            conn = get_db()
            try:
                tasks = conn.execute(
                    "SELECT * FROM scheduled_tasks WHERE is_enabled = 1 "
                    "AND next_run_at IS NOT NULL AND next_run_at <= ? "
                    "ORDER BY next_run_at ASC",
                    (now_str,),
                ).fetchall()
            finally:
                conn.close()
        except Exception as e:
            log('ERROR', 'Scheduler', f'判断到期任务失败: {e}\n{traceback.format_exc()}')
            return

        for task in tasks:
            task_id = task['id']
            with self._running_lock:
                if task_id in self._running_tasks:
                    continue
                self._running_tasks[task_id] = time.time()

            try:
                self._executor.submit(self._execute_task, dict(task))
            except Exception as e:
                # 线程池已关闭 / 拒绝提交：回滚 _running_tasks 状态，避免任务卡死
                log('ERROR', 'Scheduler', f'提交任务 #{task_id} 失败: {e}')
                with self._running_lock:
                    self._running_tasks.pop(task_id, None)

    # ------------------------------------------------------------------
    # 运行中任务列表
    # ------------------------------------------------------------------

    def get_running_tasks(self):
        """返回当前正在执行的任务列表（含开始时间）。

        Returns:
            list[dict]: [{'task_id': int, 'name': str, 'started_at': str}]
        """
        ids_with_time = []
        with self._running_lock:
            for tid, started in self._running_tasks.items():
                ids_with_time.append((tid, started))

        result = []
        if not ids_with_time:
            return result

        conn = None
        try:
            conn = get_db()
            for tid, started in ids_with_time:
                row = conn.execute(
                    "SELECT name FROM scheduled_tasks WHERE id = ?", (tid,)
                ).fetchone()
                if row:
                    result.append({
                        'task_id': tid,
                        'name': row['name'],
                        'started_at': datetime.datetime.fromtimestamp(
                            started
                        ).strftime('%Y-%m-%d %H:%M:%S'),
                    })
        except Exception as e:
            log('ERROR', 'Scheduler', f'读取运行中任务失败: {e}')
        finally:
            if conn is not None:
                conn.close()
        return result

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------

    def _execute_task(self, task: dict, no_timeout=False):
        """在子线程中执行单个定时任务。

        no_timeout=True 表示「直接运行」：不受超时限制，一直执行到结束
        （用户启动自定义脚本的长时任务）。普通定时任务仍按 timeout_seconds
        或全局默认超时执行。

        任何异常（执行 / 日志 / 调度更新）都被吞掉并记录，
        确保单个任务的失败不影响线程池中其他任务，也不影响调度主循环。
        """
        task_id = task['id']
        started_at = datetime.datetime.now()
        started_str = started_at.strftime('%Y-%m-%d %H:%M:%S')

        task_type = 'shell'

        success = False
        output = ''
        exit_code = None
        finished_at = None
        # 实际执行的命令内容，用于日志记录（保持与执行内容一致）
        executed_command = task.get('command') or ''

        try:
            # 优先从 cmd_commands 表读取最新命令内容
            # （确保快捷命令更新后任务也用最新版本）
            command_id = task.get('command_id')
            cmd_content = None
            if command_id:
                try:
                    conn = get_db()
                    try:
                        cmd_row = conn.execute(
                            "SELECT command FROM cmd_commands WHERE id = ?",
                            (command_id,),
                        ).fetchone()
                        if cmd_row:
                            cmd_content = cmd_row['command']
                    finally:
                        conn.close()
                except Exception as e:
                    log('ERROR', 'Scheduler', f'任务 #{task_id} 读取快捷命令失败: {e}')

            # 决定任务类型（强制为 shell）
            if not cmd_content:
                # 回退到 command 字段（任务创建时的快照）
                cmd_content = task.get('command') or ''

            # 记录实际执行的命令
            executed_command = cmd_content

            log('INFO', 'Scheduler', f"执行任务 #{task_id} '{task['name']}': {executed_command}")

            proc_result = run_process(
                cmd_content,
                cwd=os.getcwd(),
                # 直接运行不受超时限制；定时任务用 timeout_seconds 或全局默认
                timeout=None if no_timeout else (
                    task.get('timeout_seconds')
                    or get_config_value('TASK_EXECUTION_TIMEOUT', 300)
                ),
            )
            output = proc_result['stdout'] + proc_result['stderr']
            exit_code = proc_result['returncode']
            success = proc_result['success']
        except Exception as e:
            output = f'执行异常: {e}\n{traceback.format_exc()}'
            exit_code = -1
            success = False
            log('ERROR', 'Scheduler', f'任务 #{task_id} 执行异常: {e}')
        finally:
            # 收尾阶段独立 try：日志/调度更新失败不能阻止 _running_tasks 清理
            try:
                finished_at = datetime.datetime.now()
                duration = (finished_at - started_at).total_seconds()
                self._log_task_result(
                    task, executed_command, output, exit_code, success,
                    started_str, finished_at.strftime('%Y-%m-%d %H:%M:%S'),
                    duration,
                )
                self._update_task_schedule(task, finished_at)
            except Exception as e:
                log('ERROR', 'Scheduler', f'任务 #{task_id} 收尾失败: {e}\n{traceback.format_exc()}')
            finally:
                # 关键：无论收尾是否成功，必须从 _running_tasks 移除，
                # 否则该任务将永远无法被再次调度
                with self._running_lock:
                    self._running_tasks.pop(task_id, None)

    def _log_task_result(self, task, executed_command, output, exit_code, success,
                         started_str, finished_str, duration):
        """记录任务执行结果到数据库。

        Args:
            executed_command: 实际执行的命令内容（保持与执行内容一致，
                              避免日志记录的是任务创建时的旧快照）
        """
        # 截断过长的输出
        if len(output) > 10000:
            output = output[:10000] + '\n...(输出已截断)'

        # 截断过长的命令内容，避免日志膨胀
        log_command = executed_command or task.get('command') or ''
        if len(log_command) > 2000:
            log_command = log_command[:2000] + '\n...(命令已截断)'

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO scheduled_task_logs "
                "(task_id, task_name, command, output, exit_code, success, "
                " started_at, finished_at, duration_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task['id'], task['name'], log_command,
                    output, exit_code, success,
                    started_str, finished_str, duration,
                ),
            )
            conn.commit()
        except Exception as e:
            log('ERROR', 'Scheduler', f'记录日志失败: {e}')
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
            log('ERROR', 'Scheduler', f'更新任务调度失败: {e}')
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 调度时间计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_next_run(task: dict, base: datetime.datetime) -> str:
        """根据任务类型计算下次执行时间（执行后调用，用于安排下一次）。

        注意：'once' 类型在执行后返回 None（自动禁用）。
        创建任务时的初始执行时间请使用 calc_initial_next_run。
        """
        schedule_type = task['schedule_type']

        if schedule_type == 'once':
            # 一次性任务执行后不再安排下次
            return None

        if schedule_type == 'interval':
            seconds = task['interval_seconds'] or 3600
            next_time = base + datetime.timedelta(seconds=seconds)
            return next_time.strftime('%Y-%m-%d %H:%M:%S')

        if schedule_type == 'daily':
            execute_at = task['execute_at'] or '00:00'
            try:
                hour, minute = map(int, execute_at.split(':')[:2])
            except (ValueError, AttributeError):
                # 格式无效时返回 None 而非静默降级为 0:00
                log('WARNING', 'Scheduler', f'任务 #{task.get("id", "?")} execute_at 格式无效: {execute_at!r}，跳过调度')
                return None
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                # 时间值越界也视为无效
                log('WARNING', 'Scheduler', f'任务 #{task.get("id", "?")} execute_at 时间越界: {execute_at!r}，跳过调度')
                return None
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
        """创建/更新/启用任务时计算初始下次执行时间。

        对于 'once' 类型，使用 execute_at 作为初始执行时间；
        若 execute_at 为空或已过期，返回 None（任务无法调度）。
        """
        now = datetime.datetime.now()

        if schedule_type == 'once':
            # 一次性任务：使用 execute_at 作为初始执行时间
            if not execute_at:
                return None
            # 兼容 "YYYY-MM-DD HH:MM:SS" 和 "HH:MM" 两种格式
            try:
                # 尝试完整日期时间格式
                target = datetime.datetime.strptime(
                    execute_at, '%Y-%m-%d %H:%M:%S'
                )
            except ValueError:
                try:
                    # 尝试日期时间无秒格式
                    target = datetime.datetime.strptime(
                        execute_at, '%Y-%m-%d %H:%M'
                    )
                except ValueError:
                    try:
                        # 仅时间格式（今日或明日）
                        hour, minute = map(int, execute_at.split(':')[:2])
                        target = now.replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                        if target <= now:
                            target += datetime.timedelta(days=1)
                    except (ValueError, AttributeError):
                        return None
            # 过去时间不再调度，避免重新启用已执行过的 once 任务时立即触发
            if target <= now:
                return None
            return target.strftime('%Y-%m-%d %H:%M:%S')

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
        try:
            conn = get_db()
            try:
                task = conn.execute(
                    "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
                ).fetchone()
            finally:
                conn.close()
        except Exception as e:
            log('ERROR', 'Scheduler', f'触发查询失败 #{task_id}: {e}')
            return False

        if not task:
            return False

        with self._running_lock:
            if task_id in self._running_tasks:
                return False
            self._running_tasks[task_id] = time.time()

        try:
            # 直接运行（立即执行）：不受超时限制，一直执行到结束
            self._executor.submit(self._execute_task, dict(task), no_timeout=True)
        except Exception as e:
            # 线程池已关闭 / 拒绝提交：回滚状态
            log('ERROR', 'Scheduler', f'触发提交失败 #{task_id}: {e}')
            with self._running_lock:
                self._running_tasks.pop(task_id, None)
            return False
        return True


# 全局单例
scheduler = TaskScheduler()
