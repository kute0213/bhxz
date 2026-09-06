"""EasyAuth 绑定账号 —— 通过 RCON /auth getPlayerInfo 获取密码哈希，使用 bcrypt 验证。

验证流程：
  1. 通过 RCON 向服务器发送 /auth getPlayerInfo <username>
  2. 解析返回的 JSON 获取 password 字段（bcrypt 哈希）
  3. 使用 bcrypt 验证用户输入密码
  4. 通过后执行绑定

安全说明：
  - 密码仅在内存中比对，不存储
  - 使用 sanitize_rcon_username 清洗输入防止命令注入
"""

import json
import bcrypt


def bind_account(username: str, password: str) -> dict:
    """验证密码并将 MC 账号绑定到网站用户。

    通过 RCON 获取玩家信息（含密码哈希），使用 bcrypt 验证密码。

    Args:
        username: MC 用户名
        password: 明文密码

    Returns:
        { success, message, username, uuid, error_code, password_hash }
    """
    from services.rcon.easy_auth import get_player_info

    # ── 校验输入 ──
    username = username.strip()
    if not username:
        return _result(False, 'MC 用户名不能为空', username, error_code='INVALID_INPUT')
    if not password:
        return _result(False, '密码不能为空', username, error_code='INVALID_INPUT')
    if len(username) > 16:
        return _result(False, 'MC 用户名过长（限制 16 字符）', username, error_code='INVALID_INPUT')

    # ── 1. 获取玩家信息 ──
    ok, msg = get_player_info(username)
    if not ok:
        if 'RCON 无应答' in msg or 'RCON 连接失败' in msg:
            return _result(False, 'RCON 连接失败，无法验证密码，请联系管理员检查服务器状态',
                           username, error_code='RCON_FAILED')
        return _result(False, msg, username, error_code='PLAYER_INFO_FAILED')

    # ── 2. 解析 JSON ──
    # 预期格式：Player Info: {"password":"$2a$12$...","last_ip":"...",...}
    raw = msg.strip()
    if raw.startswith('Player Info:'):
        raw = raw[len('Player Info:'):].strip()

    try:
        player_data = json.loads(raw)
    except json.JSONDecodeError:
        return _result(False, '无法解析服务器返回的玩家信息',
                       username, error_code='PARSE_FAILED')

    stored_hash = player_data.get('password')
    if not stored_hash:
        return _result(False, '未找到该玩家的密码信息',
                       username, error_code='NO_PASSWORD')

    # ── 3. bcrypt 验证密码 ──
    try:
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode('utf-8')
        if not bcrypt.checkpw(password.encode('utf-8'), stored_hash):
            return _result(False, '密码验证失败',
                           username, error_code='WRONG_PASSWORD')
    except Exception as e:
        return _result(False, f'密码验证失败: {e}',
                       username, error_code='VERIFY_ERROR')

    # ── 4. 验证成功 ──
    uuid = player_data.get('uuid')
    return _result(
        True, f"账号 '{username}' 验证成功",
        username, uuid=uuid,
        password_hash=stored_hash.decode('utf-8') if isinstance(stored_hash, bytes) else stored_hash,
    )


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