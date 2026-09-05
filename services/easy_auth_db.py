"""EasyAuth 数据库直连验证 —— 直接读取 SQLite 数据库验证玩家密码。

比 RCON 命令更可靠，不受 EasyAuth 插件版本/命令格式影响。
密码存储为 bcrypt 哈希，通过 bcrypt.checkpw 验证。

配置方式：
  在管理后台设置 EASYAUTH_DB_PATH 为 EasyAuth 插件 SQLite 数据库路径，
  或在 .env 文件中设置 EASYAUTH_DB_PATH=/path/to/players.db。

表结构兼容性：
  - EasyAuth_players（Shevchik 版 EasyAuth，最常用）
  - auth_players
  - players
"""

import os
import sqlite3
import logging
from typing import Optional, Tuple

import bcrypt

from config import get_config_value

logger = logging.getLogger(__name__)

# 按优先级尝试的表名
_PLAYER_TABLES = ['EasyAuth_players', 'auth_players', 'players']


def _get_db_path() -> str:
    """获取 EasyAuth 数据库路径。"""
    path = get_config_value('EASYAUTH_DB_PATH', '') or os.environ.get('EASYAUTH_DB_PATH', '')
    return path.strip()


def _open_db() -> Optional[sqlite3.Connection]:
    """打开 EasyAuth 数据库连接。

    Returns:
        sqlite3.Connection 或 None（数据库不存在/无法打开）
    """
    path = _get_db_path()
    if not path:
        return None
    if not os.path.isfile(path):
        logger.warning('EasyAuth 数据库不存在: %s', path)
        return None
    try:
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error('打开 EasyAuth 数据库失败: %s', e)
        return None


def _find_player(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    """在多个可能的表中查找玩家记录。

    Args:
        conn: EasyAuth 数据库连接
        username: MC 玩家名

    Returns:
        玩家记录字典（含 password 字段）或 None
    """
    cursor = conn.cursor()
    for table in _PLAYER_TABLES:
        # 检查表是否存在
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND LOWER(name)=LOWER(?)",
            (table,),
        )
        if not cursor.fetchone():
            continue

        # 查询玩家（不区分大小写）
        try:
            cursor.execute(
                f"SELECT * FROM {table} WHERE LOWER(name)=LOWER(?)",
                (username,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        except Exception as e:
            logger.debug('查询表 %s 失败: %s', table, e)
            continue

    return None


def verify_password(username: str, password: str) -> Tuple[bool, str]:
    """通过直接读取 EasyAuth 数据库验证玩家密码。

    Args:
        username: MC 玩家名
        password: 明文密码

    Returns:
        (success, message_or_username)
        - 成功时返回 (True, 玩家真实名称)
        - 失败时返回 (False, 错误描述)
    """
    conn = _open_db()
    if conn is None:
        return False, 'EasyAuth 数据库未配置或不可用'

    try:
        player = _find_player(conn, username)
        if player is None:
            return False, '未找到该玩家信息'

        stored_hash = player.get('password') or player.get('hash') or ''
        if not stored_hash:
            return False, '玩家密码数据为空'

        # bcrypt 验证（密码和哈希均需 bytes）
        try:
            if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                # 返回数据库中的真实玩家名（保持原始大小写）
                real_name = player.get('name', username)
                return True, real_name
            return False, '密码验证失败: 密码错误'
        except (ValueError, TypeError) as e:
            logger.error('bcrypt 验证异常: %s', e)
            return False, f'密码哈希格式异常: {e}'
    except Exception as e:
        logger.error('EasyAuth 数据库查询异常: %s', e)
        return False, f'数据库查询失败: {e}'
    finally:
        try:
            conn.close()
        except Exception:
            pass