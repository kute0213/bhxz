"""EasyAuth 绑定账号 —— 通过多重验证方式验证密码并绑定到网站用户。

验证流程：
  1. EasyAuth 数据库直连验证（需配置 EASYAUTH_DB_PATH）
  2. RCON /auth checkpassword 指令
  3. RCON /auth login 指令
  4. RCON /login 指令

安全说明：
  - 不在日志中记录明文密码
  - 密码仅在内存中比对，不存储
  - 使用 sanitize_rcon_username 清洗输入防止命令注入
"""


def bind_account(username: str, password: str) -> dict:
    """验证密码并将 MC 账号绑定到网站用户。

    验证流程：
      1. 优先通过 EasyAuth 数据库直连验证（需配置 EASYAUTH_DB_PATH）
      2. 数据库不可用时，依次尝试 RCON 命令：
         - /auth checkpassword <user> <pwd>
         - /auth login <user> <pwd>
         - /login <user> <pwd>

    Args:
        username: MC 用户名
        password: 明文密码

    Returns:
        { success, message, username, uuid, error_code }
    """
    from services.rcon.easy_auth import verify_login

    # ── 校验输入 ──
    username = username.strip()
    if not username:
        return _result(False, 'MC 用户名不能为空', username, error_code='INVALID_INPUT')
    if not password:
        return _result(False, '密码不能为空', username, error_code='INVALID_INPUT')
    if len(username) > 16:
        return _result(False, 'MC 用户名过长（限制 16 字符）', username, error_code='INVALID_INPUT')

    # ── 调用 verify_login 多重验证 ──
    succ, msg = verify_login(username, password)
    if succ:
        # msg 是实际用户名（可能包含大小写修正）
        actual_username = msg
        return _result(
            True, f"账号 '{actual_username}' 验证成功",
            actual_username,
        )
    else:
        return _result(False, msg, username, error_code='VERIFY_FAILED')


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