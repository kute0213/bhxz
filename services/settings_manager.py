"""系统设置管理器 —— 支持通过管理后台在线编辑配置并热重载。

设计原则：
- 默认值定义在 config.py 中
- 用户在管理后台修改后，值存入 settings 表
- 运行时调用 get_setting(key) 获取值，自动优先从数据库读取
- 支持类型转换（int, float, str, bool）
"""

import threading
import time
from datetime import datetime

from core.db import get_db
from services.logger import log


# ---------------------------------------------------------------------------
# 类型转换辅助
# ---------------------------------------------------------------------------

def _cast_value(raw: str, default):
    """将字符串值转换为默认值的类型。"""
    if raw is None or raw == '':
        return default

    if isinstance(default, bool):
        return raw.lower() in ('1', 'true', 'yes', 'on')
    if isinstance(default, int):
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except (ValueError, TypeError):
            return default
    return raw


def _value_to_string(value) -> str:
    """将任何值转为字符串存储。"""
    if isinstance(value, bool):
        return '1' if value else '0'
    return str(value)


# ---------------------------------------------------------------------------
# 设置管理器
# ---------------------------------------------------------------------------

class SettingsManager:
    """系统设置管理器（单例）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._cache = {}          # 内存缓存 {key: value}
        self._cache_ts = {}       # 缓存时间戳 {key: timestamp}
        self._cache_lock = threading.Lock()
        self._dirty = True        # 首次访问强制刷新
        self._refresh_interval = 5  # 缓存刷新间隔（秒）

    def _is_cache_fresh(self, key: str) -> bool:
        """检查缓存是否新鲜。"""
        with self._cache_lock:
            if self._dirty:
                return False
            ts = self._cache_ts.get(key, 0)
            return (time.time() - ts) < self._refresh_interval

    def _load_from_db(self, key: str, default):
        """从数据库加载单个设置值。"""
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            conn.close()

            if row:
                raw_value = row['value'] if hasattr(row, '__getitem__') else row[0]
                return _cast_value(raw_value, default)
        except Exception as e:
            log('ERROR', 'SettingsManager', f'加载设置 {key} 失败: {e}')
        return default

    def _save_to_db(self, key: str, value):
        """保存单个设置到数据库。"""
        str_value = _value_to_string(value)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            conn = get_db()
            # UPSERT：存在则更新，不存在则插入
            conn.execute(
                """INSERT INTO settings (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT (key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at
                """,
                (key, str_value, now)
            )
            conn.commit()
            conn.close()

            # 更新缓存
            with self._cache_lock:
                self._cache[key] = value
                self._cache_ts[key] = time.time()
        except Exception as e:
            log('ERROR', 'SettingsManager', f'保存设置 {key} 失败: {e}')
            raise

    # -------------------------------------------------------------------
    # 公共 API
    # -------------------------------------------------------------------

    def get(self, key: str, default=None):
        """获取单个设置值。"""
        if self._is_cache_fresh(key):
            with self._cache_lock:
                return self._cache.get(key, default)

        value = self._load_from_db(key, default)
        with self._cache_lock:
            self._cache[key] = value
            self._cache_ts[key] = time.time()
        return value

    def set(self, key: str, value):
        """设置单个设置值（持久化到数据库并更新缓存）。"""
        self._save_to_db(key, value)

    def bulk_set(self, items: dict):
        """批量设置多个设置值。"""
        conn = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            for key, value in items.items():
                str_value = _value_to_string(value)
                conn.execute(
                    """INSERT INTO settings (key, value, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT (key) DO UPDATE SET
                           value = excluded.value,
                           updated_at = excluded.updated_at
                    """,
                    (key, str_value, now)
                )
            conn.commit()
        finally:
            conn.close()

        # 更新缓存
        with self._cache_lock:
            for key, value in items.items():
                self._cache[key] = value
                self._cache_ts[key] = time.time()

    def delete(self, key: str):
        """删除单个设置（恢复默认值）。"""
        try:
            conn = get_db()
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            conn.close()
        except Exception as e:
            log('ERROR', 'SettingsManager', f'删除设置 {key} 失败: {e}')
            raise

        with self._cache_lock:
            self._cache.pop(key, None)
            self._cache_ts.pop(key, None)

    def get_all(self):
        """获取所有数据库中存储的设置。"""
        try:
            conn = get_db()
            rows = conn.execute(
                "SELECT key, value, description, updated_at FROM settings ORDER BY key ASC"
            ).fetchall()
            conn.close()
            return [dict(row) if hasattr(row, 'keys') else {
                'key': row[0], 'value': row[1],
                'description': row[2] if len(row) > 2 else '',
                'updated_at': row[3] if len(row) > 3 else ''
            } for row in rows]
        except Exception as e:
            log('ERROR', 'SettingsManager', f'获取所有设置失败: {e}')
            return []

    def invalidate_cache(self):
        """强制刷新缓存（手动调用）。"""
        with self._cache_lock:
            self._dirty = True
            self._cache.clear()
            self._cache_ts.clear()


# 全局单例
settings_manager = SettingsManager()


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def get_setting(key: str, default=None):
    """获取设置值（便捷函数）。"""
    return settings_manager.get(key, default)


def set_setting(key: str, value):
    """设置设置值（便捷函数）。"""
    settings_manager.set(key, value)


def get_all_settings():
    """获取所有设置（便捷函数）。"""
    return settings_manager.get_all()
