"""EasyAuth 数据库直连验证 —— 从 MC_GAME_FOLDER 自动发现数据库并验证密码。

比 RCON 命令更可靠，不受 EasyAuth 插件版本/命令格式影响。
密码存储为 bcrypt 哈希，通过 bcrypt.checkpw 验证。

自动发现路径（按优先级）：
  - {MC_GAME_FOLDER}/plugins/EasyAuth/players.db   (Shevchik Bukkit)
  - {MC_GAME_FOLDER}/plugins/EasyAuth/easyauth.db  (Bukkit 变体)
  - {MC_GAME_FOLDER}/EasyAuth/easyauth.db           (Fabric 变体)
  - {MC_GAME_FOLDER}/easyauth.db                    (根目录变体)
  - {MC_GAME_FOLDER}/config/easyauth.db             (config 目录变体)

支持的表格名（按优先级）：
  - EasyAuth_players, auth_players, players, easyauth
"""

import os
import sqlite3
import logging
from typing import Optional, Tuple

import bcrypt

from config import get_config_value

logger = logging.getLogger(__name__)

# 按优先级尝试的数据库路径（相对 MC_GAME_FOLDER）
_CANDIDATE_PATHS = [
    'plugins/EasyAuth/players.db',
    'plugins/EasyAuth/easyauth.db',
    'EasyAuth/easyauth.db',
    'easyauth.db',
    'config/easyauth.db',
]

# 按优先级尝试的表名
_PLAYER_TABLES = ['EasyAuth_players', 'auth_players', 'players', 'easyauth']


def _get_game_folder() -> str:
    """获取 MC 游戏根目录。"""
    return (get_config_value('MC_GAME_FOLDER', '') or '').strip()


def _find_db_path() -> Optional[str]:
    """在 MC_GAME_FOLDER 下自动发现 EasyAuth 数据库文件。

    Returns:
        数据库绝对路径，或 None（未找到）
    """
    game_folder = _get_game_folder()
    if not game_folder:
        return None
    if not os.path.isdir(game_folder):
        logger.warning('MC_GAME_FOLDER 目录不存在: %s', game_folder)
        return None

    for rel_path in _CANDIDATE_PATHS:
        abs_path = os.path.join(game_folder, rel_path)
        if os.path.isfile(abs_path):
            logger.info('发现 EasyAuth 数据库: %s', abs_path)
            return abs_path

    return None


def _open_db() -> Optional[sqlite3.Connection]:
    """自动发现并打开 EasyAuth 数据库连接。

    Returns:
        sqlite3.Connection 或 None（未找到/无法打开）
    """
    path = _find_db_path()
    if not path:
        return None
    try:
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error('打开 EasyAuth 数据库失败 (%s): %s', path, e)
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
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND LOWER(name)=LOWER(?)",
                (table,),
            )
            if not cursor.fetchone():
                continue
        except Exception:
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

    自动从 MC_GAME_FOLDER 下发现数据库文件，无需手动配置路径。

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

        # 尝试多个可能的密码列名
        stored_hash = (
            player.get('password')
            or player.get('hash')
            or player.get('hashed_password')
            or ''
        )
        if not stored_hash:
            return False, '玩家密码数据为空'

        # bcrypt 验证（密码和哈希均需 bytes）
        try:
            if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
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