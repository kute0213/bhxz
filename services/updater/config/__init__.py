"""一键更新服务 - 常量配置。"""

from collections import deque
import threading

# GitHub 归档路径格式
REPO_ARCHIVE_PATH = 'kute0213/bhxz/archive/refs/heads/main.zip'
REPO_FULL = 'kute0213/bhxz'

# 下载 URL 模板（proxy_base 替换为实际代理地址）
DOWNLOAD_URL_FORMATS = [
    '{proxy_base}{archive_path}',
    '{proxy_base}github.com/{archive_path}',
    '{proxy_base}https://github.com/{archive_path}',
]

# 可靠代理列表（按优先级，数量多、格式统一为 {proxy}/https://github.com/）
# 全部为 GitHub 加速代理/镜像，下载失败时自动顺延到下一个；
# 启动时会并发检测连通性与延迟，不可达的会被跳过。
RELIABLE_PROXIES = [
    ('gh-proxy.com', 'https://gh-proxy.com/https://github.com/', 'https://gh-proxy.com/https://github.com/{repo}'),
    ('ghproxy.net', 'https://ghproxy.net/https://github.com/', 'https://ghproxy.net/https://github.com/{repo}'),
    ('mirror.ghproxy.com', 'https://mirror.ghproxy.com/https://github.com/', 'https://mirror.ghproxy.com/https://github.com/{repo}'),
    ('ghfast.top', 'https://ghfast.top/https://github.com/', 'https://ghfast.top/https://github.com/{repo}'),
    ('github.moeyy.xyz', 'https://github.moeyy.xyz/https://github.com/', 'https://github.moeyy.xyz/https://github.com/{repo}'),
    ('slink.ltd', 'https://slink.ltd/https://github.com/', 'https://slink.ltd/https://github.com/{repo}'),
    ('gh.ddlc.top', 'https://gh.ddlc.top/https://github.com/', 'https://gh.ddlc.top/https://github.com/{repo}'),
    ('gh.h233.eu.org', 'https://gh.h233.eu.org/https://github.com/', 'https://gh.h233.eu.org/https://github.com/{repo}'),
    ('ghproxy.1888866.xyz', 'https://ghproxy.1888866.xyz/https://github.com/', 'https://ghproxy.1888866.xyz/https://github.com/{repo}'),
    ('hub.gitmirror.com', 'https://hub.gitmirror.com/https://github.com/', 'https://hub.gitmirror.com/https://github.com/{repo}'),
    ('gh-proxy.net', 'https://gh-proxy.net/https://github.com/', 'https://gh-proxy.net/https://github.com/{repo}'),
    ('github.boki.moe', 'https://github.boki.moe/https://github.com/', 'https://github.boki.moe/https://github.com/{repo}'),
    ('gh.llkk.cc', 'https://gh.llkk.cc/https://github.com/', 'https://gh.llkk.cc/https://github.com/{repo}'),
    ('kkgithub.com', 'https://kkgithub.com/https://github.com/', 'https://kkgithub.com/https://github.com/{repo}'),
]

# 默认不替换路径（从安全角度考虑，db 文件夹等必须保护）
DEFAULT_EXCLUDED = [
    'db', 'backups', 'uploads', 'ssl',
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