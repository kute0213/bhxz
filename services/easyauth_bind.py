"""EasyAuth 绑定账号 —— 通过游戏根目录路径验证密码并绑定到网站用户。

用户输入游戏根目录绝对路径、MC 用户名和密码，
通过读取 EasyAuth SQLite 数据库中的 BCrypt 哈希验证身份，
验证通过后将 MC 账号绑定到网站用户。

依赖：
  - bcrypt>=5.0.0（已添加至 requirements.txt）

安全说明：
  - 不在日志中记录明文密码
  - 密码仅在内存中比对，不存储
  - 使用参数化查询防止 SQL 注入
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, Tuple


def bind_account(server_path: str, username: str, password: str) -> dict:
    """验证密码并将 MC 账号绑定到网站用户。

    验证流程：
      1. 根据游戏根目录路径定位 EasyAuth 数据库
      2. 查询玩家记录（不区分大小写）
      3. 解析 data 字段中的 BCrypt 哈希
      4. 使用 bcrypt.checkpw 比对密码

    Args:
        server_path: 游戏根目录的绝对路径
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
    if not server_path or not server_path.strip():
        return _result(False, '游戏根目录不能为空', username, error_code='INVALID_INPUT')
    if not username or not username.strip():
        return _result(False, '用户名不能为空', username, error_code='INVALID_INPUT')
    if not password:
        return _result(False, '密码不能为空', username, error_code='INVALID_INPUT')
    if len(username) > 16:
        return _result(False, '用户名过长（MC 限制 16 字符）', username, error_code='INVALID_INPUT')

    # ── 第 1 步：构建数据库路径 ──
    try:
        db_path = os.path.join(server_path.strip(), 'EasyAuth', 'easyauth.db')
        db_path = str(Path(db_path).resolve())
    except Exception as e:
        return _result(False, f'路径解析失败: {e}', username, error_code='DB_NOT_FOUND')

    # ── 第 2 步：检查数据库文件是否存在 ──
    if not os.path.isfile(db_path):
        return _result(
            False,
            '未找到 EasyAuth 数据库文件，请确认游戏根目录路径正确',
            username,
            error_code='DB_NOT_FOUND',
        )

    # ── 第 3 步：读取数据库 ──
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            'SELECT * FROM easyauth WHERE username_lower = ?',
            (username.strip().lower(),),
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        return _result(False, f'数据库读取失败: {e}', username, error_code='DB_ERROR')

    # ── 第 4 步：检查玩家是否存在 ──
    if not rows:
        return _result(
            False,
            f"玩家 '{username}' 未在服务器注册",
            username,
            error_code='PLAYER_NOT_FOUND',
        )

    # 优先精确匹配原始大小写
    player = None
    for row in rows:
        if row['username'] == username:
            player = dict(row)
            break
    if player is None:
        player = dict(rows[0])

    # ── 第 5 步：解析密码哈希 ──
    try:
        data = json.loads(player['data'])
        stored_hash = data.get('password', '')
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return _result(
            False, '玩家数据解析失败', username,
            uuid=player.get('uuid'), error_code='HASH_ERROR',
        )

    if not stored_hash:
        return _result(
            False, '该玩家未设置密码，无法绑定', username,
            uuid=player.get('uuid'), error_code='HASH_ERROR',
        )

    # ── 第 6 步：BCrypt 密码比对 ──
    try:
        import bcrypt
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
            return _result(
                True, f"账号 '{player['username']}' 验证成功",
                player['username'], uuid=player.get('uuid'),
            )
        else:
            return _result(
                False, '密码错误，请重试', username,
                uuid=player.get('uuid'), error_code='WRONG_PASSWORD',
            )
    except ImportError:
        return _result(False, 'bcrypt 库未安装，请联系管理员', username, error_code='HASH_ERROR')
    except Exception as e:
        return _result(False, f'密码验证异常: {e}', username, error_code='HASH_ERROR')


def _result(success: bool, message: str, username: str, uuid: str = None, error_code: str = None) -> dict:
    """构建标准返回字典。"""
    return {
        'success': success,
        'message': message,
        'username': username,
        'uuid': uuid,
        'error_code': error_code,
    }