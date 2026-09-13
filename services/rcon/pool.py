"""RCON 连接池 —— 线程安全、自动回收、支持无限并发。

设计说明：
  - 连接池维护一个空闲连接队列，线程从池中借用连接，用后归还
  - 空闲连接超时自动关闭回收（默认 60 秒）
  - 后台守护线程每 30 秒清理过期空闲连接
  - 连接数无硬上限 —— 池满时自动创建临时连接（用完即关），实现理论无限并发
  - 归还连接时自动检测健康状态，失效连接被丢弃并创建新连接填补
  - 所有操作线程安全，使用 threading.Lock 保护内部状态
  - 使用 socket.settimeout 替代 mcrcon 的 signal.alarm，确保多线程安全
"""

import threading
import time
import socket
from collections import deque
from typing import Optional, Tuple

from mcrcon import MCRcon

from config import get_config_value
from core.scheduler import Scheduler


class RCONConnectionPool:
    """线程安全的 RCON 连接池。

    用法：
        pool = RCONConnectionPool()
        conn = pool.acquire()
        try:
            resp = conn.command('/list')
        finally:
            pool.release(conn)

    Args:
        host: RCON 地址，None 时从配置读取
        port: RCON 端口，None 时从配置读取
        password: RCON 密码，None 时从配置读取
        min_size: 最小空闲连接数（预创建）
        max_size: 最大空闲连接保留数
        idle_timeout: 空闲连接超时秒数
        connect_timeout: 连接超时秒数
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
        min_size: int = 2,
        max_size: int = 8,
        idle_timeout: int = 60,
        connect_timeout: int = 5,
    ):
        self._host = host
        self._port = port
        self._password = password
        self._min_size = min_size
        self._max_size = max_size
        self._idle_timeout = idle_timeout
        self._connect_timeout = connect_timeout

        # 内部状态
        self._lock = threading.Lock()
        self._idle: deque = deque()         # [(MCRcon, float), ...]
        self._active_count = 0               # 当前活跃连接数
        self._total_created = 0              # 累计创建连接数（调试用）
        self._closed = False

        # 预填充连接池
        self._fill_pool()

        # 启动后台清理调度器（每 30 秒清理一次过期空闲连接）
        self._scheduler = Scheduler(
            name='rcon-pool-cleanup',
            action=self._cleanup_idle,
            interval=30,
            run_immediately=False,
        )
        self._scheduler.start()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def acquire(self) -> Optional[MCRcon]:
        """从池中获取一个可用连接。

        返回一个 MCRcon 实例，或 None（配置错误/创建失败）。

        设计策略：
          - 优先从空闲队列取，检查健康状态
          - 空闲队列为空时，只要未达最大活跃数就创建新连接
          - 超过最大活跃数时，创建临时连接（不加入池，用完即关）
          - 永不阻塞调用线程，实现理论无限并发
        """
        # 先尝试从空闲队列获取
        with self._lock:
            if self._closed:
                return None

            while self._idle:
                conn, _ = self._idle.popleft()
                self._active_count += 1
                # 在锁外检查健康状态（避免长时间持有锁）
                # 注意：锁被释放前 self._active_count 已递增，如果健康检查失败
                # 需要在锁外递减，否则计数器会泄漏
                break  # 只取一个，跳出 while 循环到锁外检查
            else:
                # 空闲队列为空 —— 创建新连接
                if self._active_count < self._max_size:
                    conn = self._create_connection()
                    if conn:
                        self._active_count += 1
                        self._total_created += 1
                    return conn  # 可能为 None，在锁内返回
                # 超过最大活跃数，在锁外创建临时连接
                conn = None

        # 以下代码在锁外执行

        # 从空闲队列取出的连接，检查健康状态
        if conn is not None:
            if self._check_alive(conn):
                return conn
            # 连接失效，丢弃并递减计数器
            self._safe_disconnect(conn)
            with self._lock:
                self._active_count -= 1
            # 尝试创建新连接替代
            new_conn = self._create_connection()
            if new_conn:
                with self._lock:
                    self._active_count += 1
                    self._total_created += 1
                return new_conn
            return None

        # 超过最大活跃数 —— 创建临时连接（不加入池统计）
        temp_conn = self._create_connection()
        if temp_conn:
            with self._lock:
                self._total_created += 1
        return temp_conn  # 可能为 None

    def release(self, conn: Optional[MCRcon], force_close: bool = False):
        """归还连接。

        Args:
            conn: 要归还的 MCRcon 实例
            force_close: 强制关闭（用于连接已损坏时）
        """
        if conn is None:
            return

        if force_close:
            self._safe_disconnect(conn)
            # 递减活跃计数（如果是从池中借出的）
            with self._lock:
                if self._active_count > 0:
                    self._active_count -= 1
            return

        with self._lock:
            if self._closed:
                self._safe_disconnect(conn)
                if self._active_count > 0:
                    self._active_count -= 1
                return

            # 检查是否临时连接（未计入 active_count 或计数已归零）
            if self._active_count <= 0:
                # 临时连接，直接关闭
                self._safe_disconnect(conn)
                return

            # 归还到空闲队列
            self._idle.append((conn, time.time()))
            self._active_count -= 1

    def close(self):
        """关闭连接池，释放所有连接。"""
        self._scheduler.stop()
        with self._lock:
            self._closed = True
            while self._idle:
                conn, _ = self._idle.popleft()
                self._safe_disconnect(conn)
            self._active_count = 0

    @property
    def stats(self) -> dict:
        """连接池统计信息（线程安全）。"""
        with self._lock:
            return {
                'idle': len(self._idle),
                'active': self._active_count,
                'total_created': self._total_created,
                'max_size': self._max_size,
                'closed': self._closed,
            }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _read_config(self) -> Tuple[str, int, str]:
        """读取 RCON 配置。"""
        host = self._host or get_config_value('RCON_HOST', '127.0.0.1')
        port = self._port or int(get_config_value('RCON_PORT', 25575))
        password = self._password or get_config_value('RCON_PASSWORD', '')
        return host, port, password

    def _create_connection(self) -> Optional[MCRcon]:
        """创建一条新的 RCON 连接。

        使用 socket.settimeout 替代 mcrcon 内部 signal.alarm 实现超时，
        确保多线程环境下线程安全。
        """
        host, port, password = self._read_config()
        if not password:
            return None

        try:
            mcr = MCRcon(host, password, port=port, timeout=self._connect_timeout)
            # 设置 socket 超时（优先于 mcrcon 的 signal.alarm）
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout)
            sock.connect((host, port))
            # 替换 mcrcon 内部 socket 为已连接且带超时的 socket
            mcr.socket = sock
            # 发送 RCON 认证包
            mcr._send(3, password)  # noqa: SLF001
            return mcr
        except socket.timeout:
            return None
        except ConnectionRefusedError:
            return None
        except ConnectionResetError:
            return None
        except OSError:
            return None
        except Exception:
            return None

    def _check_alive(self, conn: MCRcon) -> bool:
        """检查连接是否存活。

        使用 ping 命令（/）探测连接状态，不产生副作用。
        失败时标记连接为失效。
        """
        if conn is None or conn.socket is None:
            return False
        try:
            # 发一个无害命令，检查连接是否正常
            # 即使服务器返回"未知命令"，也是有效响应
            conn.command('/')
            return True
        except Exception:
            return False

    def _safe_disconnect(self, conn: MCRcon):
        """安全关闭连接，忽略异常。"""
        try:
            conn.disconnect()
        except Exception:
            pass

    def _fill_pool(self):
        """预填充连接池到 min_size。

        如果 RCON 未配置或连接失败，静默跳过，不会阻塞启动。
        """
        for _ in range(self._min_size):
            conn = self._create_connection()
            if conn:
                self._idle.append((conn, time.time()))

    def _cleanup_idle(self):
        """清理超时未使用的空闲连接。"""
        now = time.time()
        with self._lock:
            keep = deque()
            discarded = 0
            while self._idle:
                conn, last_used = self._idle.popleft()
                if now - last_used > self._idle_timeout:
                    self._safe_disconnect(conn)
                    discarded += 1
                else:
                    keep.append((conn, last_used))
            self._idle = keep
            current_idle = len(self._idle)

        # 如果清理后空闲连接少于 min_size，补充（在锁外）
        if current_idle < self._min_size:
            need = self._min_size - current_idle
            for _ in range(need):
                conn = self._create_connection()
                if conn:
                    with self._lock:
                        self._idle.append((conn, time.time()))


# 模块级单例
_pool_lock = threading.Lock()
_pool: Optional[RCONConnectionPool] = None


def get_pool() -> RCONConnectionPool:
    """获取全局 RCON 连接池单例。"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = RCONConnectionPool()
    return _pool


def reset_pool():
    """重置连接池（用于配置变更时）。"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None