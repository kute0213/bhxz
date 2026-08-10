"""终端会话管理器。

管理多个持久 shell 会话的生命周期，包括创建、获取、重置与过期清理。
"""

import subprocess
import threading
import time
import uuid

from config import APP_ROOT
from services.process_manager import ProcessManager
from services.shell import detect_shell, get_shell_env
from services.terminal.session import TerminalSession


class _TerminalErrorSession:
    """shell 启动失败时的占位会话，用于向前端返回可读错误信息。"""

    def __init__(self, sid, error_msg):
        self.sid = sid
        self.error = error_msg
        self.closed = True
        self.shell_type = None
        self.last_active = time.time()
        self._output_queue = [
            '\r\n[终端启动失败]\r\n',
            f'错误信息: {error_msg}\r\n',
            '请检查系统是否安装了兼容的 shell（Windows 需 cmd.exe/PowerShell，'
            'Linux/macOS 需 bash/sh）。\r\n',
        ]
        self._lock = threading.Lock()
        self._output_event = threading.Event()
        self._output_event.set()

    def send_input(self, _text):
        return False

    def read_pending_output(self):
        with self._lock:
            chunks = self._output_queue
            self._output_queue = []
            self._output_event.clear()
            return chunks

    def wait_output(self, _timeout=None):
        return False

    def touch(self):
        pass

    def is_alive(self):
        return False

    def close(self):
        self.closed = True


class TerminalManager:
    """终端会话管理器（线程安全单例）。"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, timeout=30 * 60, cleanup_interval=300):
        if self._initialized:
            return
        self._initialized = True

        self._timeout = timeout
        self._cleanup_interval = cleanup_interval
        self._sessions = {}
        self._lock = threading.Lock()

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self):
        """后台线程：定期清理过期会话。"""
        while True:
            time.sleep(self._cleanup_interval)
            try:
                self.cleanup_expired_sessions()
            except Exception:
                pass

    def get_or_create_session(self, user_session):
        """获取或创建当前用户的终端会话。

        Args:
            user_session: Flask session 对象或类似字典

        Returns:
            TerminalSession 或 _TerminalErrorSession 实例
        """
        sid = user_session.get('terminal_sid')

        with self._lock:
            if sid and sid in self._sessions:
                session = self._sessions[sid]
                if not session.closed and session.is_alive():
                    session.touch()
                    return session
                self._cleanup_session_nolock(sid)

            sid = str(uuid.uuid4())
            user_session['terminal_sid'] = sid

            session = self._create_session_nolock(sid)
            self._sessions[sid] = session
            return session

    def _create_session_nolock(self, sid):
        """创建新的终端会话（调用方需持有 _lock）。"""
        shell_args, shell_type, init_commands = detect_shell()
        env = get_shell_env()

        proc_manager = ProcessManager()
        try:
            proc_manager.start(
                shell_args,
                cwd=APP_ROOT,
                env=env,
                shell=False,
                use_process_group=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
        except Exception as e:
            return _TerminalErrorSession(sid, str(e))

        return TerminalSession(sid, shell_type, proc_manager, init_commands)

    def _cleanup_session_nolock(self, sid):
        """清理指定会话（调用方需持有 _lock）。"""
        if sid not in self._sessions:
            return
        session = self._sessions.pop(sid)
        try:
            session.close()
        except Exception:
            pass

    def reset_session(self, user_session):
        """重置当前用户的终端会话（重启 shell）。"""
        sid = user_session.get('terminal_sid')
        if sid:
            with self._lock:
                self._cleanup_session_nolock(sid)
        return self.get_or_create_session(user_session)

    def cleanup_expired_sessions(self):
        """清理超过超时时间未活动的会话。"""
        now = time.time()
        expired = []
        with self._lock:
            for sid, session in self._sessions.items():
                if now - session.last_active > self._timeout:
                    expired.append(sid)
            for sid in expired:
                self._cleanup_session_nolock(sid)
