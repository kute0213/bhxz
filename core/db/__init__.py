"""数据库访问层包 —— 基于 SQLite 实现，开启 WAL 模式。

主要改动：
- 使用 Python 内置 sqlite3，开启 WAL 模式 + 外键约束，并发读写与崩溃恢复更优
- 保持原有接口不变：get_db() 返回线程安全的连接对象，
  行对象支持 keys() 与 ['列名'] 访问
- 单例共享连接 + 可重入锁，保证多线程读写安全
"""

from core.db.connection import (
    get_db,
)
from core.db.schema import init_db

__all__ = ['get_db', 'init_db']
