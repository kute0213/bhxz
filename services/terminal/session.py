"""持久终端会话。

封装单个 shell 子进程的状态、输入输出处理与生命周期。
"""

import threading
import time

from core.process_utils import decode_output


class TerminalSession:
    """单个持久 shell 会话。"""

    def __init__(self, sid, shell_type, proc_manager, init_commands):
        """初始化会话。

        Args:
            sid: 会话唯一标识
            shell_type: shell 类型，如 'cmd' / 'bash'
            proc_manager: ProcessManager 实例
            init_commands: 启动后需发送的初始化命令列表
        """
        self.sid = sid
        self.shell_type = shell_type
        self._proc_manager = proc_manager
        self.init_commands = init_commands

        self.last_active = time.time()
        self.created_at = time.time()
        self.closed = False
        self.error = None
        self.generation = 0

        self._output_queue = []
        self._output_event = threading.Event()
        self._lock = threading.Lock()

        self._reader_thread = threading.Thread(
            target=self._read_output_loop,
            daemon=True,
        )
        self._reader_thread.start()

        # 发送初始化命令，让 shell 进入可用状态
        for cmd in init_commands:
            self.send_input(cmd)
            time.sleep(0.05)

    def _read_output_loop(self):
        """后台线程：持续读取 shell 输出并放入队列。"""
        while not self.closed:
            try:
                data = self._proc_manager.read_output(4096)
                if not data:
                    break
                text = decode_output(data)
                with self._lock:
                    self._output_queue.append(text)
                    self._output_event.set()
            except Exception as e:
                if not self.closed:
                    with self._lock:
                        self._output_queue.append(
                            f'\r\n[终端读取错误: {e}]\r\n'
                        )
                        self._output_event.set()
                break

        self.closed = True
        with self._lock:
            self._output_event.set()

    def send_input(self, text):
        """向 shell 发送输入。

        Returns:
            bool: 是否发送成功
        """
        if self.closed:
            return False
        ok = self._proc_manager.send_input(text)
        if ok:
            self.touch()
        return ok

    def read_pending_output(self):
        """读取并清空待发送的输出队列。

        Returns:
            list[str]: 输出块列表
        """
        with self._lock:
            chunks = self._output_queue
            self._output_queue = []
            self._output_event.clear()
            return chunks

    def wait_output(self, timeout=2.0):
        """等待输出事件或超时。

        Returns:
            bool: True 表示有数据或会话结束，False 表示超时
        """
        if self.closed:
            return True
        return self._output_event.wait(timeout=timeout)

    def touch(self):
        """更新最后活动时间。"""
        self.last_active = time.time()

    def next_generation(self):
        """递增并返回新的 generation 值。

        用于 SSE 连接独占：旧连接检测到 generation 变化后应主动退出，
        避免多个 SSE 连接同时消费同一个会话的输出队列。
        """
        with self._lock:
            self.generation += 1
            return self.generation

    def is_alive(self):
        """会话是否仍然存活。"""
        if self.closed:
            return False
        return self._proc_manager.is_running()

    def close(self):
        """关闭会话并释放资源。"""
        self.closed = True
        self._proc_manager.cleanup()
        reader = self._reader_thread
        if reader and reader.is_alive():
            reader.join(timeout=2)
