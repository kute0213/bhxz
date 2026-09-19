"""任务执行器 —— 到期任务的多种后台执行方式，tick 线程永不阻塞。

执行方式（由 ScheduledTask.mode 指定）：
  - 'pool'：共享守护线程池（默认）。高频轻量任务复用线程，开销最小
  - 'thread'：每次执行新建独立守护线程。低频长任务隔离执行，不占用共享池

防重叠：任务到期即从注册表取出，执行完成才重新入列，天然不会重叠执行。

线程均为 daemon，进程退出时不会被阻塞等待。
"""

import queue
import threading

from core.system.logger import log


class TaskExecutor:
    """轻量守护线程池执行器（可重启，幂等）。"""

    def __init__(self, pool_size=4):
        self._queue = queue.Queue()
        self._pool_size = max(1, int(pool_size))
        self._workers: list = []
        self._closed = False
        self._lock = threading.Lock()
        self.ensure_started()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def ensure_started(self):
        """确保 worker 线程存活（幂等；stop 后可重新拉起）。"""
        with self._lock:
            if self._workers and not self._closed:
                return
            self._closed = False
            self._workers = []
            for _ in range(self._pool_size):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name='sched-pool',
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

    def shutdown(self):
        """关闭线程池（幂等）：worker 处理完当前队列后退出。"""
        with self._lock:
            self._closed = True

    # ------------------------------------------------------------------
    # 派发
    # ------------------------------------------------------------------

    def submit(self, task, on_done):
        """派发一次执行；'thread' 模式每次新建独立守护线程。

        on_done(task, ok, error)：执行结束后回调（重调度 / 失败计数）。
        """
        with self._lock:
            if self._closed:
                return      # 执行器已关闭，丢弃本次派发
            thread_mode = task.mode == 'thread'
        if thread_mode:
            threading.Thread(
                target=self._run_task,
                args=(task, on_done),
                name=f'sched-{task.name}',
                daemon=True,
            ).start()
        else:
            self._queue.put((task, on_done))

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _worker_loop(self):
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                with self._lock:
                    if self._closed:
                        return
                continue
            task, on_done = item
            self._run_task(task, on_done)

    def _run_task(self, task, on_done):
        """执行回调，并把结果交给注册表做完成处理。"""
        ok, error = None, None
        try:
            task.running = True
            ok = task.action()
        except Exception as exc:
            error = exc
            log('ERROR', task.name, '任务执行异常', error=str(exc))
        finally:
            task.running = False
            try:
                on_done(task, ok, error)
            except Exception:
                pass
