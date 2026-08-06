"""
一键更新服务：从 GitHub 获取最新代码，安全替换指定文件夹，自动重启。

安全策略：
- 只删除并替换指定的代码文件夹（core, docs, routes, services, static, templates）
- 绝对不碰：数据库文件、backups/、uploads/、ssl/、.env
- 不替换的文件列表可在管理后台一键更新页面设置
- 更新后自动重启进程
- 跨平台兼容（Windows/Linux/macOS）
- 自动检测最快代理
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

# 需要替换的代码文件夹（删除再下载）
TARGET_FOLDERS = [
    'core',
    'docs',
    'routes',
    'services',
    'static',
    'templates',
]

# 需要更新的根级文件（直接覆盖）
TARGET_ROOT_FILES = [
    'app.py',
    'requirements.txt',
]

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

# 默认 GitHub 代理列表（按响应速度排序，检测时自动选最快的）
# 来源：https://github.com/topics/github-proxy
DEFAULT_PROXY_LIST = [
    ('直连', 'https://github.com'),
    # 通用型代理（URL 前缀方式）
    ('ghproxy.com', 'https://ghproxy.com/https://github.com'),
    ('ghproxy.net', 'https://ghproxy.net/https://github.com'),
    ('mirror.ghproxy.com', 'https://mirror.ghproxy.com/https://github.com'),
    ('ghproxy.homeboyc.cn', 'https://ghproxy.homeboyc.cn/https://github.com'),
    ('gh.llkk.cc', 'https://gh.llkk.cc/https://github.com'),
    ('hub.gitmirror.com', 'https://hub.gitmirror.com/https://github.com'),
    ('gh.h233.eu.org', 'https://gh.h233.eu.org/https://github.com'),
    ('gh.api.99988866.xyz', 'https://gh.api.99988866.xyz/https://github.com'),
    ('moeyy.cn/gh-proxy', 'https://moeyy.cn/gh-proxy/https://github.com'),
    # 直接访问型镜像站
    ('bgithub.xyz', 'https://bgithub.xyz/https://github.com'),
    ('kkgithub.com', 'https://kkgithub.com/https://github.com'),
    ('kgithub.com', 'https://kgithub.com/https://github.com'),
    ('hub.fastgit.org', 'https://hub.fastgit.org/https://github.com'),
    ('gitclone.com', 'https://gitclone.com/github.com'),
    ('github.ur1.fun', 'https://github.ur1.fun/https://github.com'),
    ('githubfast.com', 'https://githubfast.com/https://github.com'),
    # 文件加速型
    ('github.akams.cn', 'https://github.akams.cn/https://github.com'),
    ('ghp.ci', 'https://ghp.ci/https://github.com'),
    ('g.nite07.org', 'https://g.nite07.org/https://github.com'),
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
# 代理检测
# ---------------------------------------------------------------------------

def _test_proxy_timeout(proxy_name, proxy_url, timeout=5):
    """测试代理的响应时间，返回 (名称, 完整URL, 延迟秒数) 或 None。"""
    test_url = proxy_url.rstrip('/') + '/'
    try:
        req = Request(test_url, method='HEAD')
        # 设置合理的 User-Agent
        req.add_header('User-Agent', 'Mozilla/5.0')
        start = time.time()
        resp = urlopen(req, timeout=timeout)
        elapsed = time.time() - start
        # 检查响应状态
        if resp.status < 400:
            return (proxy_name, proxy_url, elapsed)
    except (URLError, OSError, ValueError):
        pass
    return None


def detect_fastest_proxy(proxy_list=None, timeout=5):
    """检测最快的 GitHub 代理，返回 (代理名称, 代理完整URL)。

    如果所有代理都不可达，返回直连。
    """
    if proxy_list is None:
        proxy_list = DEFAULT_PROXY_LIST

    results = []
    threads = []

    # 使用多线程并行测试
    def _test(pn, pu):
        r = _test_proxy_timeout(pn, pu, timeout)
        if r:
            results.append(r)

    for name, url in proxy_list:
        t = threading.Thread(target=_test, args=(name, url), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    if results:
        # 按延迟排序，取最快的
        results.sort(key=lambda x: x[2])
        fastest = results[0]
        return fastest[0], fastest[1]

    # 所有代理都失败，返回直连
    return '直连', proxy_list[0][1]


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


def _is_target_folder(rel_path):
    """检查路径是否是需要更新的目标文件夹内的文件。"""
    rel_path = rel_path.replace('\\', '/').strip('/')
    for folder in TARGET_FOLDERS:
        if rel_path == folder or rel_path.startswith(folder + '/'):
            return True
    return False


def _is_target_root_file(rel_path):
    """检查是否是根级需要更新的文件。"""
    rel_path = rel_path.replace('\\', '/').strip('/')
    return rel_path in TARGET_ROOT_FILES


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

        # 0. 从设置读取不替换文件列表和自定义代理
        protected_paths = list(DEFAULT_PROTECTED_PATHS)
        proxy_list = list(DEFAULT_PROXY_LIST)

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
                    name = name.strip()
                    url = url.strip()
                    if name and url:
                        # 替换同名的已有代理，或追加
                        replaced = False
                        for i, (n, u) in enumerate(proxy_list):
                            if n == name:
                                proxy_list[i] = (name, url)
                                replaced = True
                                break
                        if not replaced:
                            proxy_list.append((name, url))
        except Exception:
            pass  # 读取设置失败时使用默认值

        _add_event('progress', {'percent': 2, 'message': f'已加载 {len(protected_paths)} 个受保护路径，{len(proxy_list)} 个代理'})

        # 1. 检测 git 是否可用
        git_path = _find_git()
        if not git_path:
            raise RuntimeError(
                '未找到 Git，请先安装 Git（https://git-scm.com/downloads）'
                '并确保 Git 已添加到系统 PATH 环境变量中'
            )

        _add_event('progress', {'percent': 3, 'message': f'已找到 Git: {git_path}'})

        # 2. 检测代理
        proxy_name, proxy_url = detect_fastest_proxy(proxy_list=proxy_list)
        _add_event('progress', {'percent': 5, 'message': f'已选择代理: {proxy_name}'})

        # 构建克隆 URL
        if proxy_name == '直连':
            clone_url = GITHUB_REPO
        else:
            # 代理 URL 需要拼接仓库路径
            base = proxy_url.rstrip('/')
            # 如果代理 URL 已经包含 github.com，直接添加 /kute0213/bhxz.git
            if 'github.com' in base:
                clone_url = base.rstrip('/') + '/kute0213/bhxz.git'
            else:
                clone_url = base.rstrip('/') + '/https://github.com/kute0213/bhxz.git'

        _add_event('progress', {'percent': 5, 'message': f'正在从 {proxy_name} 克隆仓库...'})

        # 2. 克隆到临时目录
        temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
        try:
            # 使用 git clone（使用完整路径确保 Windows 能找到）
            git_cmd = [git_path, 'clone', '--depth', '1', '--single-branch', '--progress', clone_url, temp_dir]

            # 设置 git 不再交互
            env = os.environ.copy()
            env['GIT_TERMINAL_PROMPT'] = '0'
            env['GIT_ASKPASS'] = 'echo'

            # Windows 上确保 Git 的 bin 目录在 PATH 中（解决 DLL 依赖问题）
            if sys.platform == 'win32':
                git_dir = os.path.dirname(os.path.dirname(git_path))
                git_bin = os.path.join(git_dir, 'bin')
                git_cmd_dir = os.path.join(git_dir, 'cmd')
                extra_paths = []
                for p in [git_bin, git_cmd_dir]:
                    if os.path.isdir(p) and p not in env.get('PATH', ''):
                        extra_paths.append(p)
                if extra_paths:
                    env['PATH'] = os.pathsep.join(extra_paths + [env.get('PATH', '')])

            # 流式克隆，实时解析进度
            proc = subprocess.Popen(
                git_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
            )

            # 解析 git clone --progress 的 stderr 输出
            CLONE_START = 5
            CLONE_END = 70
            progress_range = CLONE_END - CLONE_START
            last_clone_pct = -1
            line_buf = b''

            def _read_stderr(stream):
                nonlocal last_clone_pct, line_buf
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    for byte in chunk:
                        if byte == 0x0d:  # \r 回车符（进度行结束）
                            _parse_progress_line(line_buf, last_clone_pct)
                            line_buf = b''
                        elif byte == 0x0a:  # \n 换行符
                            line_buf = b''
                        else:
                            line_buf += bytes([byte])

            def _parse_progress_line(buf, last_pct):
                nonlocal last_clone_pct
                text = buf.decode('utf-8', errors='replace')
                m = re.search(r'(\d+)\s*%', text)
                if m:
                    pct = int(m.group(1))
                    if pct != last_pct:
                        last_clone_pct = pct
                        mapped = CLONE_START + int(pct * progress_range / 100)
                        _add_event('progress', {
                            'percent': mapped,
                            'message': f'正在克隆仓库... {pct}%',
                        })

            # 在后台线程中读取 stderr
            stderr_thread = threading.Thread(
                target=_read_stderr, args=(proc.stderr,), daemon=True
            )
            stderr_thread.start()
            proc.wait()
            stderr_thread.join(timeout=5)

            if proc.returncode != 0:
                remaining = proc.stderr.read().decode('utf-8', errors='replace').strip()
                error_msg = remaining or '克隆失败'
                raise RuntimeError(f'Git 克隆失败: {error_msg}')

            _add_event('progress', {'percent': 72, 'message': '仓库克隆完成，正在验证...'})

            # 3. 验证临时目录
            if not os.path.isdir(temp_dir):
                raise RuntimeError('克隆目录不存在')

            # 列出仓库中的顶级目录和文件
            repo_items = set()
            for item in os.listdir(temp_dir):
                if item == '.git':
                    continue
                repo_items.add(item)

            _add_event('progress', {'percent': 74, 'message': f'仓库包含 {len(repo_items)} 个顶级项目，开始更新...'})

            # 4. 统计需要处理的文件数量（精确到文件级别，让进度更平滑）
            total_files = 0
            file_ops = []  # [(type, src, dst), ...]   type: 'folder' | 'root_file'

            for folder in TARGET_FOLDERS:
                src = os.path.join(temp_dir, folder)
                dst = os.path.join(APP_ROOT, folder)
                if os.path.isdir(src):
                    file_ops.append(('folder', src, dst, folder))

            for root_file in TARGET_ROOT_FILES:
                src = os.path.join(temp_dir, root_file)
                dst = os.path.join(APP_ROOT, root_file)
                if os.path.isfile(src):
                    file_ops.append(('root_file', src, dst, root_file))

            if not file_ops:
                raise RuntimeError('仓库中没有找到任何需要更新的代码文件夹')

            # 统计每个目录下的实际文件数以精确计算进度
            for op_type, src, dst, name in file_ops:
                if op_type == 'folder':
                    for dirpath, dirnames, filenames in os.walk(src):
                        total_files += len(filenames)
                else:
                    total_files += 1

            if total_files == 0:
                total_files = len(file_ops)

            _add_event('progress', {'percent': 75, 'message': f'将更新 {total_files} 个文件...'})

            # 5. 更新文件（精确到每个文件，进度条平滑推进，但避免日志刷屏）
            FILE_PROGRESS_START = 75
            FILE_PROGRESS_END = 95
            file_progress_range = FILE_PROGRESS_END - FILE_PROGRESS_START
            processed_files = 0
            last_reported_pct = -1

            def _update_file_progress(message, force=False):
                """更新进度。force=True 时强制上报（用于文件夹切换等关键节点）。"""
                nonlocal processed_files, last_reported_pct
                processed_files += 1
                pct = FILE_PROGRESS_START + int(processed_files * file_progress_range / total_files)
                pct = min(pct, 94)

                # 只有百分比变化 >= 2 或强制上报时才发事件，避免逐文件刷屏
                if force or abs(pct - last_reported_pct) >= 2:
                    last_reported_pct = pct
                    _add_event('progress', {'percent': pct, 'message': message})

            for op_type, src, dst, name in file_ops:
                if op_type == 'folder':
                    # 删除现有文件夹
                    if os.path.isdir(dst):
                        _update_file_progress(f'正在删除 {name}/...', force=True)

                        def _onerror(func, path, exc_info):
                            for attempt in range(3):
                                try:
                                    time.sleep(0.5)
                                    func(path)
                                    return
                                except Exception:
                                    pass

                        shutil.rmtree(dst, onerror=_onerror)

                    # 复制新文件夹（逐个文件上报进度，但按百分比阈值控制日志频率）
                    copy_files = []
                    for dirpath, dirnames, filenames in os.walk(src):
                        rel_dir = os.path.relpath(dirpath, src)
                        for fn in filenames:
                            src_file = os.path.join(dirpath, fn)
                            dst_file = os.path.join(dst, rel_dir, fn) if rel_dir != '.' else os.path.join(dst, fn)
                            copy_files.append((src_file, dst_file))

                    # 确保目标子目录存在
                    all_dirs = set()
                    for _, dst_file in copy_files:
                        all_dirs.add(os.path.dirname(dst_file))
                    for d in sorted(all_dirs):
                        os.makedirs(d, exist_ok=True)

                    # 逐个复制文件，进度条每变化 2% 才上报一次
                    for src_file, dst_file in copy_files:
                        try:
                            shutil.copy2(src_file, dst_file)
                        except Exception:
                            pass
                        _update_file_progress(f'正在复制 {name}/...')

                    # 文件夹完成时强制上报
                    _update_file_progress(f'{name}/ 已更新', force=True)

                else:
                    # 根级文件直接覆盖
                    try:
                        shutil.copy2(src, dst)
                    except Exception as e:
                        _update_file_progress(f'更新 {name} 失败: {e}', force=True)
                    _update_file_progress(f'正在更新 {name}...')

            # 7. 清理临时目录
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

            _add_event('progress', {'percent': 97, 'message': '更新完成，正在准备重启...'})

        except Exception:
            # 清理临时目录
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            raise

        # 8. 更新完成，准备重启
        _add_event('done', {
            'success': True,
            'message': '更新成功，即将重启服务器...',
        })

        # 给前端一点时间接收事件
        time.sleep(1)

        # 9. 重启
        _restart_app()

    except Exception as e:
        error_msg = str(e)
        _add_event('error', {'message': f'更新失败: {error_msg}'})
        _add_event('done', {'success': False, 'message': f'更新失败: {error_msg}'})


def _restart_app():
    """重启当前应用进程（跨平台，优雅替换）。

    - Unix: 使用 os.execv 直接替换当前进程，干净利落
    - Windows: 使用 Popen 启动新进程 + 优雅退出，避免 CMD 窗口闪烁
    """
    python_exe = sys.executable
    script = os.path.join(APP_ROOT, 'app.py')

    _add_event('progress', {'percent': 100, 'message': '正在重启服务器...'})

    # 给前端一点时间接收事件
    time.sleep(0.5)

    if sys.platform == 'win32':
        _restart_win32(python_exe, script)
    else:
        # Unix/Linux/macOS 使用 execv 替换进程
        os.chdir(APP_ROOT)
        os.execv(python_exe, [python_exe, script])


def _restart_win32(python_exe, script):
    """Windows 可靠重启：Popen 启动新进程 + 优雅退出。

    避免 CMD 窗口闪烁。使用 CREATE_NO_WINDOW 标志让新进程无窗口启动，
    然后通过信号触发当前进程的优雅关闭。
    """
    import signal

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

    # 2. 触发当前进程的优雅退出
    #    使用 os.kill 发送 SIGTERM，app.py 中注册了 SIGTERM 处理函数
    #    会依次关闭后台线程、关闭数据库连接，然后 sys.exit(0)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        pass

    # 3. 如果上面的信号处理没生效，兜底退出
    sys.exit(0)


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