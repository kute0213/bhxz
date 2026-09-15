"""EasyAuth 数据库直连操作 —— 直接读写 SQLite 数据库验证/修改密码。

比 RCON 命令更可靠，不受 EasyAuth 插件版本/命令格式影响。
密码以 BCrypt 哈希存储在 data 字段（JSON）中。

自动发现路径（从 MC_GAME_FOLDER）：
  - {MC_GAME_FOLDER}/EasyAuth/easyauth.db  (最常用)
  - {MC_GAME_FOLDER}/plugins/EasyAuth/easyauth.db
  - {MC_GAME_FOLDER}/plugins/EasyAuth/players.db
  - {MC_GAME_FOLDER}/easyauth.db

表结构：
  CREATE TABLE easyauth (
    username TEXT NOT NULL,
    username_lower TEXT NOT NULL PRIMARY KEY,
    uuid TEXT,
    data TEXT NOT NULL  -- JSON: {"password": "$2a$12$...", ...}
  );
"""

import os
import json
import sqlite3
import logging
from typing import Optional, Tuple

import bcrypt

from config import get_config_value

logger = logging.getLogger(__name__)

# 候选数据库路径（相对 MC_GAME_FOLDER）
_CANDIDATE_PATHS = [
    'EasyAuth/easyauth.db',
    'plugins/EasyAuth/easyauth.db',
    'plugins/EasyAuth/players.db',
    'easyauth.db',
]

# 候选表名
_PLAYER_TABLES = ['easyauth', 'EasyAuth_players', 'auth_players', 'players']


def _get_game_folder() -> str:
    """获取 MC 游戏根目录。"""
    return (get_config_value('MC_GAME_FOLDER', '') or '').strip()


def _find_db_path() -> Optional[str]:
    """在 MC_GAME_FOLDER 下自动发现 EasyAuth 数据库文件。"""
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
    """自动发现并打开 EasyAuth 数据库连接。"""
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


def _get_player(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    """查询玩家数据行，优先精确匹配大小写，回退到模糊匹配。

    兼容多种表结构：
      - easyauth: 用 username_lower 查询，data（JSON）存密码
      - EasyAuth_players/players: 用 name 查询，password 字段直接存哈希
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

        try:
            # 尝试 easyauth 表结构（username_lower 为主键）
            cursor.execute(f"SELECT * FROM {table} WHERE username_lower = ?", (username.lower(),))
            rows = cursor.fetchall()
            if rows:
                # 优先精确匹配大小写
                for row in rows:
                    if row.get('username', '').lower() == username.lower() and row['username'] == username:
                        return dict(row)
                return dict(rows[0])  # 回退到第一条

            # 尝试 EasyAuth_players/players 表结构（name 字段）
            cursor.execute(f"SELECT * FROM {table} WHERE LOWER(name)=LOWER(?)", (username,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        except Exception as e:
            logger.debug('查询表 %s 失败: %s', table, e)
            continue

    return None


def _extract_password(player: dict) -> str:
    """从玩家数据中提取密码哈希。

    兼容两种存储方式：
      1. data 字段 JSON 中的 password 键（easyauth 表）
      2. password 字段直接存储（EasyAuth_players/players 表）
    """
    # 方式 1: data 字段 JSON
    raw_data = player.get('data')
    if raw_data:
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            if isinstance(data, dict):
                pwd = data.get('password') or data.get('hash') or ''
                if pwd:
                    return pwd
        except (json.JSONDecodeError, TypeError):
            pass

    # 方式 2: 直接 password 字段
    return player.get('password') or player.get('hash') or ''


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
        return False, 'EasyAuth 数据库未配置或不可用（请设置 MC_GAME_FOLDER）'

    try:
        player = _get_player(conn, username)
        if player is None:
            return False, '未找到该玩家信息'

        stored_hash = _extract_password(player)
        if not stored_hash:
            return False, '玩家密码数据为空'

        # BCrypt 验证
        try:
            if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                real_name = (player.get('username') or player.get('name') or username)
                return True, real_name
            return False, '密码验证失败: 密码错误'
        except (ValueError, TypeError) as e:
            logger.error('bcrypt 验证异常: %s', e)
            # 可能不是 BCrypt 哈希（如 Argon2），DB 不可用则降级
            return False, '密码哈希格式异常: %s' % e
    except Exception as e:
        logger.error('EasyAuth 数据库查询异常: %s', e)
        return False, '数据库查询失败: %s' % e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def change_password(username: str, new_password: str) -> Tuple[bool, str]:
    """通过直接写入 EasyAuth 数据库修改玩家密码。

    仅更新 data 字段中的 password 键，其他数据（UUID、2FA 等）完全不变。
    仅支持 easyauth 表结构（JSON data 字段），不支持旧版直列字段。

    Args:
        username: MC 玩家名
        new_password: 新密码

    Returns:
        (success, message)
    """
    conn = _open_db()
    if conn is None:
        return False, 'EasyAuth 数据库未配置或不可用'

    try:
        player = _get_player(conn, username)
        if player is None:
            return False, '未找到该玩家信息'

        # 检查是否为 easyauth 表（JSON data 字段）
        raw_data = player.get('data')
        if not raw_data:
            return False, '该玩家数据不支持数据库直连改密（缺少 data 字段）'

        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else dict(raw_data)
        except (json.JSONDecodeError, TypeError):
            return False, 'data 字段 JSON 解析失败'

        # 表名
        table = None
        cursor = conn.cursor()
        for t in _PLAYER_TABLES:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND LOWER(name)=LOWER(?)",
                (t,),
            )
            if cursor.fetchone():
                # 检查该表是否有 username_lower 列
                cursor.execute(f"PRAGMA table_info({t})")
                cols = [c[1] for c in cursor.fetchall()]
                if 'username_lower' in cols:
                    table = t
                    break

        if not table:
            return False, '未找到支持改密的表（需要 username_lower 列）'

        # 生成新 BCrypt 哈希（cost factor = 12，与 EasyAuth 默认一致）
        salt = bcrypt.gensalt(rounds=12)
        new_hash = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')

        # 只修改 password 字段，其余不变
        data['password'] = new_hash

        cursor.execute(
            f"UPDATE {table} SET data = ? WHERE username_lower = ?",
            (json.dumps(data), username.lower()),
        )
        conn.commit()

        if cursor.rowcount > 0:
            return True, '密码修改成功'
        return False, '密码修改失败（未找到匹配记录）'
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error('EasyAuth 改密异常: %s', e)
        return False, '改密失败: %s' % e
    finally:
        try:
            conn.close()
        except Exception:
            pass