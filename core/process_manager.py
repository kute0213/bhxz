"""跨平台子进程生命周期管理。

封装 subprocess.Popen 的创建、终止、等待，统一处理：
  - Windows CREATE_NO_WINDOW 标志
  - Unix 进程组（setsid）与 SIGTERM/SIGKILL
  - 阶梯式终止，避免僵尸进程与孤儿进程
"""

import os
import signal
import subprocess
import threading

from core.process_utils import make_env


class ProcessManager:
    """统一子进程管理器。

    每个实例同时只能管理一个子进程；如需并发多个进程，请创建多个实例。
    """

    def __init__(self):
        self._process = None
        self._use_process_group = False
        self._lock = threading.Lock()

    def start(
        self,
        cmd,
        cwd=None,
        env=None,
        shell=False,
        use_process_group=None,
        stdin=None,
        stdout=None,
        stderr=None,
        **kwargs,
    ):
        """启动子进程并返回 Popen 实例。

        Args:
            cmd: 命令列表或字符串
            cwd: 工作目录，默认项目根目录
            env: 环境变量字典，默认使用 make_env()
            shell: 是否通过 shell 执行
            use_process_group: 是否创建新进程组（Unix 下使用 setsid）。
                None 表示根据 shell 参数自动判断：shell=True 时默认创建进程组
            stdin/stdout/stderr: 标准流重定向，默认 None
            **kwargs: 额外传给 Popen 的参数

        Returns:
            subprocess.Popen 实例
        """
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("Process is already running")

            if env is None:
                env = make_env()
            if cwd is None:
                from config import APP_ROOT
                cwd = APP_ROOT

            if use_process_group is None:
                use_process_group = shell

            popen_kwargs = {
                'cwd': cwd,
                'env': env,
                'shell': shell,
                'stdin': stdin,
                'stdout': stdout,
                'stderr': stderr,
            }
            popen_kwargs.update(kwargs)

            self._use_process_group = use_process_group

            if os.name == 'nt':
                # Windows：默认隐藏窗口；需要进程组时附加 CREATE_NEW_PROCESS_GROUP
                default_flags = subprocess.CREATE_NO_WINDOW
                if use_process_group:
                    default_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
                popen_kwargs.setdefault('creationflags', default_flags)
            else:
                # Unix：创建新会话/进程组，便于整体终止子进程树
                if use_process_group:
                    popen_kwargs.setdefault('preexec_fn', os.setsid)

            self._process = subprocess.Popen(cmd, **popen_kwargs)
            return self._process

    def terminate(self, timeout=5):
        """阶梯式终止子进程。

        1. 发送 SIGTERM（Windows: 优先向进程组发 CTRL_BREAK_EVENT）
        2. 等待 timeout 秒
        3. 若仍在运行，发送 SIGKILL（Windows: kill）
        4. 再次等待
        """
        with self._lock:
            proc = self._process
            use_pg = self._use_process_group
            if proc is None:
                return

            if proc.poll() is not None:
                self._process = None
                self._use_process_group = False
                return

            try:
                if os.name == 'nt':
                    # Windows：若创建了进程组，先向整个组发送 CTRL_BREAK_EVENT
                    # 使 shell 及其子进程都能收到终止信号
                    if use_pg and hasattr(signal, 'CTRL_BREAK_EVENT'):
                        try:
                            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                        except (ProcessLookupError, OSError):
                            pass
                    else:
                        proc.terminate()
                else:
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        proc.terminate()

                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == 'nt':
                        proc.kill()
                    else:
                        try:
                            pgid = os.getpgid(proc.pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            proc.kill()
                    proc.wait(timeout=timeout)
                except Exception:
                    pass
            except Exception:
                pass
            finally:
                self._process = None
                self._use_process_group = False

    def kill(self):
        """立即强制终止子进程。"""
        with self._lock:
            proc = self._process
            use_pg = self._use_process_group
            if proc is None or proc.poll() is not None:
                return
            try:
                if os.name == 'nt':
                    # 进程组模式下仍优先尝试组信号，失败后强制 kill
                    if use_pg and hasattr(signal, 'CTRL_BREAK_EVENT'):
                        try:
                            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                            proc.wait(timeout=1)
                        except Exception:
                            pass
                    proc.kill()
                else:
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
            finally:
                self._process = None
                self._use_process_group = False

    def wait(self, timeout=None):
        """等待子进程结束。

        Returns:
            returncode 或 None（超时）
        """
        with self._lock:
            proc = self._process
        if proc is None:
            return None
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def is_running(self):
        """子进程是否仍在运行。"""
        with self._lock:
            proc = self._process
            return proc is not None and proc.poll() is None

    def get_process(self):
        """获取底层 Popen 实例（只读，谨慎使用）。"""
        with self._lock:
            return self._process

    def send_input(self, data):
        """向子进程 stdin 写入数据。

        Args:
            data: str 或 bytes

        Returns:
            bool: 是否写入成功
        """
        with self._lock:
            proc = self._process
        if proc is None or proc.stdin is None:
            return False
        try:
            if isinstance(data, str):
                data = data.encode('utf-8', errors='replace')
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except Exception:
            return False

    def read_output(self, size=4096):
        """读取子进程 stdout 的一块数据。

        Returns:
            bytes
        """
        with self._lock:
            proc = self._process
        if proc is None or proc.stdout is None:
            return b''
        try:
            return proc.stdout.read(size)
        except Exception:
            return b''

    def cleanup(self):
        """清理资源：终止进程并关闭所有流。"""
        with self._lock:
            proc = self._process
        self.terminate(timeout=2)
        if proc is not None:
            for stream_name in ('stdin', 'stdout', 'stderr'):
                stream = getattr(proc, stream_name, None)
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
