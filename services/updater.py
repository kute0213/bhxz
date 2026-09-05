"""一键更新服务 —— 后台线程下载 GitHub 最新代码并安全替换文件。

核心流程：
1. 检测可用的 GitHub 代理
2. 通过代理下载 ZIP 压缩包
3. 解压并同步文件（跳过受保护路径）
4. 重启服务器
"""

import os
import sys
import re
import json
import time
import shutil
import tempfile
import zipfile
import threading
import subprocess
import shlex
from collections import deque
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from config import APP_ROOT

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# GitHub 归档路径格式
REPO_ARCHIVE_PATH = 'kute0213/bhxz/archive/refs/heads/main.zip'

# 下载 URL 格式（按优先级排列）
# 需要依次尝试 proxy_base 拼接 archive_path 的多种格式组合
DOWNLOAD_URL_FORMATS = [
    '{proxy_base}{archive_path}',
    '{proxy_base}{archive_path}',
]

# 默认代理列表（格式：名称、基础 URL、下载模板）
DEFAULT_PROXIES = [
    ('cdn.jsdelivr.net', 'https://cdn.jsdelivr.net/gh/', 'https://cdn.jsdelivr.net/gh/{repo}'),
    ('ghp.ci', 'https://ghp.ci/https://github.com/', 'https://ghp.ci/https://github.com/{repo}'),
    ('ghproxy.net', 'https://ghproxy.net/https://github.com/', 'https://ghproxy.net/https://github.com/{repo}'),
    ('ghproxy.com', 'https://ghproxy.com/https://github.com/', 'https://ghproxy.com/https://github.com/{repo}'),
    ('kkgithub.com', 'https://kkgithub.com/https://github.com/', 'https://kkgithub.com/https://github.com/{repo}'),
    ('gh.llkk.cc', 'https://gh.llkk.cc/https://github.com/', 'https://gh.llkk.cc/https://github.com/{repo}'),
    ('slink.ltd', 'https://slink.ltd/https://github.com/', 'https://slink.ltd/https://github.com/{repo}'),
    ('moeyy.cn', 'https://github.moeyy.cn/https://github.com/', 'https://github.moeyy.cn/https://github.com/{repo}'),
    ('gh-proxy.com', 'https://gh-proxy.com/https://github.com/', 'https://gh-proxy.com/https://github.com/{repo}'),
    ('ghproxy.net', 'https://ghproxy.net/https://github.com/', 'https://ghproxy.net/https://github.com/{repo}'),
    ('gitproxy.cn', 'https://gitproxy.cn/https://github.com/', 'https://gitproxy.cn/https://github.com/{repo}'),
    ('github.2222.win', 'https://github.2222.win/https://github.com/', 'https://github.2222.win/https://github.com/{repo}'),
    ('github.moeyy.xyz', 'https://github.moeyy.xyz/https://github.com/', 'https://github.moeyy.xyz/https://github.com/{repo}'),
    ('gh-proxy.lvedong.top', 'https://gh-proxy.lvedong.top/https://github.com/', 'https://gh-proxy.lvedong.top/https://github.com/{repo}'),
    ('github.catvod.com', 'https://github.catvod.com/https://github.com/', 'https://github.catvod.com/https://github.com/{repo}'),
    ('github.top', 'https://github.top/https://github.com/', 'https://github.top/https://github.com/{repo}'),
    ('gh.akass.cn', 'https://gh.akass.cn/https://github.com/', 'https://gh.akass.cn/https://github.com/{repo}'),
    ('ghproxy.51sww.com', 'https://ghproxy.51sww.com/https://github.com/', 'https://ghproxy.51sww.com/https://github.com/{repo}'),
]

# 默认不替换路径（从安全角度考虑，site.duckdb 等必须保护）
DEFAULT_EXCLUDED = [
    'site.duckdb', 'site.duckdb.wal', 'backups', 'uploads', 'ssl',
    '.env', '.git', '__pycache__',
]

# ---------------------------------------------------------------------------
# 内部状态
# ---------------------------------------------------------------------------

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

_proxy_test_results = []
_proxy_test_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def get_status():
    """获取当前更新状态（线程安全）。"""
    with _update_state['lock']:
        return {
            'running': _update_state['running'],
            'progress': _update_state['progress'],
            'message': _update_state['message'],
            'done': _update_state['done'],
            'success': _update_state['success'],
            'error': _update_state['error'],
        }


def pop_events():
    """取出所有待处理事件（线程安全）。"""
    with _update_state['lock']:
        events = list(_update_state['events'])
        _update_state['events'].clear()
        return events


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


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _add_event(event_type, data):
    """添加更新事件（线程安全）。"""
    try:
        with _update_state['lock']:
            _update_state['events'].append((event_type, data))
            if event_type == 'progress':
                _update_state['progress'] = data.get('percent', 0)
                _update_state['message'] = data.get('message', '')
            elif event_type == 'done':
                _update_state['running'] = False
                _update_state['done'] = True
                _update_state['success'] = data.get('success', False)
                if not data.get('success'):
                    _update_state['error'] = data.get('message', '')
            elif event_type == 'error':
                _update_state['error'] = data.get('message', '')
    except Exception:
        pass


def _is_protected(item, protected_paths):
    """检查路径是否受保护（不替换）。

    支持精确匹配和子路径前缀匹配。
    """
    item_norm = item.replace('\\', '/')
    for p in protected_paths:
        p_norm = p.replace('\\', '/')
        if p_norm.endswith('/'):
            if item_norm.startswith(p_norm) or item_norm == p_norm.rstrip('/'):
                return True
        elif item_norm == p_norm:
            return True
        elif item_norm.startswith(p_norm + '/'):
            return True
    return False


def _sync_item(src, dst, protected_paths, item_rel='', log=print):
    """同步单个文件或目录。

    返回处理文件数。
    """
    if not os.path.exists(src):
        return 0

    if os.path.isfile(src):
        if _is_protected(item_rel, protected_paths):
            log(f'⏭ 跳过受保护: {item_rel}')
            return 1
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copy2(src, dst)
            log(f'✓ 更新: {item_rel}')
        except Exception as e:
            log(f'✗ 更新失败: {item_rel} ({e})')
        return 1

    # 目录：递归同步
    processed = 0
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        for filename in files:
            f_src = os.path.join(root, filename)
            f_rel = os.path.join(item_rel, rel_root, filename) if rel_root != '.' else os.path.join(item_rel, filename)
            f_dst = os.path.join(dst, rel_root, filename) if rel_root != '.' else os.path.join(dst, filename)

            if _is_protected(f_rel, protected_paths):
                log(f'⏭ 跳过受保护: {f_rel}')
                processed += 1
                continue

            try:
                os.makedirs(os.path.dirname(f_dst), exist_ok=True)
                shutil.copy2(f_src, f_dst)
                processed += 1
            except Exception as e:
                log(f'✗ 更新失败: {f_rel} ({e})')
                processed += 1

    return processed


def _make_zip_path():
    """生成临时 ZIP 文件路径。"""
    return os.path.join(tempfile.gettempdir(), f'bhxz_update_{int(time.time())}.zip')


def _download_zip(url, zip_path, progress_callback=None, timeout=30):
    """下载 ZIP 文件，支持进度回调。

    Returns:
        bool: 下载是否成功
    """
    try:
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/zip,*/*',
        })
        with urlopen(req, timeout=timeout) as resp:
            # 检查状态码
            if resp.status != 200:
                return False

            # 检查 Content-Type 是否为 ZIP
            content_type = resp.headers.get('Content-Type', '')
            if 'html' in content_type.lower():
                return False

            # 获取文件大小
            content_length = resp.headers.get('Content-Length')
            total_size = int(content_length) if content_length else 0

            # 下载到临时文件
            downloaded = 0
            chunk_size = 64 * 1024  # 64KB
            last_report = 0

            with open(zip_path, 'wb') as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    # 进度回调
                    if total_size > 0 and progress_callback:
                        pct = int(downloaded * 100 / total_size)
                        if pct > last_report:
                            last_report = pct
                            progress_callback(pct)

            # 验证 ZIP 文件
            if not zipfile.is_zipfile(zip_path):
                os.remove(zip_path)
                return False

            # 检查 ZIP 是否为空
            with zipfile.ZipFile(zip_path, 'r') as zf:
                if len(zf.namelist()) == 0:
                    os.remove(zip_path)
                    return False

            return True

    except (URLError, HTTPError, OSError, ValueError, zipfile.BadZipFile) as e:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        return False


def _extract_zip(zip_path, extract_dir):
    """解压 ZIP 文件，自动处理顶层目录。"""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # 找到顶层目录名
        top_dirs = set()
        for name in zf.namelist():
            parts = name.split('/')
            if len(parts) > 1:
                top_dirs.add(parts[0])

        # 如果有统一的顶层目录，解压到 extract_dir 时去掉这一层
        if len(top_dirs) == 1:
            top_dir = top_dirs.pop()
            for name in zf.namelist():
                if name.startswith(top_dir + '/'):
                    relative = name[len(top_dir) + 1:]
                    if relative:
                        target = os.path.join(extract_dir, relative)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        if not name.endswith('/'):
                            with zf.open(name) as src, open(target, 'wb') as dst:
                                shutil.copyfileobj(src, dst)
        else:
            zf.extractall(extract_dir)


def _detect_fastest_proxy(proxy_list, timeout=3):
    """检测最快的可用代理。

    分批检测（每批 8 个），找到 3 个可用后提前结束。
    """
    import concurrent.futures

    available = []
    batch_size = 8
    early_stop_count = 3
    batch_start = 0
    total_checked = 0

    while batch_start < len(proxy_list):
        batch = proxy_list[batch_start:batch_start + batch_size]
        batch_start += batch_size

        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            future_map = {
                executor.submit(_test_proxy, name, url, timeout): (name, url, tmpl)
                for name, url, tmpl in batch
            }
            for future in concurrent.futures.as_completed(future_map):
                name, url, tmpl = future_map[future]
                total_checked += 1
                try:
                    latency = future.result()
                    if latency is not None:
                        available.append((name, url, tmpl, latency))
                        _add_event('log', {
                            'message': f'  ✓ {name} ({latency:.2f}s)'
                        })
                except Exception:
                    pass

        # 检查是否已有足够代理
        if len(available) >= early_stop_count:
            break

    # 按速度排序
    available.sort(key=lambda x: x[3])
    return available


def _test_proxy(name, base_url, timeout):
    """测试单个代理的延迟。"""
    import urllib.request

    test_url = f'{base_url}https://github.com/'
    try:
        start = time.time()
        req = urllib.request.Request(test_url, headers={
            'User-Agent': 'Mozilla/5.0',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = time.time() - start
            if resp.status == 200:
                return elapsed
    except Exception:
        pass
    return None


def detect_fastest_proxy(proxy_list=None, timeout=3):
    """检测最快的可用代理（对外暴露的接口）。

    Returns:
        list: 按速度排序的 (name, base_url, download_template, latency) 列表
    """
    if proxy_list is None:
        proxy_list = DEFAULT_PROXIES
    return _detect_fastest_proxy(proxy_list, timeout)


# ---------------------------------------------------------------------------
# 核心更新流程
# ---------------------------------------------------------------------------

def _run_update():
    """执行一键更新（后台线程）。"""
    zip_path = None
    temp_dir = None

    try:
        _add_event('progress', {'percent': 0, 'message': '初始化...'})
        _add_event('log', {'message': '开始检查更新...'})

        # 解析配置
        proxy_list = list(DEFAULT_PROXIES)
        protected_paths = list(DEFAULT_EXCLUDED)

        try:
            from config import get_config_value

            # 读取自定义保护路径
            raw_excluded = get_config_value('UPDATE_EXCLUDED_FILES', '')
            if raw_excluded and isinstance(raw_excluded, str):
                custom_paths = [p.strip() for p in raw_excluded.split(',') if p.strip()]
                if custom_paths:
                    protected_paths = custom_paths

            # 读取自定义代理
            raw_proxies = get_config_value('GITHUB_PROXIES', '')
            if raw_proxies and isinstance(raw_proxies, str):
                for line in raw_proxies.strip().split('\n'):
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    name, url = line.split('=', 1)
                    name = name.strip()
                    url = url.strip()
                    if not name or not url:
                        continue
                    # 确保 URL 以 / 结尾
                    if not url.endswith('/'):
                        url += '/'
                    # 构建下载模板
                    download_template = url.rstrip('/') + '/{repo}'
                    # 检查是否已存在同名代理
                    replaced = False
                    for i, (n, u, t) in enumerate(proxy_list):
                        if n == name:
                            proxy_list[i] = (name, url, download_template)
                            replaced = True
                            break
                    if not replaced:
                        proxy_list.append((name, url, download_template))
        except Exception:
            pass

        _add_event('progress', {'percent': 2, 'message': f'已加载配置，{len(protected_paths)} 个受保护路径'})

        # 1. 检测可用代理（分批检测，每批 8 个，超时 2.5s）
        _add_event('progress', {'percent': 3, 'message': f'正在检测 {len(proxy_list)} 个 GitHub 代理...'})
        _add_event('log', {'message': f'╔══ 开始代理检测（共 {len(proxy_list)} 个，分批 8 个，超时 2.5s，早停 3 个）'})
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

        if success_details:
            _add_event('log', {'message': f'║  ✓ 可用代理 ({success_count}): {", ".join(success_details[:6])}'})
            if len(success_details) > 6:
                _add_event('log', {'message': f'║    ... 还有 {len(success_details) - 6} 个可用'})
        if fail_details:
            _add_event('log', {'message': f'║  ✗ 不可用: {fail_count} 个（{fail_details[0]}）'})
        _add_event('log', {'message': f'╚══ 代理检测完成：可用 {success_count} 个，不可用 {fail_count} 个'})

        if not available_proxies:
            err_details = []
            with _proxy_test_lock:
                for r in _proxy_test_results:
                    err_details.append(f'{r["name"]}: {r["error"]}')
            err_msg = '所有 GitHub 代理均不可达，请检查网络连接或稍后重试'
            if err_details:
                err_msg += '\n' + '\n'.join(err_details[:5])
            raise RuntimeError(err_msg)

        rank_parts = [f'{i+1}. {n} ({e:.1f}s)' for i, (n, *_, e) in enumerate(available_proxies[:5])]
        _add_event('log', {'message': f'→ 代理速度排名: {"; ".join(rank_parts)}'})
        if len(available_proxies) > 5:
            _add_event('log', {'message': f'→ 以及另外 {len(available_proxies) - 5} 个可用代理'})

        # 2. 按速度顺序尝试下载 ZIP 压缩包
        download_success = False
        last_error = ''
        total_attempts = len(available_proxies)

        for attempt_idx, (name, base_url, download_template, elapsed) in enumerate(available_proxies):
            proxy_base = download_template.replace('{repo}', '')
            if not proxy_base.endswith('/'):
                proxy_base += '/'

            candidate_urls = []
            for fmt in DOWNLOAD_URL_FORMATS:
                url = fmt.format(proxy_base=proxy_base, archive_path=REPO_ARCHIVE_PATH)
                candidate_urls.append(url)

            _add_event('log', {'message': f'{"─" * 40}'})
            hint = '首选' if attempt_idx == 0 else '备用'
            _add_event('log', {'message': f'下载尝试 #{attempt_idx + 1}: {name} （{hint}，延迟 {elapsed:.1f}s）'})
            _add_event('progress', {'percent': 5, 'message': f'正在从 {name} 下载更新包...'})

            zip_path = _make_zip_path()
            download_start = time.time()

            def _dl_progress(pct):
                mapped = 5 + int(pct * 65 / 100)
                _add_event('progress', {'percent': mapped, 'message': f'正在下载更新包... {int(pct)}%'})

            url_ok = False
            for url_idx, zip_url in enumerate(candidate_urls):
                _add_event('log', {'message': f'  URL格式{url_idx + 1}: {zip_url}'})
                try:
                    success = _download_zip(zip_url, zip_path, progress_callback=_dl_progress, timeout=30)
                    if success:
                        url_ok = True
                        break
                    else:
                        _add_event('log', {'message': f'  ✗ 格式{url_idx + 1} 不可用'})
                except Exception as e:
                    _add_event('log', {'message': f"  ✗ 格式{url_idx + 1} 异常: {str(e)[:60]}"})
                finally:
                    if not url_ok and os.path.isfile(zip_path):
                        try:
                            os.remove(zip_path)
                        except Exception:
                            pass

            if url_ok:
                download_elapsed = time.time() - download_start
                _add_event('log', {'message': f'✓ {name} 下载成功（耗时 {download_elapsed:.1f}s）'})
                _add_event('progress', {'percent': 70, 'message': '下载完成，正在解压...'})

                temp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
                _add_event('log', {'message': '正在解压更新包...'})
                _extract_zip(zip_path, temp_dir)

                download_success = True
                break
            else:
                _add_event('log', {'message': f'✗ {name} 所有格式均失败（耗时 {time.time() - download_start:.1f}s）'})
                last_error = f'{name} 所有格式均失败'

        if not download_success:
            _add_event('log', {'message': f'{"─" * 40}'})
            _add_event('log', {'message': '尝试直接下载 GitHub 原始归档（无代理）...'})
            direct_url = f'https://github.com/{REPO_ARCHIVE_PATH}'
            _add_event('log', {'message': f"  下载 URL: {direct_url}"})

            zip_path = _make_zip_path()

            def _direct_progress(pct):
                mapped = 5 + int(pct * 65 / 100)
                _add_event('progress', {'percent': mapped, 'message': f'正在直连下载更新包... {int(pct)}%'})

            try:
                success = _download_zip(direct_url, zip_path, progress_callback=_direct_progress, timeout=15)
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

        repo_items = sorted([
            item for item in os.listdir(temp_dir)
            if item != '.git'
        ])

        if not repo_items:
            raise RuntimeError('仓库为空，没有可同步的文件')

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

        processed = 0
        remaining_pct = 95 - 75

        for item in repo_items:
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
            _add_event('progress', {
                'percent': 75 + int(processed * remaining_pct / total_files),
                'message': f'正在同步 {item}/...',
            })

            processed += _sync_item(
                src, dst, protected_paths, item_rel=item,
                log=lambda msg: _add_event('log', {'message': f'    {msg}'}),
            )

        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

        _add_event('log', {'message': f'✓ 同步完成，共处理 {processed} 个文件'})

        # 检查设置，决定是否运行静态资源构建脚本
        _build_static = False
        try:
            from config import get_config_value
            _build_static = get_config_value('BUILD_STATIC_ON_UPDATE', False)
        except Exception:
            pass

        if _build_static:
            _add_event('progress', {'percent': 97, 'message': '同步完成，正在构建静态资源...'})
            build_script = os.path.join(APP_ROOT, 'scripts', 'build', 'build_static.py')
            if os.path.isfile(build_script):
                _add_event('log', {'message': '正在构建静态资源...'})
                _add_event('progress', {'percent': 97, 'message': '正在构建静态资源...'})
                build_env = {**os.environ, 'PYTHONUNBUFFERED': '1'}
                proc = subprocess.Popen(
                    [sys.executable, build_script],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    env=build_env,
                )
                build_ok = False
                try:
                    for line in iter(proc.stdout.readline, ''):
                        line = line.rstrip('\n\r')
                        if line:
                            _add_event('log', {'message': f'  | {line}'})
                    proc.wait(timeout=180)
                    build_ok = proc.returncode == 0
                except subprocess.TimeoutExpired:
                    proc.kill()
                    raise
                finally:
                    proc.stdout.close()
                if build_ok:
                    _add_event('log', {'message': '[OK] 静态资源构建完成'})
                else:
                    _add_event('log', {'message': '[WARN] 静态资源构建完成（有警告）'})
            else:
                _add_event('log', {'message': '[WARN] 未找到构建脚本: scripts/build/build_static.py'})

        # 标记需要在下一次启动时运行清理与迁移脚本
        _add_event('progress', {'percent': 98, 'message': '正在标记清理与迁移任务...'})
        _add_event('log', {'message': '标记清理与迁移脚本，将在下次服务器启动时运行...'})
        try:
            from services.settings_manager import set_setting
            set_setting('UPLOADS_MIGRATION_PENDING', '1')
            _add_event('log', {'message': '[OK] 已标记清理与迁移任务，重启后自动执行'})
        except Exception as e:
            _add_event('log', {'message': f'[WARN] 标记迁移任务失败（重启后手动运行 scripts/uploads.py）: {e}'})

        _add_event('progress', {'percent': 99, 'message': '构建完成，正在准备重启...'})

        _add_event('done', {
            'success': True,
            'message': '更新成功，即将重启服务器...',
        })
        time.sleep(1)
        _restart_app()

    except Exception as e:
        error_msg = str(e)
        _add_event('log', {'message': f'✗ 更新失败: {error_msg}'})
        _add_event('error', {'message': f'更新失败: {error_msg}'})
        _add_event('done', {'success': False, 'message': f'更新失败: {error_msg}'})
    finally:
        # 确保 running 标志被重置，允许重新尝试
        with _update_state['lock']:
            _update_state['running'] = False
        if zip_path and os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


def _restart_app():
    """重启当前应用进程（跨平台，优雅替换）。

    使用默认方式启动新服务器，然后自动关闭当前进程。
    """
    _add_event('progress', {'percent': 100, 'message': '正在重启服务器...'})

    time.sleep(0.5)

    python_exe = sys.executable
    script = os.path.join(APP_ROOT, 'app.py')
    _add_event('log', {'message': f'启动新服务器: {python_exe} {script}'})
    try:
        with open(os.devnull, 'w') as devnull:
            subprocess.Popen(
                [python_exe, script],
                cwd=APP_ROOT,
                close_fds=True,
                start_new_session=True,
                stdout=devnull,
                stderr=devnull,
                stdin=devnull,
            )
    except Exception as e:
        _add_event('log', {'message': f'启动服务器失败: {e}'})
        _shutdown_current_process()
        return

    _shutdown_current_process()


def _shutdown_current_process():
    """自动关闭当前进程（跨平台）。"""
    if sys.platform == 'win32':
        import signal
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass
    sys.exit(0)