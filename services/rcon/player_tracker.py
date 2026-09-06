"""在线玩家列表追踪器 —— 后台线程定时通过 /list 获取玩家列表。

设计：
- 独立线程，每 5 秒执行一次 /list 命令
- 缓存结果，外部通过 read-only 接口获取最新数据
- 连接失败时自动降级，不抛异常
- 连续失败时自动降低轮询频率（退避），恢复后重置
- 使用 threading.Event 实现优雅关闭
"""

import re
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from core.logger import log
from services.rcon.client import execute_command


@dataclass
class PlayerList:
    """解析后的玩家列表。"""
    online: int = 0           # 在线人数
    max_players: int = 0      # 最大人数
    players: List[str] = field(default_factory=list)  # 玩家名列表
    raw: str = ''             # 原始 /list 应答
    error: Optional[str] = None  # 错误信息
    updated_at: float = 0.0   # 最后更新时间戳


# 正则：There are 2 of a max of 520 players online: kute_mc, kute_bot
_LIST_PATTERN = re.compile(
    r'There are (\d+) of a max of (\d+) players online:?\s*(.*)',
    re.IGNORECASE,
)


def parse_player_list(raw: str) -> PlayerList:
    """解析 /list 命令的应答文本。

    Args:
        raw: /list 命令的原始应答

    Returns:
        解析后的 PlayerList
    """
    result = PlayerList(raw=raw.strip(), updated_at=time.time())

    if not raw:
        result.error = 'RCON 无应答'
        return result

    m = _LIST_PATTERN.match(raw)
    if not m:
        # 可能无玩家在线时的格式：There are 0 of a max of 520 players online:
        # 或应答格式不匹配
        result.error = '无法解析玩家列表'
        return result

    result.online = int(m.group(1))
    result.max_players = int(m.group(2))
    names_str = m.group(3).strip()
    if names_str:
        result.players = [n.strip() for n in names_str.split(',') if n.strip()]
    return result


class PlayerTracker:
    """玩家列表后台追踪器。

    启动后在独立线程中每 5 秒执行一次 /list 命令，
    解析结果并缓存，外部通过 get_player_list() 获取最新数据。

    连续失败时自动降低轮询频率，最多退避到 60 秒，
    恢复成功后立即重置回正常间隔。
    """

    def __init__(self, interval: float = 5.0):
        self._interval = interval
        self._lock = threading.Lock()
        self._cache: PlayerList = PlayerList()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._name = 'rcon-player-tracker'
        # 连续失败计数 & 退避
        self._consecutive_failures = 0
        self._max_backoff = 60.0  # 最大退避间隔（秒）

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_player_list(self) -> PlayerList:
        """获取缓存的玩家列表（线程安全）。"""
        with self._lock:
            return self._cache

    def start(self):
        """启动追踪线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._consecutive_failures = 0
        self._thread = threading.Thread(
            target=self._run_loop,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        log('INFO', 'RCON', '玩家列表追踪器已启动')

    def stop(self):
        """停止追踪线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log('INFO', 'RCON', '玩家列表追踪器已停止')

    def reset(self):
        """重置缓存和失败计数（配置变更时调用）。"""
        with self._lock:
            self._cache = PlayerList()
            self._consecutive_failures = 0

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get_current_interval(self) -> float:
        """根据连续失败次数计算当前轮询间隔（退避）。"""
        failures = self._consecutive_failures
        if failures <= 0:
            return self._interval
        # 退避算法：每次失败增加 5 秒，最大 60 秒
        backoff = min(self._interval + failures * 5, self._max_backoff)
        return backoff

    def _run_loop(self):
        """后台循环：每 5 秒执行一次 /list，失败时自动退避。"""
        while not self._stop_event.is_set():
            try:
                raw = execute_command('/list', timeout=5)
                parsed = parse_player_list(raw)
                with self._lock:
                    self._cache = parsed
                    if parsed.error:
                        self._consecutive_failures += 1
                    else:
                        # 恢复成功，重置失败计数
                        self._consecutive_failures = 0
            except Exception:
                with self._lock:
                    self._consecutive_failures += 1
                # 兜底：任何未捕获异常都不让线程挂掉
                pass

            # 使用退避间隔等待
            current_interval = self._get_current_interval()
            self._stop_event.wait(current_interval)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# 模块级单例
player_tracker = PlayerTracker()