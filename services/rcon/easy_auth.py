"""EasyAuth 插件指令封装 —— 注册、改密、删除、查询等。

通过 RCON 向 Minecraft 服务器发送 EasyAuth 插件指令。
所有函数返回 (success, message) 元组。
底层连接复用 services/rcon/client.py 的 execute_command。
"""

from typing import Tuple

from services.rcon.client import execute_command


def _exec(command: str) -> str:
    """执行一条 RCON 指令，失败时返回空字符串。"""
    return execute_command(command, timeout=5)


def register_player(username: str, password: str) -> Tuple[bool, str]:
    """注册游戏内账号。

    Args:
        username: MC 玩家名
        password: 密码（含空格时自动加引号）

    Returns:
        (success, message)
    """
    pwd = f'"{password}"' if ' ' in password else password
    resp = _exec(f'/auth register {username} {pwd}')
    if not resp:
        return False, 'RCON 连接失败，请检查 RCON 配置'
    if 'successfully' in resp.lower() or '注册成功' in resp or 'created' in resp.lower():
        return True, '账号注册成功'
    return False, resp or '注册失败，未知错误'


def change_password(username: str, new_password: str) -> Tuple[bool, str]:
    """修改游戏内账号密码。

    Args:
        username: MC 玩家名
        new_password: 新密码

    Returns:
        (success, message)
    """
    pwd = f'"{new_password}"' if ' ' in new_password else new_password
    resp = _exec(f'/auth update {username} {pwd}')
    if not resp:
        return False, 'RCON 连接失败，请检查 RCON 配置'
    if 'successfully' in resp.lower() or '更新成功' in resp or 'updated' in resp.lower():
        return True, '密码修改成功'
    return False, resp or '修改密码失败，未知错误'


def remove_player(username: str) -> Tuple[bool, str]:
    """删除游戏内账号。"""
    resp = _exec(f'/auth remove {username}')
    if not resp:
        return False, 'RCON 连接失败，请检查 RCON 配置'
    if 'successfully' in resp.lower() or 'removed' in resp.lower() or '删除成功' in resp:
        return True, '账号已删除'
    return False, resp or '删除失败，未知错误'


def get_player_info(username: str) -> Tuple[bool, str]:
    """查询玩家信息。"""
    resp = _exec(f'/auth getPlayerInfo {username}')
    if not resp:
        return False, 'RCON 连接失败'
    if resp.strip():
        return True, resp.strip()
    return False, '未找到该玩家信息'


def list_players() -> Tuple[bool, str]:
    """列出所有注册玩家。"""
    resp = _exec('/auth list')
    if not resp:
        return False, 'RCON 连接失败'
    if resp.strip():
        return True, resp.strip()
    return False, '无玩家列表返回'