"""访问日志抓取服务 —— 对外统一入口。

管理界面通过本模块开启 / 取消抓取；请求中间件通过
:func:`should_capture_request` 与 :func:`record_access` 写入访问记录；
管理页的 SSE 接口通过 :func:`subscribe` / :func:`unsubscribe` 接收实时数据。

数据库文件：``uploads/db/access_logs.duckdb``（独立于主站 SQLite 与防火墙 DuckDB），
取消抓取时自动删除。
"""

from services.access_log.capture import (
    get_status,
    is_capturing,
    record_access,
    should_capture_request,
    start_capture,
    stop_capture,
    subscribe,
    unsubscribe,
)
from services.access_log.store import DB_PATH, query_recent

__all__ = [
    'DB_PATH',
    'get_status',
    'is_capturing',
    'query_recent',
    'record_access',
    'should_capture_request',
    'start_capture',
    'stop_capture',
    'subscribe',
    'unsubscribe',
]
