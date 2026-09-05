"""EasyAuth 插件指令封装 —— 注册、改密、删除、查询等。

密码验证优先使用数据库直连（services/easy_auth_db），
仅当数据库未配置或不可用时，才通过 RCON 命令验证。

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
        return False, 'RCON 连接失败，请检查 RCON 配置'
    if 'successfully' in resp.lower() or '注册成功' in resp or 'created' in resp.lower():
        return True, '账号注册成功'
    return False, resp or '注册失败，未知错误'


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
        return False, 'RCON 连接失败，请检查 RCON 配置'
    if 'successfully' in resp.lower() or '更新成功' in resp or 'updated' in resp.lower():
        return True, '密码修改成功'
    return False, resp or '修改密码失败，未知错误'


def remove_player(username: str) -> Tuple[bool, str]:
    """删除游戏内账号。"""
    cmd = _build_command('/auth remove', username)
    if not cmd:
        return False, 'MC 用户名包含非法字符'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 连接失败，请检查 RCON 配置'
    if 'successfully' in resp.lower() or 'removed' in resp.lower() or '删除成功' in resp:
        return True, '账号已删除'
    return False, resp or '删除失败，未知错误'


def get_player_info(username: str) -> Tuple[bool, str]:
    """查询玩家信息。"""
    cmd = _build_command('/auth getPlayerInfo', username)
    if not cmd:
        return False, 'MC 用户名包含非法字符'
    resp = _exec(cmd)
    if not resp:
        return False, 'RCON 连接失败'
    if resp.strip():
        return True, resp.strip()
    return False, '未找到该玩家信息'


def verify_login(username: str, password: str) -> Tuple[bool, str]:
    """验证玩家密码是否正确。

    验证流程（按优先级）：
    1. 尝试通过 EasyAuth 数据库直连验证（需配置 EASYAUTH_DB_PATH）
    2. 失败或未配置时，依次尝试 RCON 命令：
       - /auth checkpassword
       - /auth login
       - /login 带用户名
       - /login 仅密码

    注意：返回 (成功, 消息) 元组，成功时消息为玩家真实名称。

    Args:
        username: MC 玩家名
        password: 密码

    Returns:
        (success, message_or_error)
    """
    safe_user = sanitize_rcon_username(username)
    if not safe_user:
        return False, 'MC 用户名包含非法字符'
    safe_pwd = sanitize_rcon_password(password)
    if not safe_pwd:
        return False, '密码不能为空'

    # -----------------------------------------------------------------------
    # 1. EasyAuth 数据库直连验证（优先，需配置 MC_GAME_FOLDER）
    # -----------------------------------------------------------------------
    try:
        from services.easy_auth_db import verify_password as db_verify
        db_ok, db_msg = db_verify(safe_user, password)
        if db_ok:
            return True, db_msg
        if '密码错误' in db_msg:
            return False, db_msg
    except Exception as e:
        # 数据库验证异常（如 bcrypt 版本不兼容、数据库文件损坏等），降级到 RCON
        import logging
        logging.getLogger(__name__).error('EasyAuth 数据库验证异常: %s', e)

    # 数据库未配置或不可用，继续尝试 RCON 命令
    # -----------------------------------------------------------------------
    # 2. /auth checkpassword 指令（EasyAuth 控制台密码验证命令）
    # -----------------------------------------------------------------------
    cmd = f'/auth checkpassword {safe_user} {safe_pwd}'
    resp = _exec(cmd)
    if resp:
        resp_lower = resp.lower()
        if ('password correct' in resp_lower or 'password matches' in resp_lower
                or '验证成功' in resp or '密码正确' in resp
                or 'successfully authenticated' in resp_lower):
            return True, safe_user
        if ('password incorrect' in resp_lower or 'password doesn\'t match' in resp_lower
                or '密码错误' in resp or '验证失败' in resp
                or 'incorrect password' in resp_lower):
            return False, '密码验证失败: 密码错误'

    # -----------------------------------------------------------------------
    # 3. /auth login 指令（部分 EasyAuth 版本支持）
    # -----------------------------------------------------------------------
    cmd2 = f'/auth login {safe_user} {safe_pwd}'
    resp2 = _exec(cmd2)
    if resp2:
        resp2_lower = resp2.lower()
        if ('successfully authenticated' in resp2_lower or '登录成功' in resp2
                or 'logged in' in resp2_lower or '验证成功' in resp2):
            return True, safe_user

    # -----------------------------------------------------------------------
    # 4. /login 带用户名（部分 EasyAuth 版本支持）
    # -----------------------------------------------------------------------
    cmd3 = f'/login {safe_user} {safe_pwd}'
    resp3 = _exec(cmd3)
    if resp3:
        resp3_lower = resp3.lower()
        if ('successfully authenticated' in resp3_lower or '登录成功' in resp3
                or 'logged in' in resp3_lower or '验证成功' in resp3):
            return True, safe_user

    # -----------------------------------------------------------------------
    # 5. /login 仅密码（客户端模式，兼容性兜底）
    # -----------------------------------------------------------------------
    cmd4 = f'/login {safe_pwd}'
    resp4 = _exec(cmd4)
    if resp4:
        resp4_lower = resp4.lower()
        if ('successfully authenticated' in resp4_lower or '登录成功' in resp4
                or 'logged in' in resp4_lower or '验证成功' in resp4):
            return True, safe_user

    # 组合错误信息
    err = resp or resp2 or resp3 or resp4 or 'RCON 连接失败，请检查 RCON 配置'
    return False, f'密码验证失败: {err}'


def list_players() -> Tuple[bool, str]:
    """列出所有注册玩家。"""
    resp = _exec('/auth list')
    if not resp:
        return False, 'RCON 连接失败'
    if resp.strip():
        return True, resp.strip()
    return False, '无玩家列表返回'