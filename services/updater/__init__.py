"""一键更新服务包 —— 后台线程下载 GitHub 最新代码并安全替换文件。

核心流程：
1. 检测可用的 GitHub 代理
2. 通过代理下载 ZIP 压缩包
3. 解压并同步文件（跳过受保护路径）
4. 重启服务器
"""

from services.updater.config import (
    REPO_ARCHIVE_PATH,
    REPO_FULL,
    DOWNLOAD_URL_FORMATS,
    RELIABLE_PROXIES,
    DEFAULT_EXCLUDED,
)
from services.updater.core import (
    get_status,
    pop_events,
    start_update,
    detect_fastest_proxy,
)

__all__ = [
    'REPO_ARCHIVE_PATH', 'REPO_FULL', 'DOWNLOAD_URL_FORMATS',
    'RELIABLE_PROXIES', 'DEFAULT_EXCLUDED',
    'get_status', 'pop_events', 'start_update', 'detect_fastest_proxy',
]