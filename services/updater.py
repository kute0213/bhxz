"""
一键更新服务：从 GitHub 获取最新代码，安全替换指定文件夹，自动重启。

安全策略：
- 只删除并替换指定的代码文件夹（core, docs, routes, services, static, templates）
- 绝对不碰：数据库文件(site.duckdb*)、backups/、uploads/、ssl/、.env
- 更新后自动通过 os.execv 重启进程
- 跨平台兼容（Windows/Linux/macOS）
- 自动检测最快代理
"""

import os
import sys
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
APP_ROOT = os.path.dirname(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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

# 绝对不删除/覆盖的路径（相对项目根目录）
PROTECTED_PATHS = [
    'site.duckdb',
    'site.duckdb.wal',
    'backups',
    'uploads',
    'ssl',
    '.env',
    '.git',
    '__pycache__',
]

# GitHub 代理检测列表
PROXY_LIST = [
    ('直连', 'https://github.com'),
    ('ghproxy.com', 'https://ghproxy.com/https://github.com'),
    ('ghproxy.net', 'https://ghproxy.net/https://github.com'),
    ('gh.api.99988866.xyz', 'https://gh.api.99988866.xyz/https://github.com'),
    ('gh.h233.eu.org', 'https://gh.h233.eu.org/https://github.com'),
    ('mirror.ghproxy.com', 'https://mirror.ghproxy.com/https://github.com'),
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


def detect_fastest_proxy(timeout=5):
    """检测最快的 GitHub 代理，返回 (代理名称, 代理完整URL)。

    如果所有代理都不可达，返回直连。
    """
    results = []
    threads = []

    # 使用多线程并行测试
    def _test(pn, pu):
        r = _test_proxy_timeout(pn, pu, timeout)
        if r:
            results.append(r)

    for name, url in PROXY_LIST:
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
    return '直连', PROXY_LIST[0][1]


# ---------------------------------------------------------------------------
# 安全路径检查
# ---------------------------------------------------------------------------

def _is_protected(rel_path):
    """检查路径是否受保护（不应删除/覆盖）。"""
    # 规范化路径
    rel_path = rel_path.replace('\\', '/').strip('/')

    # 检查是否匹配受保护路径
    for protected in PROTECTED_PATHS:
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
# 核心更新逻辑
# ---------------------------------------------------------------------------

def _run_update():
    """执行更新（在后台线程中运行）。"""
    try:
        _add_event('progress', {'percent': 2, 'message': '正在检测最快的 GitHub 代理...'})

        # 1. 检测代理
        proxy_name, proxy_url = detect_fastest_proxy()
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

        _add_event('progress', {'percent': 8, 'message': f'正在从 {proxy_name} 克隆仓库...'})

        # 2. 克隆到临时目录
        temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
        try:
            # 使用 git clone
            git_cmd = ['git', 'clone', '--depth', '1', '--single-branch', clone_url, temp_dir]

            # 设置 git 不再交互
            env = os.environ.copy()
            env['GIT_TERMINAL_PROMPT'] = '0'
            env['GIT_ASKPASS'] = 'echo'

            proc = subprocess.run(
                git_cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )

            if proc.returncode != 0:
                error_msg = proc.stderr.strip() or proc.stdout.strip() or '克隆失败'
                raise RuntimeError(f'Git 克隆失败: {error_msg}')

            _add_event('progress', {'percent': 30, 'message': '仓库克隆完成，正在验证...'})

            # 3. 验证临时目录
            if not os.path.isdir(temp_dir):
                raise RuntimeError('克隆目录不存在')

            # 列出仓库中的顶级目录和文件
            repo_items = set()
            for item in os.listdir(temp_dir):
                # 跳过 .git 目录
                if item == '.git':
                    continue
                repo_items.add(item)

            _add_event('progress', {'percent': 35, 'message': f'仓库包含 {len(repo_items)} 个顶级项目，开始更新...'})

            # 4. 统计需要处理的文件
            total_ops = 0
            for folder in TARGET_FOLDERS:
                src = os.path.join(temp_dir, folder)
                if os.path.isdir(src):
                    total_ops += 1

            for root_file in TARGET_ROOT_FILES:
                src = os.path.join(temp_dir, root_file)
                if os.path.isfile(src):
                    total_ops += 1

            if total_ops == 0:
                raise RuntimeError('仓库中没有找到任何需要更新的代码文件夹')

            _add_event('progress', {'percent': 40, 'message': f'将更新 {total_ops} 个项目...'})

            # 5. 更新文件夹（删除再复制）
            progress_base = 40
            progress_per_op = 50 // total_ops if total_ops > 0 else 50
            op_index = 0

            for folder in TARGET_FOLDERS:
                src = os.path.join(temp_dir, folder)
                dst = os.path.join(APP_ROOT, folder)

                if not os.path.isdir(src):
                    _add_event('progress', {
                        'percent': progress_base + (op_index + 1) * progress_per_op,
                        'message': f'跳过 {folder}/（仓库中不存在）',
                    })
                    op_index += 1
                    continue

                # 删除现有文件夹
                if os.path.isdir(dst):
                    _add_event('progress', {
                        'percent': progress_base + op_index * progress_per_op,
                        'message': f'正在删除 {folder}/...',
                    })

                    def _onerror(func, path, exc_info):
                        """删除失败时的回调，尝试多次。"""
                        for attempt in range(3):
                            try:
                                time.sleep(0.5)
                                func(path)
                                return
                            except Exception:
                                pass

                    shutil.rmtree(dst, onerror=_onerror)

                # 复制新文件夹
                _add_event('progress', {
                    'percent': progress_base + op_index * progress_per_op + progress_per_op // 2,
                    'message': f'正在复制 {folder}/...',
                })
                shutil.copytree(src, dst, dirs_exist_ok=True)

                _add_event('progress', {
                    'percent': progress_base + (op_index + 1) * progress_per_op,
                    'message': f'{folder}/ 已更新',
                })
                op_index += 1

            # 6. 更新根级文件
            for root_file in TARGET_ROOT_FILES:
                src = os.path.join(temp_dir, root_file)
                dst = os.path.join(APP_ROOT, root_file)

                if not os.path.isfile(src):
                    continue

                op_index += 1
                _add_event('progress', {
                    'percent': progress_base + op_index * progress_per_op,
                    'message': f'正在更新 {root_file}...',
                })

                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    _add_event('progress', {
                        'percent': progress_base + op_index * progress_per_op,
                        'message': f'更新 {root_file} 失败: {e}',
                    })

            # 7. 清理临时目录
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

            _add_event('progress', {'percent': 95, 'message': '更新完成，正在准备重启...'})

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
    """重启当前应用进程（跨平台）。"""
    import signal

    python_exe = sys.executable
    script = os.path.join(APP_ROOT, 'app.py')

    _add_event('progress', {'percent': 100, 'message': '正在重启服务器...'})

    # 关闭所有后台线程
    try:
        from services.logging import log_writer, log_cleaner
        from services.scheduler import scheduler
        log_writer.stop()
        log_cleaner.stop()
        scheduler.stop()
    except Exception:
        pass

    # 关闭数据库连接
    try:
        from core.db import get_db
        conn = get_db()
        try:
            conn.commit()
        except Exception:
            pass
        conn.close()
    except Exception:
        pass

    # 使用 os.execv 重启（Unix）或 subprocess（Windows fallback）
    if sys.platform == 'win32':
        # Windows 上 os.execv 可能有问题，使用 subprocess 启动新进程后退出
        try:
            subprocess.Popen(
                [python_exe, script],
                cwd=APP_ROOT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0,
            )
        except Exception:
            subprocess.Popen([python_exe, script], cwd=APP_ROOT)
        # 发送终止信号给自己
        os.kill(os.getpid(), signal.SIGTERM)
    else:
        # Unix/Linux/macOS 使用 execv 替换进程
        os.chdir(APP_ROOT)
        os.execv(python_exe, [python_exe, script])


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