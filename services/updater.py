"""
一键更新服务：从 GitHub 获取最新代码，全量同步到本地，自动重启。

安全策略：
- 下载 GitHub 仓库 ZIP 压缩包，使用系统临时目录解压
- 遍历仓库根目录所有项目
- 每个项目：如果不在不替换列表 → 删除本地版本 → 复制新版本
- 不替换的文件列表可在管理后台一键更新页面设置
- 更新后自动重启进程
- 跨平台兼容（Windows/Linux/macOS）
- 自动检测最快代理（带详细日志）
- 无需安装 Git，纯 HTTP 下载

下载方式（替代 git clone）：
- 使用 ZIP 压缩包下载（archive/refs/heads/main.zip），纯 HTTP 请求
- 代理兼容性更好（git 协议常被屏蔽，HTTP 更稳定）
- 最后兜底直连 GitHub 原始归档
"""

import os
import sys
import shutil
import zipfile
import tempfile
import threading
import time
import json
import subprocess
import random
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 项目根目录
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# GitHub 仓库地址
GITHUB_REPO = 'https://github.com/kute0213/bhxz.git'

# ZIP 压缩包路径（用于 HTTP 下载，替代 git clone）
# 下载后解压，顶层目录名为 kute0213-bhxz-main
REPO_ARCHIVE_PATH = 'kute0213/bhxz/archive/refs/heads/main.zip'

# 默认不替换的路径（相对项目根目录），运行时还会合并设置的排除列表
DEFAULT_PROTECTED_PATHS = [
    'site.duckdb',
    'site.duckdb.wal',
    'backups',
    'uploads',
    'ssl',
    '.env',
    '.git',
    '__pycache__',
]

# 默认 GitHub 代理列表（仅代理，不包含直连 — 直连在用户环境不可用）
# 格式：(名称, 代理前缀URL, 下载URL模板)
# 代理前缀URL: 代理服务的首页，用于检测代理是否可达（不包含 /https://github.com 后缀）
# 下载URL模板: 实际用于 HTTP 下载的完整 URL，{repo} 会被替换为仓库归档路径
# 按可靠性排序，最快的在前，分批检测时第一批命中即可早停
DEFAULT_PROXY_LIST = [
    ('github.akams.cn',   'https://github.akams.cn/',            'https://github.akams.cn/{repo}'),
    ('gh.idayer.com',     'https://gh.idayer.com/',               'https://gh.idayer.com/{repo}'),
    ('ghproxy.net',       'https://ghproxy.net/',                 'https://ghproxy.net/{repo}'),
    ('ghfast.top',        'https://ghfast.top/',                  'https://ghfast.top/{repo}'),
    ('ghproxy.cxkpro.top','https://ghproxy.cxkpro.top/',         'https://ghproxy.cxkpro.top/{repo}'),
    ('mirror.ghproxy.com','https://mirror.ghproxy.com/',          'https://mirror.ghproxy.com/{repo}'),
    ('gh-proxy.netlify.app','https://gh-proxy.netlify.app/',      'https://gh-proxy.netlify.app/{repo}'),
    ('github.moeyy.xyz',  'https://github.moeyy.xyz/',           'https://github.moeyy.xyz/{repo}'),
    ('ghp.ci',            'https://ghp.ci/',                      'https://ghp.ci/{repo}'),
    ('gh.zwy.one',        'https://gh.zwy.one/',                 'https://gh.zwy.one/{repo}'),
    ('gh.dcm.so',         'https://gh.dcm.so/',                   'https://gh.dcm.so/{repo}'),
    ('hub.gitmirror.com', 'https://hub.gitmirror.com/',           'https://hub.gitmirror.com/{repo}'),
    ('ghproxy.yaoyaoling.net','https://ghproxy.yaoyaoling.net/', 'https://ghproxy.yaoyaoling.net/{repo}'),
    ('gitproxy.188706.xyz','https://gitproxy.188706.xyz/',       'https://gitproxy.188706.xyz/{repo}'),
    ('gh-proxy.lhr.ltd',  'https://gh-proxy.lhr.ltd/',           'https://gh-proxy.lhr.ltd/{repo}'),
]

# ---------------------------------------------------------------------------
# 更新状态（供 SSE 流读取）
# ---------------------------------------------------------------------------

_update_state = {
    'running': False,
    'progress': 0,
    'message': '',
    'done': False,
    'success': False,
    'error': None,
    'events': [],  # 事件队列 [(event_type, data), ...]
    'lock': threading.Lock(),
}


def _add_event(event_type, data):
    """添加 SSE 事件。"""
    with _update_state['lock']:
        _update_state['events'].append((event_type, data))
        _update_state['message'] = data.get('message', '')
        if event_type == 'progress':
            _update_state['progress'] = data.get('percent', 0)
        elif event_type == 'error':
            _update_state['error'] = data.get('message', '')
            _update_state['done'] = True
            _update_state['running'] = False
        elif event_type == 'done':
            _update_state['done'] = True
            _update_state['success'] = data.get('success', False)
            _update_state['running'] = False


def pop_events():
    """获取并清空事件队列（供 SSE 路由调用）。"""
    with _update_state['lock']:
        events = list(_update_state['events'])
        _update_state['events'].clear()
    return events


def get_status():
    """获取当前状态（供轮询调用）。"""
    with _update_state['lock']:
        return {
            'running': _update_state['running'],
            'progress': _update_state['progress'],
            'message': _update_state['message'],
            'done': _update_state['done'],
            'success': _update_state['success'],
            'error': _update_state['error'],
        }


# ---------------------------------------------------------------------------
# 代理检测（带详细日志）
# ---------------------------------------------------------------------------

# 代理检测结果缓存（供日志查看）
_proxy_test_results = []
_proxy_test_lock = threading.Lock()


def _build_test_url(proxy_base_url):
    """构建测试 URL：直接使用代理首页 URL（轻量，不跟随重定向）。"""
    return proxy_base_url.rstrip('/') + '/'


def _test_proxy_timeout(proxy_name, proxy_base_url, proxy_clone_template, timeout=4):
    """测试代理的响应时间，返回详细结果字典。

    关键改进：
    - 使用 GET 请求（HEAD 请求很多代理不支持，会导致误判）
    - 不跟随 HTTP 重定向，代理返回 3xx 说明代理本身可用
    - HTTPError（4xx/5xx）单独处理：代理返回了响应说明可达，不判为失败
    - 只有网络级错误（DNS/连接超时/SSL握手失败）才判为失败

    返回结果字典:
        status: 'success' 表示代理可达，'fail' 表示代理不可达
    """
    test_url = _build_test_url(proxy_base_url)

    # 自定义 opener：不跟随重定向
    from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler

    class NoRedirectHandler(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # 不跟随重定向
        def http_error_302(self, req, fp, code, msg, headers):
            return fp  # 返回响应本身，不抛异常
        http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    ctx = _create_ssl_context()
    opener = build_opener(NoRedirectHandler, HTTPSHandler(context=ctx))

    start = time.time()
    try:
        req = Request(test_url, method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = opener.open(req, timeout=timeout)
        elapsed = time.time() - start
        # 2xx/3xx 响应 = 代理可达
        return {
            'name': proxy_name,
            'url': proxy_base_url,
            'clone_template': proxy_clone_template,
            'test_url': test_url,
            'elapsed': round(elapsed, 2),
            'status': 'success',
            'error': f'HTTP {resp.status}',
        }
    except HTTPError as e:
        elapsed = time.time() - start
        # HTTPError（4xx/5xx）: 代理服务器有响应，说明代理本身是可达的！
        return {
            'name': proxy_name,
            'url': proxy_base_url,
            'clone_template': proxy_clone_template,
            'test_url': test_url,
            'elapsed': round(elapsed, 2),
            'status': 'success',
            'error': f'HTTP {e.code} (proxy reachable)',
        }
    except URLError as e:
        # URLError: 网络级错误，代理不可达
        reason = _get_urlerror_reason(e)
        return {
            'name': proxy_name,
            'url': proxy_base_url,
            'clone_template': proxy_clone_template,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'URLError: {reason}',
        }
    except OSError as e:
        return {
            'name': proxy_name,
            'url': proxy_base_url,
            'clone_template': proxy_clone_template,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'OSError: {e.strerror or str(e)[:60]}',
        }
    except Exception as e:
        return {
            'name': proxy_name,
            'url': proxy_base_url,
            'clone_template': proxy_clone_template,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'{type(e).__name__}: {str(e)[:80]}',
        }


def _create_ssl_context():
    """创建宽松的 SSL 上下文，兼容一些代理证书问题。"""
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get_urlerror_reason(e):
    """提取 URLError 的具体原因描述。"""
    if hasattr(e, 'reason'):
        r = e.reason
        if isinstance(r, (TimeoutError, ConnectionRefusedError, ConnectionResetError,
                          ConnectionAbortedError, ConnectionError)):
            return type(r).__name__
        if isinstance(r, str):
            return r[:60]
        return str(r)[:60]
    if hasattr(e, 'code'):
        return f'HTTP {e.code}'
    return str(e)[:60]


# ---------------------------------------------------------------------------
# ZIP 下载（替代 git clone）
# ---------------------------------------------------------------------------

def _download_zip(url, dest_path, progress_callback=None, timeout=60):
    """通过 HTTP 下载 ZIP 压缩包到本地路径。

    使用 urllib（Python 内置），无需外部依赖。
    支持 Content-Length 进度回调。

    参数:
        url: 下载 URL
        dest_path: 本地保存路径
        progress_callback: 进度回调函数，接收 0-100 的浮点数
        timeout: 超时秒数（默认 60s）

    返回:
        True 表示下载成功，False 表示失败
    """
    ctx = _create_ssl_context()
    try:
        req = Request(url, method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; bhxz-updater)')
        req.add_header('Accept', 'application/zip,*/*')

        resp = urlopen(req, context=ctx, timeout=timeout)
        total = resp.headers.get('Content-Length')
        total = int(total) if total else 0

        downloaded = 0
        chunk_size = 128 * 1024  # 128KB

        with open(dest_path, 'wb') as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and progress_callback:
                    # 每 5% 回调一次，避免过于频繁
                    pct = downloaded / total * 100
                    if int(pct) % 5 == 0 or pct >= 99:
                        progress_callback(min(pct, 100))

        # 验证文件是否有效 ZIP
        if os.path.getsize(dest_path) == 0:
            return False
        try:
            with zipfile.ZipFile(dest_path, 'r') as zf:
                if zf.testzip() is not None:
                    return False  # 损坏的 ZIP
        except zipfile.BadZipFile:
            return False

        return True
    except HTTPError as e:
        # HTTP 错误（4xx/5xx）— 代理可达但资源不可达
        return False
    except (URLError, OSError, Exception):
        return False


def _extract_zip(zip_path, dest_dir):
    """解压 GitHub ZIP 压缩包，自动处理顶层目录嵌套。

    GitHub 的 ZIP 归档包含一个顶层目录（如 kute0213-bhxz-main），
    此函数跳过顶层目录，直接将仓库内容提取到 dest_dir。

    参数:
        zip_path: ZIP 文件路径
        dest_dir: 目标目录（必须已存在）
    """
    # 先找出顶层目录
    top_level = None
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                parts = name.replace('\\', '/').split('/')
                if parts[0]:
                    top_level = parts[0]
                    break

            if top_level:
                # 跳过顶层目录，提取所有文件
                for name in zf.namelist():
                    if name.endswith('/'):
                        continue  # 跳过目录条目
                    # 规范化路径分隔符
                    norm_name = name.replace('\\', '/')
                    # 跳过顶层目录
                    if norm_name.startswith(top_level + '/'):
                        rel_name = norm_name[len(top_level) + 1:]
                    else:
                        rel_name = norm_name
                    if not rel_name:
                        continue
                    target = os.path.join(dest_dir, rel_name)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(name) as src, open(target, 'wb') as dst:
                        dst.write(src.read())
            else:
                # 没有顶层目录，直接全部解压
                zf.extractall(dest_dir)
    except Exception:
        raise


def _make_zip_path():
    """生成唯一的临时 ZIP 文件路径。"""
    return os.path.join(tempfile.gettempdir(), f'bhxz_update_{random.randint(100000, 999999)}.zip')


def detect_fastest_proxy(proxy_list=None, timeout=3):
    """检测所有可用的 GitHub 代理，返回排序后的可用列表 [(名称, 代理首页URL, 下载模板URL, 延迟), ...]。

    分批检测 + 早停策略：
    - 每批最多 8 个代理并行测试
    - 找到 3 个可用代理后立即停止
    - 单代理超时 2.5s，整体控制在 3s 内
    - 低并发，避免给服务器网络带来太大压力

    参数:
        proxy_list: 待检测的代理列表，默认使用 DEFAULT_PROXY_LIST
                    格式: [(名称, 代理首页URL, 下载模板URL), ...]
        timeout: 整体超时秒数（默认 3s）

    返回:
        [(名称, 代理首页URL, 下载模板URL, 延迟秒数), ...] 按延迟升序排列
    """
    if proxy_list is None:
        proxy_list = DEFAULT_PROXY_LIST

    all_results = []
    lock = threading.Lock()
    stop_flag = threading.Event()  # 提前停止信号

    BATCH_SIZE = 8
    EARLY_STOP_COUNT = 3
    PROXY_TIMEOUT = min(timeout, 2.5)

    # 分批检测
    for batch_start in range(0, len(proxy_list), BATCH_SIZE):
        if stop_flag.is_set():
            break

        batch = proxy_list[batch_start:batch_start + BATCH_SIZE]

        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            future_map = {
                executor.submit(_test_proxy_timeout, name, base_url, ct, PROXY_TIMEOUT): (name, base_url)
                for name, base_url, ct in batch
            }

            deadline = time.time() + PROXY_TIMEOUT
            try:
                for future in as_completed(future_map, timeout=PROXY_TIMEOUT):
                    if stop_flag.is_set():
                        for f in future_map:
                            f.cancel()
                        break
                    try:
                        result = future.result(timeout=max(0.05, deadline - time.time()))
                        with lock:
                            all_results.append(result)
                        # 检查是否达到早停条件
                        success_count = sum(1 for r in all_results if r['status'] == 'success')
                        if success_count >= EARLY_STOP_COUNT:
                            stop_flag.set()
                            for f in future_map:
                                f.cancel()
                            break
                    except Exception:
                        pass
            except TimeoutError:
                for f in future_map:
                    f.cancel()

    # 按状态和延迟排序（成功的在前，按延迟升序；失败的在后，按名称排序）
    success_results = [r for r in all_results if r['status'] == 'success']
    fail_results = [r for r in all_results if r['status'] == 'fail']

    success_results.sort(key=lambda x: x['elapsed'])
    fail_results.sort(key=lambda x: x['name'])

    # 记录详细结果（供后续日志查看）
    with _proxy_test_lock:
        _proxy_test_results.clear()
        for r in success_results:
            _proxy_test_results.append({
                'name': r['name'],
                'url': r['url'],
                'test_url': r['test_url'],
                'elapsed': f'{r["elapsed"]:.1f}s',
                'status': 'success',
                'error': r['error'],
            })
        for r in fail_results:
            _proxy_test_results.append({
                'name': r['name'],
                'url': r['url'],
                'test_url': r['test_url'],
                'elapsed': f'{r["elapsed"]:.1f}s',
                'status': 'fail',
                'error': r['error'],
            })

    # 返回可用代理列表
    available = [(r['name'], r['url'], r['clone_template'], r['elapsed']) for r in success_results]

    return available


# ---------------------------------------------------------------------------
# 安全路径检查
# ---------------------------------------------------------------------------

def _is_protected(rel_path, protected_paths=None):
    """检查路径是否受保护（不应删除/覆盖）。"""
    if protected_paths is None:
        protected_paths = DEFAULT_PROTECTED_PATHS

    # 规范化路径
    rel_path = rel_path.replace('\\', '/').strip('/')

    # 检查是否匹配受保护路径
    for protected in protected_paths:
        p = protected.replace('\\', '/').strip('/')
        if rel_path == p or rel_path.startswith(p + '/'):
            return True

    # 检查是否是 .gitignore 等配置文件
    if rel_path.startswith('.'):
        return True

    return False


# ---------------------------------------------------------------------------
# 核心更新逻辑
# ---------------------------------------------------------------------------

def _run_update():
    """执行更新（在后台线程中运行）。"""
    try:
        _add_event('progress', {'percent': 1, 'message': '正在加载更新配置...'})

        # 0. 从设置读取不替换文件列表、自定义代理和启动命令
        protected_paths = list(DEFAULT_PROTECTED_PATHS)
        proxy_list = list(DEFAULT_PROXY_LIST)
        start_command = ''

        try:
            from config import get_config_value

            # 读取不替换文件列表
            excluded_raw = get_config_value('UPDATE_EXCLUDED_FILES', '')
            if excluded_raw:
                custom_excluded = [p.strip() for p in excluded_raw.split(',') if p.strip()]
                for p in custom_excluded:
                    if p not in protected_paths:
                        protected_paths.append(p)

            # 读取自定义代理
            # 配置格式：name=base_url（每行一个）
            # 例如：myproxy=https://myproxy.example.com/
            proxies_raw = get_config_value('GITHUB_PROXIES', '')
            if proxies_raw:
                for line in proxies_raw.strip().split('\n'):
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    name, url = line.split('=', 1)
                    name, url = name.strip(), url.strip()
                    if name and url:
                        base = url.rstrip('/')
                        # 自动构造下载模板
                        download_template = base + '/{repo}'
                        replaced = False
                        for i, (n, *_rest) in enumerate(proxy_list):
                            if n == name:
                                # 保留原有的 download_template，只更新 base_url
                                proxy_list[i] = (name, base + '/', download_template)
                                replaced = True
                                break
                        if not replaced:
                            proxy_list.append((name, base + '/', download_template))

            # 读取自定义启动命令
            start_command = get_config_value('START_COMMAND', '')
        except Exception:
            pass

        _add_event('progress', {'percent': 2, 'message': f'已加载配置，{len(protected_paths)} 个受保护路径'})
        if start_command:
            _add_event('log', {'message': f'✓ 自定义启动命令: {start_command}'})

        # 1. 检测可用代理（分批检测，每批 8 个，超时 2.5s）
        _add_event('progress', {'percent': 3, 'message': f'正在检测 {len(proxy_list)} 个 GitHub 代理...'})
        _add_event('log', {'message': f'╔══ 开始代理检测（共 {len(proxy_list)} 个，分批 8 个，超时 2.5s，早停 3 个）'})
        # 压缩日志：不逐条输出所有代理 URL，防止日志刷屏
        _add_event('log', {'message': f'║  首批检测前 8 个: {", ".join(n for n, *_ in proxy_list[:8])}'})
        if len(proxy_list) > 8:
            _add_event('log', {'message': f'║  剩余 {len(proxy_list) - 8} 个代理作为备用批次'})

        available_proxies = detect_fastest_proxy(proxy_list=proxy_list, timeout=3)

        # 记录详细结果
        success_count = 0
        fail_count = 0
        success_details = []
        fail_details = []
        with _proxy_test_lock:
            for r in _proxy_test_results:
                if r['status'] == 'success':
                    success_count += 1
                    success_details.append(f'{r["name"]}({r["elapsed"]})')
                else:
                    fail_count += 1
                    fail_details.append(f'{r["name"]}({r["error"][:30]})')

        # 只显示成功代理和失败数量
        if success_details:
            _add_event('log', {'message': f'║  ✓ 可用代理 ({success_count}): {", ".join(success_details[:6])}'})
            if len(success_details) > 6:
                _add_event('log', {'message': f'║    ... 还有 {len(success_details) - 6} 个可用'})
        if fail_details:
            _add_event('log', {'message': f'║  ✗ 不可用: {fail_count} 个（{fail_details[0]}）'})
        _add_event('log', {'message': f'╚══ 代理检测完成：可用 {success_count} 个，不可用 {fail_count} 个'})

        if not available_proxies:
            # 所有代理都不可达，给用户明确的错误信息
            err_details = []
            with _proxy_test_lock:
                for r in _proxy_test_results:
                    err_details.append(f'{r["name"]}: {r["error"]}')
            err_msg = '所有 GitHub 代理均不可达，请检查网络连接或稍后重试'
            if err_details:
                err_msg += '\n' + '\n'.join(err_details[:5])
            raise RuntimeError(err_msg)

        # 速度排名
        rank_parts = [f'{i+1}. {n} ({e:.1f}s)' for i, (n, *_, e) in enumerate(available_proxies[:5])]
        _add_event('log', {'message': f'→ 代理速度排名: {"; ".join(rank_parts)}'})
        if len(available_proxies) > 5:
            _add_event('log', {'message': f'→ 以及另外 {len(available_proxies) - 5} 个可用代理'})

        # 2. 按速度顺序尝试下载 ZIP 压缩包（替代 git clone）
        #    纯 HTTP 下载，兼容性更好，无需安装 git
        download_success = False
        last_error = ''
        temp_dir = None
        zip_path = None
        total_attempts = len(available_proxies)

        for attempt_idx, (name, base_url, download_template, elapsed) in enumerate(available_proxies):
            # 构建 ZIP 下载 URL
            zip_url = download_template.replace('{repo}', REPO_ARCHIVE_PATH)

            _add_event('log', {'message': f'{"─" * 40}'})
            hint = '首选' if attempt_idx == 0 else '备用'
            _add_event('log', {'message': f'下载尝试 #{attempt_idx + 1}: {name} （{hint}，延迟 {elapsed:.1f}s）'})
            _add_event('progress', {'percent': 5, 'message': f'正在从 {name} 下载更新包...'})
            _add_event('log', {'message': f'  下载 URL: {zip_url}'})

            zip_path = _make_zip_path()
            download_start = time.time()

            def _dl_progress(pct):
                mapped = 5 + int(pct * 65 / 100)
                _add_event('progress', {'percent': mapped, 'message': f'正在下载更新包... {int(pct)}%'})

            try:
                success = _download_zip(zip_url, zip_path, progress_callback=_dl_progress, timeout=30)
                if success:
                    download_elapsed = time.time() - download_start
                    _add_event('log', {'message': f'✓ {name} 下载成功（耗时 {download_elapsed:.1f}s）'})
                    _add_event('progress', {'percent': 70, 'message': '下载完成，正在解压...'})

                    # 解压到临时目录
                    temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
                    _add_event('log', {'message': '正在解压更新包...'})
                    _extract_zip(zip_path, temp_dir)

                    download_success = True
                    break
                else:
                    download_elapsed = time.time() - download_start
                    last_error = f'{name} 下载失败'
                    _add_event('log', {'message': f'✗ {name} 下载失败（耗时 {download_elapsed:.1f}s）'})
            except Exception as e:
                last_error = str(e)[:200]
                _add_event('log', {'message': f'✗ {name} 下载异常: {last_error}'})
            finally:
                # 清理临时 ZIP 文件
                if zip_path and os.path.isfile(zip_path):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
                    zip_path = None

        # 如果所有代理都失败，尝试直连 GitHub 下载
        if not download_success:
            _add_event('log', {'message': f'{"─" * 40}'})
            _add_event('log', {'message': '尝试直接下载 GitHub 原始归档（无代理）...'})
            direct_url = f'https://github.com/{REPO_ARCHIVE_PATH}'
            _add_event('log', {'message': f"  下载 URL: {direct_url}"})

            zip_path = _make_zip_path()
            try:
                success = _download_zip(direct_url, zip_path, timeout=15)
                if success:
                    _add_event('log', {'message': '✓ 直接下载成功'})
                    temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
                    _extract_zip(zip_path, temp_dir)
                    download_success = True
                else:
                    last_error = '直接下载失败'
            except Exception as e:
                last_error = str(e)[:200]
            finally:
                if zip_path and os.path.isfile(zip_path):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass

        if not download_success:
            raise RuntimeError(
                f'已尝试 {total_attempts} 个代理及直连，全部失败。\n'
                f'最后错误: {last_error[:300]}'
            )

        _add_event('progress', {'percent': 72, 'message': '下载完成，正在同步文件...'})

        # 4. 列出仓库根目录下的所有项目（排除 .git）
        repo_items = sorted([
            item for item in os.listdir(temp_dir)
            if item != '.git'
        ])

        if not repo_items:
            raise RuntimeError('仓库为空，没有可同步的文件')

        # 统计总文件数（用于进度条）
        total_files = 0
        for item in repo_items:
            src = os.path.join(temp_dir, item)
            if os.path.isdir(src):
                for dirpath, dirnames, filenames in os.walk(src):
                    total_files += len(filenames)
            else:
                total_files += 1

        _add_event('progress', {'percent': 75, 'message': f'将同步 {len(repo_items)} 个项目，{total_files} 个文件...'})
        _add_event('log', {'message': f'开始同步 {len(repo_items)} 个项目，{total_files} 个文件'})

        # 5. 全量同步：遍历仓库每个顶级项目
        #    - 不在保护列表 → 删除本地版本 → 复制新版本
        #    - 在保护列表 → 跳过
        #    这样仓库里删除的文件，本地也会被删掉
        processed = 0
        remaining_pct = 95 - 75  # 20%

        for item in repo_items:
            # 检查是否受保护
            if _is_protected(item, protected_paths):
                _add_event('log', {'message': f'  ⏭ 跳过受保护路径: {item}'})
                _add_event('progress', {
                    'percent': 75 + int(processed * remaining_pct / total_files),
                    'message': f'跳过受保护路径: {item}',
                })
                processed += 1
                continue

            src = os.path.join(temp_dir, item)
            dst = os.path.join(APP_ROOT, item)

            _add_event('log', {'message': f'  → 同步: {item}'})

            # 删除本地版本（如果存在）
            if os.path.isdir(dst):
                _add_event('log', {'message': f'    删除旧目录: {item}/'})
                _add_event('progress', {
                    'percent': 75 + int(processed * remaining_pct / total_files),
                    'message': f'正在删除 {item}/...',
                })

                def _onerror(func, path, exc_info):
                    for attempt in range(3):
                        try:
                            time.sleep(0.5)
                            func(path)
                            return
                        except Exception:
                            pass

                shutil.rmtree(dst, onerror=_onerror)
            elif os.path.isfile(dst):
                _add_event('log', {'message': f'    删除旧文件: {item}'})
                try:
                    os.remove(dst)
                except Exception:
                    pass

            # 复制新版本
            if os.path.isdir(src):
                # 确保父目录存在
                os.makedirs(os.path.dirname(dst) if os.path.dirname(dst) else APP_ROOT, exist_ok=True)
                # 递归复制整个目录
                for dirpath, dirnames, filenames in os.walk(src):
                    rel_dir = os.path.relpath(dirpath, src)
                    target_dir = os.path.join(dst, rel_dir) if rel_dir != '.' else dst
                    os.makedirs(target_dir, exist_ok=True)
                    for fn in filenames:
                        src_file = os.path.join(dirpath, fn)
                        dst_file = os.path.join(target_dir, fn)
                        try:
                            shutil.copy2(src_file, dst_file)
                        except Exception:
                            pass
                        processed += 1
                        if processed % max(1, total_files // 20) == 0:
                            pct = 75 + int(processed * remaining_pct / total_files)
                            _add_event('progress', {
                                'percent': min(pct, 94),
                                'message': f'正在同步 {item}/...',
                            })
            else:
                # 单个文件直接复制
                os.makedirs(APP_ROOT, exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass
                processed += 1

        # 清理临时目录
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

        _add_event('log', {'message': f'✓ 同步完成，共处理 {processed} 个文件'})
        _add_event('progress', {'percent': 97, 'message': '同步完成，正在构建静态资源...'})

        # 6. 运行静态资源构建脚本（下载外部 CDN 资源到本地，生成静态 CSS/JS 文件）
        try:
            build_script = os.path.join(APP_ROOT, 'scripts', 'build', 'build_static.py')
            if os.path.isfile(build_script):
                _add_event('log', {'message': '正在构建静态资源...'})
                build_result = subprocess.run(
                    [sys.executable, build_script],
                    capture_output=True, text=True, timeout=180,
                )
                if build_result.returncode == 0:
                    _add_event('log', {'message': '✓ 静态资源构建完成'})
                else:
                    _add_event('log', {'message': f'⚠ 静态资源构建警告: {build_result.stderr[:200]}'})
            else:
                _add_event('log', {'message': '⚠ 未找到构建脚本: scripts/build/build_static.py'})
        except subprocess.TimeoutExpired:
            _add_event('log', {'message': '⚠ 静态资源构建超时（180s），跳过'})
        except Exception as e:
            _add_event('log', {'message': f'⚠ 静态资源构建失败: {e}'})

        _add_event('progress', {'percent': 99, 'message': '构建完成，正在准备重启...'})

        # 6. 完成
        _add_event('done', {
            'success': True,
            'message': '更新成功，即将重启服务器...',
        })
        time.sleep(1)
        _restart_app(start_command)

    except Exception as e:
        error_msg = str(e)
        _add_event('log', {'message': f'✗ 更新失败: {error_msg}'})
        _add_event('error', {'message': f'更新失败: {error_msg}'})
        _add_event('done', {'success': False, 'message': f'更新失败: {error_msg}'})


def _restart_app(start_command=''):
    """重启当前应用进程（跨平台，优雅替换）。

    使用自定义启动命令启动新服务器，然后自动关闭当前进程。
    默认使用 `{python} app.py`（在 config.py 中配置 START_COMMAND）。

    自定义启动命令支持占位符：
    - {python}    → Python 可执行文件路径
    - {script}    → app.py 绝对路径
    - {app_root}  → 项目根目录
    """
    _add_event('progress', {'percent': 100, 'message': '正在重启服务器...'})

    # 给前端一点时间接收事件
    time.sleep(0.5)

    cmd = start_command or '{python} app.py'
    # 格式化占位符
    formatted = cmd.replace('{python}', sys.executable)\
                   .replace('{script}', os.path.join(APP_ROOT, 'app.py'))\
                   .replace('{app_root}', APP_ROOT)
    _add_event('log', {'message': f'执行启动命令: {formatted}'})
    try:
        subprocess.Popen(formatted, cwd=APP_ROOT, shell=True, close_fds=True)
    except Exception as e:
        _add_event('log', {'message': f'启动命令执行失败: {e}'})
        # 关闭当前进程，避免卡死
        _shutdown_current_process()
        return
    # 使用自动方式关闭当前进程
    _shutdown_current_process()


def _shutdown_current_process():
    """自动关闭当前进程（跨平台）。

    - Windows: 发送 SIGTERM 信号触发优雅关闭，兜底 sys.exit
    - Unix: 直接 sys.exit
    """
    if sys.platform == 'win32':
        import signal
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass
    sys.exit(0)


def _restart_win32():
    """Windows 可靠重启：Popen 启动新进程 + 优雅退出。

    避免 CMD 窗口闪烁。使用 CREATE_NO_WINDOW 标志让新进程无窗口启动，
    然后通过信号触发当前进程的优雅关闭。
    """
    python_exe = sys.executable
    script = os.path.join(APP_ROOT, 'app.py')

    # 1. 启动新进程（无窗口，独立进程组，避免被连带终止）
    try:
        proc = subprocess.Popen(
            [python_exe, script],
            cwd=APP_ROOT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception:
        # fallback：不带标志启动
        try:
            proc = subprocess.Popen([python_exe, script], cwd=APP_ROOT)
        except Exception:
            proc = None

    if proc and proc.pid:
        _add_event('progress', {'percent': 100, 'message': f'已启动新进程 (PID: {proc.pid})'})

    # 2. 自动关闭当前进程
    _shutdown_current_process()


def start_update():
    """启动一键更新（后台线程）。"""
    if _update_state['running']:
        return False

    # 重置状态
    with _update_state['lock']:
        _update_state['running'] = True
        _update_state['progress'] = 0
        _update_state['message'] = '准备中...'
        _update_state['done'] = False
        _update_state['success'] = False
        _update_state['error'] = None
        _update_state['events'].clear()

    thread = threading.Thread(target=_run_update, daemon=True, name='app-updater')
    thread.start()
    return True