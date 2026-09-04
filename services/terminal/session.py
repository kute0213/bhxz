"""持久终端会话。

封装单个 shell 子进程的状态、输入输出处理与生命周期。
"""

import re
import threading
import time

from services.process_utils import decode_output


def filter_escape_sequences(text):
    """过滤终端输出中的转义序列，仅保留可读内容。

    规则：只允许 ASCII 可打印字符（0x20-0x7E）、\\n、\\r、\\t，
    移除所有 ANSI 转义序列（ESC 0x1B 开头）。
    """
    # 移除 ESC 开头的 ANSI 转义序列（\x1b[...m, \x1b(... 等）
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b[][()][0-9;]*[a-zA-Z]?', '', text)
    text = re.sub(r'\x1b[PX^_]', '', text)
    text = re.sub(r'\x1b[\\ab]', '', text)
    # 移除其他非允许字符
    return ''.join(c for c in text if c in '\n\r\t' or 0x20 <= ord(c) <= 0x7E)


class TerminalSession:
    """单个持久 shell 会话。"""

    def __init__(self, sid, shell_type, proc_manager, init_commands):
        """初始化会话。

        Args:
            sid: 会话唯一标识
            shell_type: shell 类型，如 'cmd' / 'bash'
            proc_manager: ProcessManager 或 PtyProcess 实例（两者接口一致）
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
                # PTY 下 stdout 的 read 会因非阻塞语义立即返回且持续抢占；
                # 统一先判断是否就绪，避免占用 CPU。
                if hasattr(self._proc_manager, 'poll_ready'):
                    if not self._proc_manager.poll_ready(timeout=0.2):
                        # 子进程可能刚退出，短忙等其状态
                        if not self._proc_manager.is_running():
                            break
                        continue
                data = self._proc_manager.read_output(4096)
                if not data:
                    break
                text = filter_escape_sequences(decode_output(data))
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

    def read_pending_output(self, caller_generation=None):
        """读取并清空待发送的输出队列。

        Args:
            caller_generation: 调用方持有的代际标识。若提供且与当前
                generation 不一致，说明已有新的 SSE 连接接管会话，
                此时返回空列表且**不消耗**队列，避免旧连接输出被重复发送。

        Returns:
            list[str]: 输出块列表
        """
        with self._lock:
            if caller_generation is not None and caller_generation != self.generation:
                return []
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

    def set_size(self, rows, cols):
        """调整终端窗口尺寸（PTY 下会真正生效）。"""
        set_size = getattr(self._proc_manager, 'set_size', None)
        if set_size:
            try:
                set_size(rows, cols)
            except Exception:
                pass

    def next_generation(self):
        """递增并返回新的 generation 值。

        用于 SSE 连接独占：旧连接检测到 generation 变化后应主动退出，
        避免多个 SSE 连接同时消费同一个会话的输出队列。

        非首次切换 generation 时清空旧队列，防止旧连接的残留输出被新连接
        重复显示；首次连接（generation 从 0 到 1）保留会话初始化输出。
        """
        with self._lock:
            self.generation += 1
            if self.generation > 1:
                self._output_queue = []
                self._output_event.clear()
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
