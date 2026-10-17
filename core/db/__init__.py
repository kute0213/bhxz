"""数据库访问层包 —— 基于原生 sqlite3 实现，开启 WAL 模式。

对外接口：
- get_db()：每次返回一条全新的原生连接，调用方用完 close()，不做任何连接复用
- transaction()：事务上下文管理器，块内多条语句原子提交/回滚，退出时关闭连接
- backup_to(path)：SQLite 在线备份
- checkpoint()：把 WAL 中已提交数据合并落盘（TRUNCATE）
- init_db()：建表与默认数据（幂等）
"""

from core.db.connection import (
    get_db,
    transaction,
    backup_to,
    checkpoint,
)
from core.db.schema import init_db

__all__ = ['get_db', 'transaction', 'backup_to', 'checkpoint', 'init_db']
