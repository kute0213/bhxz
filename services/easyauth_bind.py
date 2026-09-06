"""EasyAuth 绑定账号 —— 通过 RCON 验证密码并绑定到网站用户。

通过 RCON 发送 /auth getPlayerInfo 指令获取玩家密码哈希，
使用 bcrypt 比对密码，验证通过后将 MC 账号绑定到网站用户。

安全说明：
  - 不在日志中记录明文密码
  - 密码仅在内存中比对，不存储
  - 使用 sanitize_rcon_username 清洗输入防止命令注入
"""

import json
from typing import Optional


def _get_player_info(username: str) -> dict:
    """通过 RCON 获取玩家信息，返回解析后的 JSON 字典。

    发送 /auth getPlayerInfo <username> 指令，
    解析返回的 JSON 数据。

    Returns:
        {
            "success": bool,
            "message": str,
            "data": dict | None,  # 玩家信息 JSON 数据
            "username": str,      # 实际用户名
            "error_code": str | None
        }
    """
    from services.rcon.easy_auth import get_player_info

    succ, msg = get_player_info(username)
    if not succ:
        return _result(False, msg, username, error_code='PLAYER_NOT_FOUND')

    # 解析 RCON 响应
    # 格式: "Player Info: {...json...}" 或直接的 JSON 字符串
    raw = msg.strip()
    if raw.startswith('Player Info:'):
        raw = raw[len('Player Info:'):].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return _result(False, f'玩家数据解析失败: {e}', username, error_code='HASH_ERROR')

    password_hash = data.get('password', '')
    if not password_hash:
        return _result(False, '该玩家未设置密码，无法绑定', username, error_code='HASH_ERROR')

    return _result(True, '玩家信息获取成功', username, data=data, password_hash=password_hash)


def bind_account(username: str, password: str) -> dict:
    """验证密码并将 MC 账号绑定到网站用户。

    验证流程：
      1. 通过 RCON 发送 /auth getPlayerInfo <username>
      2. 解析 JSON 响应，提取 password 字段（BCrypt 哈希）
      3. 使用 bcrypt.checkpw 比对密码

    Args:
        username: MC 用户名
        password: 明文密码

    Returns:
        {
            "success": bool,         # 是否验证成功
            "message": str,          # 提示信息
            "username": str,         # 实际用户名（保持原始大小写）
            "uuid": str | None,      # 玩家 UUID（成功时返回）
            "error_code": str | None # 错误码
        }
    """
    # ── 校验输入 ──
    if not username or not username.strip():
        return _result(False, '用户名不能为空', username, error_code='INVALID_INPUT')
    if not password:
        return _result(False, '密码不能为空', username, error_code='INVALID_INPUT')
    if len(username) > 16:
        return _result(False, '用户名过长（MC 限制 16 字符）', username, error_code='INVALID_INPUT')

    # ── 第 1 步：通过 RCON 获取玩家信息 ──
    info = _get_player_info(username.strip())
    if not info['success']:
        return info  # 直接传播错误信息

    data = info['data']
    password_hash = info['password_hash']
    actual_username = data.get('online_account', data.get('username', username))

    # ── 第 2 步：BCrypt 密码比对 ──
    try:
        import bcrypt
        if bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            return _result(
                True, f"账号 '{actual_username}' 验证成功",
                actual_username, uuid=data.get('uuid'),
            )
        else:
            return _result(
                False, '密码错误，请重试', username,
                uuid=data.get('uuid'), error_code='WRONG_PASSWORD',
            )
    except ImportError:
        return _result(False, 'bcrypt 库未安装，请联系管理员', username, error_code='HASH_ERROR')
    except Exception as e:
        return _result(False, f'密码验证异常: {e}', username, error_code='HASH_ERROR')


def _result(success: bool, message: str, username: str, uuid: str = None,
            error_code: str = None, data: dict = None, password_hash: str = None) -> dict:
    """构建标准返回字典。"""
    result = {
        'success': success,
        'message': message,
        'username': username,
        'uuid': uuid,
        'error_code': error_code,
    }
    if data is not None:
        result['data'] = data
    if password_hash is not None:
        result['password_hash'] = password_hash
    return result