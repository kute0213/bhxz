"""数据库访问层包 —— 基于 DuckDB 实现，提供类 sqlite3 兼容接口。

主要改动：
- 使用 DuckDB 替换 SQLite，性能更高，支持窗口函数、列存等高级特性
- 封装 DuckDBConnection 提供与 sqlite3 相似的接口（row_factory、lastrowid、commit/close 等）
- 使用 SEQUENCE + nextval 模拟 AUTOINCREMENT，INSERT 后通过 currval / MAX(id) 获取 lastrowid
- 每个 get_db() 调用返回独立连接（DuckDB 多连接安全，支持 WAL 模式）
"""

from core.db.connection import (
    DuckDBConnection,
    DuckDBCursor,
    DuckDBRow,
    get_db,
)
from core.db.schema import init_db

__all__ = ['get_db', 'init_db', 'DuckDBConnection', 'DuckDBRow', 'DuckDBCursor']
