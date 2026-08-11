"""
一键更新服务：从 GitHub 获取最新代码，全量同步到本地，自动重启。

安全策略：
- 克隆 GitHub 仓库，遍历仓库根目录所有项目
- 每个项目：如果不在不替换列表 → 删除本地版本 → 复制新版本
- 不替换的文件列表可在管理后台一键更新页面设置
- 更新后自动重启进程
- 跨平台兼容（Windows/Linux/macOS）
- 自动检测最快代理（带详细日志）
"""

import os
import sys
import re
import shutil
import tempfile
import threading
import time
import json
import subprocess
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
# 格式：(名称, 代理前缀URL, 克隆URL模板)
# 代理前缀URL: 代理服务的首页，用于检测代理是否可达（不包含 /https://github.com 后缀）
# 克隆URL模板: 实际用于 git clone 的完整 URL，{repo} 会被替换为仓库路径
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


def detect_fastest_proxy(proxy_list=None, timeout=3):
    """检测所有可用的 GitHub 代理，返回排序后的可用列表 [(名称, 代理首页URL, 克隆模板URL, 延迟), ...]。

    分批检测 + 早停策略：
    - 每批最多 8 个代理并行测试
    - 找到 3 个可用代理后立即停止
    - 单代理超时 2.5s，整体控制在 3s 内
    - 低并发，避免给服务器网络带来太大压力

    参数:
        proxy_list: 待检测的代理列表，默认使用 DEFAULT_PROXY_LIST
                    格式: [(名称, 代理首页URL, 克隆模板URL), ...]
        timeout: 整体超时秒数（默认 3s）

    返回:
        [(名称, 代理首页URL, 克隆模板URL, 延迟秒数), ...] 按延迟升序排列
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
# Git 查找（跨平台）
# ---------------------------------------------------------------------------

def _find_git():
    """查找系统上的 Git 可执行文件路径。

    优先使用 PATH 中的 git，Windows 上额外检查常见安装路径。
    返回完整路径字符串，未找到则返回 None。
    """
    # 1. 优先检查 PATH
    git = shutil.which('git')
    if git:
        return os.path.abspath(git)

    # 2. Windows 上检查常见安装路径
    if sys.platform == 'win32':
        common_paths = [
            r'C:\Program Files\Git\bin\git.exe',
            r'C:\Program Files (x86)\Git\bin\git.exe',
            r'C:\Program Files\Git\cmd\git.exe',
            r'C:\Program Files (x86)\Git\cmd\git.exe',
            os.path.expanduser(r'~\AppData\Local\Programs\Git\bin\git.exe'),
            os.path.expanduser(r'~\AppData\Local\Programs\Git\cmd\git.exe'),
            os.path.expanduser(r'~\scoop\apps\git\current\bin\git.exe'),
            os.path.expanduser(r'~\scoop\apps\git\current\cmd\git.exe'),
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return p

        # 3. 尝试从注册表读取 Git 安装路径
        try:
            import winreg
            for key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                for subkey in [
                    r'SOFTWARE\GitForWindows',
                    r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Git_is1',
                ]:
                    try:
                        with winreg.OpenKey(key, subkey) as reg_key:
                            install_path, _ = winreg.QueryValueEx(reg_key, 'InstallPath')
                            if install_path:
                                exe = os.path.join(install_path, 'bin', 'git.exe')
                                if os.path.isfile(exe):
                                    return exe
                                exe = os.path.join(install_path, 'cmd', 'git.exe')
                                if os.path.isfile(exe):
                                    return exe
                    except (OSError, ValueError):
                        continue
        except ImportError:
            pass

    return None


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
                        # 自动构造克隆模板
                        clone_template = base + '/{repo}'
                        replaced = False
                        for i, (n, *_rest) in enumerate(proxy_list):
                            if n == name:
                                # 保留原有的 clone_template，只更新 base_url
                                proxy_list[i] = (name, base + '/', clone_template)
                                replaced = True
                                break
                        if not replaced:
                            proxy_list.append((name, base + '/', clone_template))

            # 读取自定义启动命令
            start_command = get_config_value('START_COMMAND', '')
        except Exception:
            pass

        _add_event('progress', {'percent': 2, 'message': f'已加载配置，{len(protected_paths)} 个受保护路径'})
        if start_command:
            _add_event('log', {'message': f'✓ 自定义启动命令: {start_command}'})

        # 1. 检测 git
        git_path = _find_git()
        if not git_path:
            raise RuntimeError(
                '未找到 Git，请先安装 Git（https://git-scm.com/downloads）'
                '并确保 Git 已添加到系统 PATH 环境变量中'
            )

        _add_event('log', {'message': f'✓ Git 路径: {git_path}'})

        # 2. 检测可用代理（分批检测，每批 8 个，超时 2.5s）
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

        # 3. 按速度顺序尝试克隆
        clone_success = False
        last_error = ''
        temp_dir = None
        total_attempts = len(available_proxies)

        # 复用克隆函数（内部定义，捕获 stderr 到 stderr_lines）
        CLONE_RANGE = 70
        stderr_lines = []
        stderr_lock = threading.Lock()

        def _parse_line(buf):
            nonlocal last_clone_pct
            text = buf.decode('utf-8', errors='replace')
            m = re.search(r'(\d+)\s*%', text)
            if m:
                pct = int(m.group(1))
                if pct != last_clone_pct:
                    last_clone_pct = pct
                    mapped = 5 + int(pct * CLONE_RANGE / 100)
                    _add_event('progress', {'percent': mapped, 'message': f'正在克隆仓库... {pct}%'})

        def _read_stderr(stream):
            nonlocal last_clone_pct, line_buf
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                for byte in chunk:
                    if byte == 0x0d:
                        text = line_buf.decode('utf-8', errors='replace').strip()
                        if text:
                            with stderr_lock:
                                stderr_lines.append(text)
                        _parse_line(line_buf)
                        line_buf = b''
                    elif byte == 0x0a:
                        text = line_buf.decode('utf-8', errors='replace').strip()
                        if text:
                            with stderr_lock:
                                stderr_lines.append(text)
                        line_buf = b''
                    else:
                        line_buf += bytes([byte])
            if line_buf:
                text = line_buf.decode('utf-8', errors='replace').strip()
                if text:
                    with stderr_lock:
                        stderr_lines.append(text)

        for attempt_idx, (name, base_url, clone_template, elapsed) in enumerate(available_proxies):
            # 使用 clone_template 替换 {repo} 占位符
            cur_clone_url = clone_template.replace('{repo}', 'kute0213/bhxz.git')

            _add_event('log', {'message': f'{"─" * 40}'})
            hint = '首选' if attempt_idx == 0 else '备用'
            _add_event('log', {'message': f'克隆尝试 #{attempt_idx + 1}: {name} （{hint}，延迟 {elapsed:.1f}s）'})
            _add_event('progress', {'percent': 5, 'message': f'正在从 {name} 克隆仓库...'})
            _add_event('log', {'message': f'  克隆 URL: {cur_clone_url}'})

            temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
            git_cmd = [git_path, 'clone', '--depth', '1', '--single-branch', '--progress',
                       cur_clone_url, temp_dir]
            env = os.environ.copy()
            env['GIT_TERMINAL_PROMPT'] = '0'
            env['GIT_ASKPASS'] = 'echo'

            if sys.platform == 'win32':
                _git_dir = os.path.dirname(os.path.dirname(git_path))
                for p in [os.path.join(_git_dir, 'bin'), os.path.join(_git_dir, 'cmd')]:
                    if os.path.isdir(p) and p not in env.get('PATH', ''):
                        env['PATH'] = os.pathsep.join([p, env.get('PATH', '')])

            _add_event('log', {'message': f'  执行: {" ".join(git_cmd[:3])} ...'})
            clone_start = time.time()
            proc = subprocess.Popen(git_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    bufsize=0, env=env)

            # 重置进度变量
            last_clone_pct = -1
            line_buf = b''
            stderr_lines.clear()

            stderr_thread = threading.Thread(target=_read_stderr, args=(proc.stderr,), daemon=True)
            stderr_thread.start()
            proc.wait()
            stderr_thread.join(timeout=5)
            clone_elapsed = time.time() - clone_start

            if proc.returncode == 0:
                clone_success = True
                _add_event('log', {'message': f'✓ {name} 克隆成功（耗时 {clone_elapsed:.1f}s）'})
                break
            else:
                with stderr_lock:
                    last_error = '\n'.join(stderr_lines[-10:]) if stderr_lines else f'{name} 克隆失败'
                _add_event('log', {'message': f'✗ {name} 克隆失败（耗时 {clone_elapsed:.1f}s）'})
                _add_event('log', {'message': f'  错误: {last_error[:200]}'})
                if temp_dir:
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass
                    temp_dir = None
                continue

        _add_event('log', {'message': f'{"─" * 40}'})

        if not clone_success:
            raise RuntimeError(
                f'已尝试 {total_attempts} 个代理，全部失败。\n'
                f'最后错误: {last_error[:300]}'
            )

        _add_event('progress', {'percent': 72, 'message': '克隆完成，正在同步文件...'})

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