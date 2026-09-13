"""在线玩家列表追踪器 —— 后台线程定时通过 /list 获取玩家列表。

设计：
- 独立线程，每 5 秒执行一次 /list 命令（统一定时调度器，见 core/scheduler.py）
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
from core.scheduler import Scheduler
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
        self._name = 'rcon-player-tracker'
        self._max_backoff = 60.0  # 最大退避间隔（秒）
        # 统一定时调度器：固定间隔 + 失败退避（每次失败 +5 秒，上限 60 秒）
        self._scheduler = Scheduler(
            name=self._name,
            action=self._track,
            interval=self._interval,
            run_immediately=True,
            backoff_factor=5.0,
            backoff_max=self._max_backoff,
        )

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_player_list(self) -> PlayerList:
        """获取缓存的玩家列表（线程安全）。"""
        with self._lock:
            return self._cache

    def start(self):
        """启动追踪线程。"""
        if not self._scheduler.start():
            return
        log('INFO', 'RCON', '玩家列表追踪器已启动')

    def stop(self):
        """停止追踪线程。"""
        self._scheduler.stop()
        log('INFO', 'RCON', '玩家列表追踪器已停止')

    def reset(self):
        """重置缓存（配置变更时调用）。"""
        with self._lock:
            self._cache = PlayerList()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _track(self) -> bool:
        """执行一次 /list 并缓存结果；成功返回 True，失败返回 False（触发退避）。"""
        try:
            raw = execute_command('/list', timeout=5)
        except Exception:
            return False
        parsed = parse_player_list(raw)
        with self._lock:
            self._cache = parsed
        return parsed.error is None

    @property
    def is_running(self) -> bool:
        return self._scheduler.is_running


# 模块级单例
player_tracker = PlayerTracker()