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
from urllib.request import Request, urlopen
from urllib.error import URLError

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

# 默认 GitHub 代理列表（按类型分组，检测时自动选择最快的可用代理）
# 移除了重复的 ghproxy.net 条目
DEFAULT_PROXY_LIST = [
    # ===== 直连 =====
    ('直连', 'https://github.com'),

    # ===== 通用型代理（URL 前缀方式，在最前面加 https://X/） =====
    ('ghproxy.com', 'https://ghproxy.com/https://github.com'),
    ('mirror.ghproxy.com', 'https://mirror.ghproxy.com/https://github.com'),
    ('ghproxy.homeboyc.cn', 'https://ghproxy.homeboyc.cn/https://github.com'),
    ('gh.llkk.cc', 'https://gh.llkk.cc/https://github.com'),
    ('hub.gitmirror.com', 'https://hub.gitmirror.com/https://github.com'),
    ('gh.h233.eu.org', 'https://gh.h233.eu.org/https://github.com'),
    ('gh.api.99988866.xyz', 'https://gh.api.99988866.xyz/https://github.com'),
    ('moeyy.cn/gh-proxy', 'https://moeyy.cn/gh-proxy/https://github.com'),
    ('gh-proxy.yizhuan.org', 'https://gh-proxy.yizhuan.org/https://github.com'),
    ('ghproxy.856539.xyz', 'https://ghproxy.856539.xyz/https://github.com'),
    ('ghproxy.alphavps.workers.dev', 'https://ghproxy.alphavps.workers.dev/https://github.com'),
    ('gitproxy.plus1.win', 'https://gitproxy.plus1.win/https://github.com'),
    ('gh-proxy.lxstv.pw', 'https://gh-proxy.lxstv.pw/https://github.com'),
    ('ghproxy.guidao.workers.dev', 'https://ghproxy.guidao.workers.dev/https://github.com'),

    # ===== 镜像站 =====
    ('bgithub.xyz', 'https://bgithub.xyz/https://github.com'),
    ('kkgithub.com', 'https://kkgithub.com/https://github.com'),
    ('hub.fastgit.org', 'https://hub.fastgit.org/https://github.com'),
    ('gitclone.com', 'https://gitclone.com/github.com'),
    ('github.ur1.fun', 'https://github.ur1.fun/https://github.com'),
    ('githubfast.com', 'https://githubfast.com/https://github.com'),
    ('github.moeyy.xyz', 'https://github.moeyy.xyz/https://github.com'),

    # ===== 文件加速型 =====
    ('github.akams.cn', 'https://github.akams.cn/https://github.com'),
    ('ghp.ci', 'https://ghp.ci/https://github.com'),
    ('gh.dcm.so', 'https://gh.dcm.so/https://github.com'),
    ('gh-proxy.lhr.ltd', 'https://gh-proxy.lhr.ltd/https://github.com'),
    ('gitproxy.188706.xyz', 'https://gitproxy.188706.xyz/https://github.com'),
    ('ghproxy.yaoyaoling.net', 'https://ghproxy.yaoyaoling.net/https://github.com'),
    ('github.ddlink.cc', 'https://github.ddlink.cc/https://github.com'),
    ('gh.idayer.com', 'https://gh.idayer.com/https://github.com'),
    ('slink.ltd', 'https://slink.ltd/https://github.com'),
    ('gh-proxy.netlify.app', 'https://gh-proxy.netlify.app/https://github.com'),
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


def _build_test_url(proxy_name, proxy_url):
    """根据代理类型构建测试 URL。"""
    base = proxy_url.rstrip('/')
    if proxy_name == '直连' or 'github.com' in base:
        # 直连或本身就是 github.com 的变体
        return base + '/'
    else:
        # 前缀式代理：测试 https://代理/https://github.com/
        return base + '/https://github.com/'


def _test_proxy_timeout(proxy_name, proxy_url, timeout=4):
    """测试代理的响应时间，返回详细结果字典。

    返回:
        {
            'name': 代理名称,
            'url': 代理URL,
            'test_url': 实际测试URL,
            'elapsed': 响应秒数（失败则为 timeout 值）,
            'status': 'success' 或 'fail',
            'error': 错误描述（成功时为空字符串）,
        }
    """
    test_url = _build_test_url(proxy_name, proxy_url)

    try:
        req = Request(test_url, method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0')
        start = time.time()
        resp = urlopen(req, timeout=timeout)
        elapsed = time.time() - start
        return {
            'name': proxy_name,
            'url': proxy_url,
            'test_url': test_url,
            'elapsed': round(elapsed, 2),
            'status': 'success',
            'error': '',
        }
    except URLError as e:
        reason = _get_urlerror_reason(e)
        return {
            'name': proxy_name,
            'url': proxy_url,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'URLError: {reason}',
        }
    except OSError as e:
        return {
            'name': proxy_name,
            'url': proxy_url,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'OSError: {e.strerror or str(e)[:60]}',
        }
    except ValueError as e:
        return {
            'name': proxy_name,
            'url': proxy_url,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'ValueError: {str(e)[:60]}',
        }
    except Exception as e:
        return {
            'name': proxy_name,
            'url': proxy_url,
            'test_url': test_url,
            'elapsed': timeout,
            'status': 'fail',
            'error': f'{type(e).__name__}: {str(e)[:80]}',
        }


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


def detect_fastest_proxy(proxy_list=None, timeout=4):
    """检测所有可用的 GitHub 代理，返回排序后的可用列表 [(名称, URL, 延迟), ...]。

    特点：
    - 并行检测所有代理
    - 记录每个代理的详细测试结果（包括测试URL、错误原因）
    - 至少返回一个结果（直连兜底）

    参数:
        proxy_list: 待检测的代理列表，默认使用 DEFAULT_PROXY_LIST
        timeout: 每个代理的超时秒数（默认 4s，比之前 5s 更激进）

    返回:
        [(名称, URL, 延迟秒数), ...] 按延迟升序排列
    """
    if proxy_list is None:
        proxy_list = DEFAULT_PROXY_LIST

    all_results = []
    threads = []
    lock = threading.Lock()

    def _test(pn, pu):
        r = _test_proxy_timeout(pn, pu, timeout)
        with lock:
            all_results.append(r)

    for name, url in proxy_list:
        t = threading.Thread(target=_test, args=(name, url), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

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
                'error': '',
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
    available = [(r['name'], r['url'], r['elapsed']) for r in success_results]

    # 如果所有代理都失败，至少返回直连
    if not available:
        # 找到直连在原始列表中的位置
        direct_url = proxy_list[0][1]  # 默认第一个是直连
        return [('直连', direct_url, 999)]

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
            proxies_raw = get_config_value('GITHUB_PROXIES', '')
            if proxies_raw:
                for line in proxies_raw.strip().split('\n'):
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    name, url = line.split('=', 1)
                    name, url = name.strip(), url.strip()
                    if name and url:
                        replaced = False
                        for i, (n, u) in enumerate(proxy_list):
                            if n == name:
                                proxy_list[i] = (name, url)
                                replaced = True
                                break
                        if not replaced:
                            proxy_list.append((name, url))

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

        # 2. 检测代理（带详细日志）
        _add_event('progress', {'percent': 3, 'message': f'正在检测 {len(proxy_list)} 个 GitHub 代理...'})
        _add_event('log', {'message': f'╔══ 开始代理检测（共 {len(proxy_list)} 个，超时 {4}s）'})

        # 列出所有待测代理
        for i, (name, url) in enumerate(proxy_list, 1):
            test_url = _build_test_url(name, url)
            _add_event('log', {'message': f'║  [{i:2d}] {name:25s} → {test_url}'})

        available_proxies = detect_fastest_proxy(proxy_list=proxy_list)

        # 记录详细结果
        success_count = 0
        fail_count = 0
        with _proxy_test_lock:
            for r in _proxy_test_results:
                if r['status'] == 'success':
                    success_count += 1
                    _add_event('log', {'message': f'║  ✓ {r["name"]:25s} {r["elapsed"]:>6s}  {r["test_url"]}'})
                else:
                    fail_count += 1
                    _add_event('log', {'message': f'║  ✗ {r["name"]:25s} {r["elapsed"]:>6s}  {r["error"][:60]}'})

        _add_event('log', {'message': f'╚══ 代理检测完成：可用 {success_count} 个，不可用 {fail_count} 个'})

        if not available_proxies:
            _add_event('log', {'message': '⚠ 所有代理均不可达，将使用直连'})
            available_proxies = [('直连', GITHUB_REPO, 999)]

        fastest = available_proxies[0]
        proxy_name, proxy_url = fastest[0], fastest[1]
        _add_event('progress', {
            'percent': 5,
            'message': f'已选择代理: {proxy_name} ({fastest[2]:.1f}s)',
        })
        _add_event('log', {'message': f'→ 选择最快代理: {proxy_name} ({fastest[2]:.1f}s)'})

        # 输出可用代理排名
        if len(available_proxies) > 1:
            rank_parts = [f'{i+1}. {n} ({e:.1f}s)' for i, (n, _, e) in enumerate(available_proxies[:5])]
            _add_event('log', {'message': f'→ 代理速度排名: {"; ".join(rank_parts)}'})
            if len(available_proxies) > 5:
                _add_event('log', {'message': f'→ 以及另外 {len(available_proxies) - 5} 个可用代理'})

        # 3. 构建克隆 URL 并尝试克隆（如果最快的失败，自动尝试下一个）
        clone_success = False
        last_error = ''

        for attempt_idx, (name, url, _) in enumerate(available_proxies):
            if name == '直连':
                cur_clone_url = GITHUB_REPO
            else:
                base = url.rstrip('/')
                if 'github.com' in base:
                    cur_clone_url = base + '/kute0213/bhxz.git'
                else:
                    cur_clone_url = base + '/https://github.com/kute0213/bhxz.git'

            _add_event('log', {'message': f'{"─" * 40}'})
            if attempt_idx == 0:
                _add_event('log', {'message': f'克隆尝试 #{attempt_idx + 1}: {name} （首选）'})
                _add_event('progress', {'percent': 5, 'message': f'正在从 {name} 克隆仓库...'})
            else:
                _add_event('log', {'message': f'克隆尝试 #{attempt_idx + 1}: {name} （备用）'})
                _add_event('progress', {'percent': 5, 'message': f'尝试备用代理 {name}...'})

            _add_event('log', {'message': f'  克隆 URL: {cur_clone_url}'})

            temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')

            # 执行 git clone
            git_cmd = [git_path, 'clone', '--depth', '1', '--single-branch', '--progress', cur_clone_url, temp_dir]
            env = os.environ.copy()
            env['GIT_TERMINAL_PROMPT'] = '0'
            env['GIT_ASKPASS'] = 'echo'

            if sys.platform == 'win32':
                git_dir = os.path.dirname(os.path.dirname(git_path))
                for p in [os.path.join(git_dir, 'bin'), os.path.join(git_dir, 'cmd')]:
                    if os.path.isdir(p) and p not in env.get('PATH', ''):
                        env['PATH'] = os.pathsep.join([p, env.get('PATH', '')])

            _add_event('log', {'message': f'  执行: {" ".join(git_cmd[:3])} ...'})
            clone_start = time.time()
            proc = subprocess.Popen(git_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env)

            # 解析克隆进度
            CLONE_RANGE = 70
            last_clone_pct = -1
            line_buf = b''

            def _read_stderr(stream):
                nonlocal last_clone_pct, line_buf
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    for byte in chunk:
                        if byte == 0x0d:
                            _parse_line(line_buf)
                            line_buf = b''
                        elif byte == 0x0a:
                            line_buf = b''
                        else:
                            line_buf += bytes([byte])

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

            stderr_thread = threading.Thread(target=_read_stderr, args=(proc.stderr,), daemon=True)
            stderr_thread.start()
            proc.wait()
            stderr_thread.join(timeout=5)
            clone_elapsed = time.time() - clone_start

            if proc.returncode == 0:
                clone_success = True
                _add_event('log', {'message': f'✓ {name} 克隆成功（耗时 {clone_elapsed:.1f}s）'})
                break  # 跳出 fallback 循环
            else:
                remaining = proc.stderr.read().decode('utf-8', errors='replace').strip()
                last_error = remaining or '克隆失败（无错误输出）'
                _add_event('log', {'message': f'✗ {name} 克隆失败（耗时 {clone_elapsed:.1f}s）'})
                _add_event('log', {'message': f'  错误: {last_error[:200]}'})
                # 清理本次临时目录
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
                continue  # 尝试下一个代理

        _add_event('log', {'message': f'{"─" * 40}'})

        # 所有代理都失败
        if not clone_success:
            raise RuntimeError(f'所有 {len(available_proxies)} 个可用代理克隆均失败: {last_error}')

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
        _add_event('progress', {'percent': 97, 'message': '同步完成，正在准备重启...'})

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