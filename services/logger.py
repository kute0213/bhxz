"""简单日志工具，提供统一格式的日志输出。"""

import sys
from datetime import datetime


def log(event: str, detail: str = '', **kwargs):
    """输出统一格式的日志。

    格式: [时间] [事件] 详情 key=val key=val
    示例: [2024-01-15 03:00:00] [Register] 注册成功 username=alice ip=127.0.0.1
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    parts = [f'[{now}] [{event}]', detail]
    for k, v in kwargs.items():
        parts.append(f'{k}={v}')
    print(' '.join(parts), flush=True)