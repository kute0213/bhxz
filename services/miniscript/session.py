"""MiniScript 会话管理器。

按 Flask session 隔离脚本执行状态：
  - 每个用户会话拥有独立的 ScriptExecutor 实例
  - 每个用户会话拥有独立的 prompt/confirm 交互响应状态
  - 同一用户同时只能执行一个脚本，不同用户之间互不干扰

此设计解决了全局单例响应变量在多用户/多 worker 环境下的冲突，
也避免了 A 用户脚本弹出的 prompt 被 B 用户的响应误消费。
"""

import threading
import time

from services.miniscript import ScriptExecutor


class ScriptSessionManager:
    """按 session 管理 MiniScript 执行器与交互响应（线程安全单例）。"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, response_timeout=60):
        if self._initialized:
            return
        self._initialized = True

        self._response_timeout = response_timeout
        self._sessions = {}
        self._lock = threading.Lock()
        # 已开始执行但 SSE 连接失效的超时（秒）。前端退出网页后，
        # 连接不再被 touch，超过此值即强制终止脚本。
        self._stale_abort_timeout = 20

        # 启动监控线程：回收长期无连接存活的执行会话
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name='script-monitor', daemon=True
        )
        self._monitor_thread.start()

    def _get_or_create(self, sid):
        """获取或创建指定 sid 的会话状态（调用方不应长期持有返回字典）。"""
        with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = {
                    'executor': ScriptExecutor(),
                    'response_event': threading.Event(),
                    'response_value': None,
                    'last_seen': 0.0,
                    'created_at': time.time(),
                }
            return self._sessions[sid]

    def touch(self, sid):
        """标记该会话的连接仍然存活（由 SSE 流循环调用）。"""
        state = self._get_or_create(sid)
        with self._lock:
            state['last_seen'] = time.time()

    def _monitor_loop(self):
        """后台监控：终止「连接已失效但仍在运行」的脚本。

        覆盖意外浏览器关闭、tags 崩溃等前端无法主动发送终止信号的场景，
        保证退出网页后脚本会被强制终止。
        """
        while True:
            time.sleep(5)
            try:
                now = time.time()
                stale = []
                with self._lock:
                    for sid, state in self._sessions.items():
                        executor = state['executor']
                        if executor.is_running() and \
                                now - state['last_seen'] > self._stale_abort_timeout:
                            stale.append(sid)
                for sid in stale:
                    try:
                        self.abort(sid)
                    except Exception:
                        pass
            except Exception:
                pass

    def get_executor(self, sid):
        """获取指定 sid 的执行器实例。"""
        return self._get_or_create(sid)['executor']

    def clear_response(self, sid):
        """清空指定 sid 的待处理响应。"""
        state = self._get_or_create(sid)
        with self._lock:
            state['response_value'] = None
            state['response_event'].clear()

    def set_response(self, sid, value):
        """设置前端对 prompt/confirm 的响应值。"""
        state = self._get_or_create(sid)
        with self._lock:
            state['response_value'] = value
            state['response_event'].set()

    def wait_response(self, sid, event_type):
        """轮询等待前端对交互事件的响应。

        Args:
            sid: 用户 session id
            event_type: 'prompt' 或 'confirm'

        Returns:
            前端响应值；超时或执行器已终止时返回 None(prompt) / False(confirm)
        """
        state = self._get_or_create(sid)
        deadline = time.time() + self._response_timeout

        while time.time() < deadline:
            # 短轮询：便于及时感知执行器被 abort 或客户端断开
            if state['response_event'].wait(timeout=2.0):
                with self._lock:
                    response = state['response_value']
                    state['response_value'] = None
                    state['response_event'].clear()
                return response

            executor = state['executor']
            if not executor.is_running():
                return None if event_type == 'prompt' else False

        return None if event_type == 'prompt' else False

    def is_running(self, sid):
        """指定 sid 是否有脚本正在执行。"""
        return self._get_or_create(sid)['executor'].is_running()

    def abort(self, sid):
        """强制终止指定 sid 正在执行的脚本。

        Returns:
            bool: 是否成功终止
        """
        state = self._get_or_create(sid)
        executor = state['executor']
        if executor.is_running():
            executor.abort()
            # 唤醒可能正在等待响应的 SSE 线程
            state['response_event'].set()
            return True
        return False

    def cleanup_expired(self, max_age=3600):
        """清理已结束且超过 max_age 秒未使用的会话状态。"""
        now = time.time()
        expired = []
        with self._lock:
            for sid, state in self._sessions.items():
                if not state['executor'].is_running() and \
                        now - state['created_at'] > max_age:
                    expired.append(sid)
            for sid in expired:
                self._sessions.pop(sid, None)
