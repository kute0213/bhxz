"""RCON 服务包 —— 与 Minecraft 服务器 RCON 通信。

提供：
- RCON 客户端连接池与命令执行（线程安全，支持并发）
- 在线玩家列表定时追踪与缓存
- EasyAuth 插件指令封装（注册、改密、删除等）

连接池说明：
  services/rcon/pool.py 提供线程安全的 RCONConnectionPool，
  默认配置下复用连接，池满时自动创建临时连接，实现理论无限并发。
  使用 get_pool() 获取全局单例，reset_pool() 在配置变更时重置。
"""

from services.rcon.client import rcon_connect, execute_command
from services.rcon.pool import get_pool, reset_pool, RCONConnectionPool
from services.rcon.player_tracker import player_tracker, PlayerList, parse_player_list
from services.rcon.easy_auth import (
    register_player, change_password, remove_player,
    get_player_info, list_players,
    whitelist_add_player,
)

__all__ = [
    'rcon_connect', 'execute_command',
    'get_pool', 'reset_pool', 'RCONConnectionPool',
    'player_tracker', 'PlayerList', 'parse_player_list',
    'register_player', 'change_password', 'remove_player',
    'get_player_info', 'list_players',
    'whitelist_add_player',
]