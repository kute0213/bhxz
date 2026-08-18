"""PTY 伪终端子进程（仅 Unix）。

使用 os.openpty() 将子进程挂载到伪终端，从而获得 SSH 式交互体验：
  - 输入回显与行编辑由终端驱动处理（Python input() / readline 原生可用）
  - 清屏、光标控制等 ANSI 控制序列被真实响应
  - 输出实时流式返回（stdout/stderr 合并 + 回显）

对外暴露 PtyProcess，接口与 services.process_manager.ProcessManager
保持一致（start/send_input/read_output/is_running/terminate/cleanup/set_size），
这样上层 TerminalSession 无需关心底层是 PTY 还是管道。

Windows 无原生 pty，仍使用基于管道的 ProcessManager。
"""

import os
import select
import subprocess
import threading

if os.name == 'nt':
    import pty  # noqa: F401  (Windows 无 pty，仅占位)
else:
    import pty

__all__ = ['PtyProcess', 'start_pty']


def _set_winsize(master_fd, rows, cols):
    """通过 ioctl 设置伪终端窗口尺寸。"""
    if os.name == 'nt':
        return
    try:
        import fcntl
        import struct
        import termios
        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass


def available():
    """当前平台是否支持 PTY。"""
    return hasattr(pty, 'fork') or hasattr(pty, 'openpty')


class PtyProcess:
    """基于伪终端的子进程封装（Unix）。"""

    def __init__(self):
        self._process = None
        self._master_fd = -1
        self._lock = threading.Lock()
        self._rows = 24
        self._cols = 120

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
        rows=None,
        cols=None,
        **kwargs,
    ):
        """启动子进程并挂载到伪终端。

        stdin/stdout/stderr 参数会被忽略——PTY 会话自动接管三者。
        """
        if rows:
            self._rows = rows
        if cols:
            self._cols = cols

        if env is None:
            from services.process_utils import make_env
            env = make_env()
        if cwd is None:
            from config import APP_ROOT
            cwd = APP_ROOT

        import pty as _pty
        master_fd, slave_fd = _pty.openpty()
        self._master_fd = master_fd
        _set_winsize(master_fd, self._rows, self._cols)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
                close_fds=True,
            )
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        self._process = proc
        return proc

    def send_input(self, data):
        """向伪终端写入输入（含回显所需原始字节）。"""
        with self._lock:
            if self._master_fd < 0:
                return False
            if isinstance(data, str):
                data = data.encode('utf-8', errors='replace')
            try:
                os.write(self._master_fd, data)
                return True
            except OSError:
                return False

    def read_output(self, size=4096):
        """读取伪终端 master 端的一块输出。"""
        with self._lock:
            if self._master_fd < 0:
                return b''
            try:
                return os.read(self._master_fd, size)
            except OSError:
                return b''

    def poll_ready(self, timeout=0.1):
        """等待伪终端可读（返回 bool：是否有数据可读）。"""
        try:
            rlist, _, _ = select.select([self._master_fd], [], [], timeout)
            return bool(rlist)
        except (OSError, ValueError):
            return False

    def is_running(self):
        if self._process is None:
            return False
        return self._process.poll() is None

    def set_size(self, rows, cols):
        """调整伪终端窗口尺寸。"""
        self._rows = max(2, int(rows))
        self._cols = max(2, int(cols))
        _set_winsize(self._master_fd, self._rows, self._cols)

    def terminate(self, timeout=5):
        pro = self._process
        if pro is None:
            return
        try:
            if pro.poll() is None:
                try:
                    pid = pro.pid
                    import signal
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    try:
                        pro.terminate()
                    except Exception:
                        pass
            pro.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                pid = pro.pid
                import signal
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    pro.kill()
                except Exception:
                    pass
        except Exception:
            pass

    def cleanup(self):
        self.terminate(timeout=2)
        with self._lock:
            if self._master_fd >= 0:
                try:
                    os.close(self._master_fd)
                except OSError:
                    pass
                self._master_fd = -1


def start_pty(cmd, cwd=None, env=None, rows=24, cols=120):
    """便捷工厂：创建并启动一个 PtyProcess。"""
    proc_wrapper = PtyProcess()
    proc_wrapper.start(cmd, cwd=cwd, env=env, rows=rows, cols=cols)
    return proc_wrapper