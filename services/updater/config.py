"""一键更新服务 - 常量配置。"""

from collections import deque
import threading

# GitHub 归档路径格式
REPO_ARCHIVE_PATH = 'kute0213/bhxz/archive/refs/heads/main.zip'
REPO_FULL = 'kute0213/bhxz'

# 下载 URL 模板（proxy_base 替换为实际代理地址）
DOWNLOAD_URL_FORMATS = [
    '{proxy_base}{archive_path}',
]

# 可靠代理列表（按优先级，数量少且经过验证）
RELIABLE_PROXIES = [
    ('ghp.ci', 'https://ghp.ci/https://github.com/', 'https://ghp.ci/https://github.com/{repo}'),
    ('ghproxy.com', 'https://ghproxy.com/https://github.com/', 'https://ghproxy.com/https://github.com/{repo}'),
    ('github.moeyy.xyz', 'https://github.moeyy.xyz/https://github.com/', 'https://github.moeyy.xyz/https://github.com/{repo}'),
    ('slink.ltd', 'https://slink.ltd/https://github.com/', 'https://slink.ltd/https://github.com/{repo}'),
]

# 默认不替换路径（从安全角度考虑，site.duckdb 等必须保护）
DEFAULT_EXCLUDED = [
    'site.duckdb', 'site.duckdb.wal', 'backups', 'uploads', 'ssl',
    '.env', '.git', '__pycache__',
]

# 内部状态
_update_state = {
    'running': False,
    'progress': 0,
    'message': '',
    'done': False,
    'success': False,
    'error': None,
    'events': deque(maxlen=5000),
    'lock': threading.Lock(),
}