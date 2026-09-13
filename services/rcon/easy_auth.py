"""EasyAuth 插件指令封装 —— 注册、改密、删除、查询等。

密码验证使用 /auth getPlayerInfo + bcrypt 比对。

通过 RCON 向 Minecraft 服务器发送 EasyAuth 插件指令。
所有函数返回 (success, message) 元组。
底层连接复用 services/rcon/client.py 的 execute_command。

安全说明：
- 所有输入参数均经过 sanitize 处理，防止 RCON 命令注入
- 用户名和密码参数使用 sanitize_rcon_username / sanitize_rcon_password 清洗
"""

from typing import Tuple

from services.rcon.client import execute_command
from services.validation import sanitize_rcon_username, sanitize_rcon_password


def _exec(command: str) -> str:
    """执行一条 RCON 指令，失败时返回空字符串。"""
    return execute_command(command, timeout=5)


def _build_command(prefix: str, username: str, password: str = None) -> str:
    """安全构建 RCON 命令，防止命令注入。

    Args:
        prefix: 命令前缀，如 '/auth register'
        username: MC 用户名
        password: 密码（可选）

    Returns:
        安全的命令字符串
    """
    safe_user = sanitize_rcon_username(username)
    if not safe_user:
        return ''
    if password is not None:
        safe_pwd = sanitize_rcon_password(password)
        return f'{prefix} {safe_user} {safe_pwd}'
    return f'{prefix} {safe_user}'


def register_player(username: str, password: str) -> Tuple[bool, str]:
    """注册游戏内账号。

    Args:
        username: MC 玩家名
        password: 密码

    Returns:
        (success, message)
    """
    cmd = _build_command('/auth register', username, password)
    if not cmd:
        return False, 'MC 用户名包含非法字符'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 无应答（服务器未返回任何输出）'
    if 'successfully' in resp.lower() or '注册成功' in resp or 'created' in resp.lower():
        return True, '账号注册成功'
    return False, resp


def whitelist_add_player(username: str) -> Tuple[bool, str]:
    """通过白名单命令添加玩家（/easywhitelist add）。

    使用 RCON 向 Minecraft 服务器发送 /easywhitelist add 命令，
    将玩家添加到服务器白名单中。

    Args:
        username: MC 玩家名（已由调用方验证格式）

    Returns:
        (success, message)
    """
    safe_user = sanitize_rcon_username(username)
    if not safe_user:
        return False, 'MC 用户名包含非法字符'

    cmd = f'/easywhitelist add {safe_user}'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 无应答（服务器未返回任何输出）'
    if 'added' in resp.lower() or 'add' in resp.lower() or '成功' in resp or '已添加' in resp:
        return True, f'玩家 {safe_user} 已添加到白名单'
    if 'already' in resp.lower() or 'already added' in resp.lower() or '已存在' in resp or 'already whitelisted' in resp.lower():
        return True, f'玩家 {safe_user} 已在白名单中'
    return False, resp


def change_password(username: str, new_password: str) -> Tuple[bool, str]:
    """修改游戏内账号密码。

    优先通过 EasyAuth 数据库直连修改（需配置 MC_GAME_FOLDER），
    失败时降级到 RCON 命令。

    Args:
        username: MC 玩家名
        new_password: 新密码

    Returns:
        (success, message)
    """
    safe_user = sanitize_rcon_username(username)
    if not safe_user:
        return False, 'MC 用户名包含非法字符'

    # 1. 数据库直连改密（优先）
    try:
        from services.easy_auth_db import change_password as db_change
        db_ok, db_msg = db_change(safe_user, new_password)
        if db_ok:
            return True, db_msg
    except Exception:
        pass

    # 2. RCON 命令改密（降级）
    cmd = _build_command('/auth update', username, new_password)
    if not cmd:
        return False, 'MC 用户名包含非法字符'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 无应答（服务器未返回任何输出）'
    if 'successfully' in resp.lower() or '更新成功' in resp or 'updated' in resp.lower():
        return True, '密码修改成功'
    return False, resp


def remove_player(username: str) -> Tuple[bool, str]:
    """删除游戏内账号。"""
    cmd = _build_command('/auth remove', username)
    if not cmd:
        return False, 'MC 用户名包含非法字符'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 无应答（服务器未返回任何输出）'
    if 'successfully' in resp.lower() or 'removed' in resp.lower() or '删除成功' in resp:
        return True, '账号已删除'
    return False, resp


def get_player_info(username: str) -> Tuple[bool, str]:
    """查询玩家信息。"""
    cmd = _build_command('/auth getPlayerInfo', username)
    if not cmd:
        return False, 'MC 用户名包含非法字符'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 无应答'
    if resp.strip():
        return True, resp.strip()
    return False, '未找到该玩家信息'


def list_players() -> Tuple[bool, str]:
    """列出所有注册玩家。"""
    resp = _exec('/auth list')
    if not resp:
        return False, 'RCON 无应答'
    if resp.strip():
        return True, resp.strip()
    return False, '无玩家列表返回'