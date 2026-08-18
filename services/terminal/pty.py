"""伪终端子进程（跨平台）。

对外接口统一为（start/send_input/read_output/poll_ready/is_running/set_size/
terminate/cleanup），上层 TerminalSession 无需关心底层实现：

- **Unix / macOS**：使用 os.openpty() 原生伪终端（PtyProcess），输入回显、
  行编辑、清屏、光标控制等由终端驱动真实响应。
- **Windows**：Windows 没有 pty/termios，改用 pywinpty（ConPTY）提供真伪终端
  （WinPtyProcess），获得与 Unix 一致的 SSH 式交互体验；Windows 下未安装
  pywinpty 时 available() 返回 False，上层回退到管道实现。

输入/输出均在此层统一编码，read_output 始终返回 bytes，由上层 decode_output 解码。
"""

import os
import threading
import time

try:
    import pty  # Unix 独有
except ImportError:  # pragma: no cover - Windows 无 pty
    pty = None

try:
    import select  # Unix 轮询用；Windows 有仅 socket 的 select，不使用
except ImportError:  # pragma: no cover
    select = None

__all__ = [
    'PtyProcess',
    'WinPtyProcess',
    'available',
    'create_pty',
    'start_pty',
]


def _is_windows():
    return os.name == 'nt'


def available():
    """当前平台是否支持（真）伪终端。

    Returns:
        bool: Unix 恒为 True（有 pty）；Windows 仅当 pywinpty 可导入时为 True。
    """
    if _is_windows():
        try:
            import winpty  # noqa: F401
        except Exception:
            return False
        return True
    return pty is not None


def create_pty():
    """创建当前平台的伪终端封装实例（尚未启动）。

    Returns:
        PtyProcess | WinPtyProcess
    """
    return WinPtyProcess() if _is_windows() else PtyProcess()


# ---------------------------------------------------------------------------
# Unix 原生 PTY
# ---------------------------------------------------------------------------

def _set_winsize(master_fd, rows, cols):
    """通过 ioctl 设置伪终端窗口尺寸。"""
    if _is_windows():
        return
    try:
        import fcntl
        import struct
        import termios
        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass


class PtyProcess:
    """基于 os.openpty() 的子进程封装（Unix / macOS）。"""

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
            self._rows = int(rows)
        if cols:
            self._cols = int(cols)

        if env is None:
            from services.process_utils import make_env
            env = make_env()
        if cwd is None:
            from config import APP_ROOT
            cwd = APP_ROOT

        import subprocess
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
        import subprocess
        import signal
        pro = self._process
        if pro is None:
            return
        try:
            if pro.poll() is None:
                try:
                    os.killpg(os.getpgid(pro.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    try:
                        pro.terminate()
                    except Exception:
                        pass
            pro.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(pro.pid), signal.SIGKILL)
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


# ---------------------------------------------------------------------------
# Windows ConPTY（pywinpty）
# ---------------------------------------------------------------------------

class WinPtyProcess:
    """基于 pywinpty / ConPTY 的 Windows 伪终端封装。

    pywinpty 的 read 是阻塞式的，而上层 TerminalSession 依赖可轮询的读取模型。
    这里用**独立读取线程**把 ConPTY 输出持续搬进内部缓冲，再把
    poll_ready / read_output 做成对该缓冲的非阻塞访问，从而在 Windows 下
    获得与 Unix PTY 一致的行为：输入回显、行编辑、清屏、光标控制、Python
    input() 均可正常工作。
    """

    _READ_CHUNK = 8192

    def __init__(self):
        self._proc = None
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._closed = False
        self._reader_done = False
        self._reader_thread = None
        self._rows = 24
        self._cols = 120

    # ---- 生命周期 ----

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
        """启动 Windows 控制台子进程并挂载到 ConPTY。"""
        if rows:
            self._rows = int(rows)
        if cols:
            self._cols = int(cols)

        from winpty import PtyProcess as WinPty

        if env is None:
            from services.process_utils import make_env
            env = make_env()
        if cwd is None:
            from config import APP_ROOT
            cwd = APP_ROOT
        env = dict(env)

        command = _build_win_cmdline(cmd)

        proc = WinPty.spawn(
            command,
            cwd=cwd,
            env=env,
            dimensions=(self._rows, self._cols),
        )
        self._proc = proc

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name='winpty-reader',
        )
        self._reader_thread.start()
        return proc

    def _reader_loop(self):
        proc = self._proc
        while not self._closed:
            try:
                alive = proc.isalive()
            except Exception:
                alive = False
            if not alive:
                break
            try:
                data = proc.read(self._READ_CHUNK)
            except (EOFError, OSError, ValueError):
                break
            except Exception:
                if self._closed:
                    break
                time.sleep(0.02)
                continue
            if not data:
                time.sleep(0.01)
                continue
            self._append(data)

        self._drain_final()
        with self._lock:
            self._reader_done = True
        self._event.set()

    def _drain_final(self):
        """进程退出后尽可能把残余输出排空。"""
        proc = self._proc
        if proc is None:
            return
        for _ in range(20):
            try:
                data = proc.read(self._READ_CHUNK)
            except Exception:
                break
            if not data:
                break
            self._append(data)

    def _append(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8', errors='replace')
        if not data:
            return
        with self._lock:
            self._buffer += data
        self._event.set()

    # ---- 对外接口 ----

    def send_input(self, data):
        if self._closed or self._proc is None:
            return False
        if isinstance(data, bytes):
            data = data.decode('utf-8', errors='replace')
        try:
            self._proc.write(data)
            return True
        except Exception:
            return False

    def read_output(self, size=4096):
        with self._lock:
            if not self._buffer:
                return b''
            chunk = bytes(self._buffer[:size])
            del self._buffer[:size]
            if not self._buffer:
                self._event.clear()
            return chunk

    def poll_ready(self, timeout=0.1):
        self._event.wait(timeout=timeout)
        with self._lock:
            has_data = bool(self._buffer)
            done = self._reader_done
        # 有数据，或读取线程已结束（让上层完成最终排空并退出）
        return has_data or done

    def is_running(self):
        proc = self._proc
        if proc is None:
            return False
        try:
            return proc.isalive()
        except Exception:
            return False

    def set_size(self, rows, cols):
        self._rows = max(2, int(rows))
        self._cols = max(2, int(cols))
        proc = self._proc
        if proc is None:
            return
        # pywinpty 高层 PtyProcess 用 setwinsize(rows, cols)；set_size/resize 兜底
        for method in ('setwinsize', 'set_size', 'resize'):
            fn = getattr(proc, method, None)
            if not callable(fn):
                continue
            try:
                if method == 'resize':
                    fn(self._cols, self._rows)
                else:
                    fn(self._rows, self._cols)
                return
            except Exception:
                continue

    def terminate(self, timeout=5):
        proc = self._proc
        if proc is None:
            return
        self._closed = True
        try:
            proc.terminate(force=True)
        except Exception:
            pass
        # 关闭 ConPTY，解除读取线程的阻塞
        try:
            if hasattr(proc, 'close'):
                proc.close()
        except Exception:
            pass
        self._event.set()

    def cleanup(self):
        self.terminate(timeout=2)
        reader = self._reader_thread
        if reader and reader.is_alive():
            reader.join(timeout=2)
        self._proc = None
        with self._lock:
            self._buffer = bytearray()


def _build_win_cmdline(cmd):
    """把命令（列表或字符串）转成 winpty spawn 用的 Windows 命令行字符串。"""
    if isinstance(cmd, (list, tuple)):
        import subprocess as _sp
        return _sp.list2cmdline([str(a) for a in cmd])
    return str(cmd)


def start_pty(cmd, cwd=None, env=None, rows=24, cols=120):
    """便捷工厂：创建并启动一个当前平台的伪终端。"""
    proc_wrapper = create_pty()
    proc_wrapper.start(cmd, cwd=cwd, env=env, rows=rows, cols=cols)
    return proc_wrapper