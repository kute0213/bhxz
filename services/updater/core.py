"""一键更新服务 - 核心更新流程与公共 API。"""

import os
import sys
import time
import shutil
import tempfile
import zipfile
import threading
import subprocess
from collections import deque

from config import APP_ROOT
from services.updater.config import (
    REPO_ARCHIVE_PATH,
    DOWNLOAD_URL_FORMATS,
    RELIABLE_PROXIES,
    DEFAULT_EXCLUDED,
    _update_state,
)


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


def detect_fastest_proxy(proxy_list=None, timeout=3):
    """检测最快的可用代理（对外暴露的接口）。"""
    if proxy_list is None:
        proxy_list = RELIABLE_PROXIES
    return _detect_fastest_proxy(proxy_list, timeout)


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
    """检查路径是否受保护（不替换）。"""
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
    """同步单个文件或目录。返回处理文件数。"""
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
    """使用 requests 下载 ZIP 文件，支持进度回调。

    不依赖 Content-Type 判断（代理可能返回 text/html），
    下载完成后通过 zipfile.is_zipfile 验证文件有效性。
    """
    try:
        import requests as req_lib
        resp = req_lib.get(url, stream=True, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        resp.raise_for_status()

        total_size = int(resp.headers.get('Content-Length', 0))
        downloaded = 0
        last_report = 0

        with open(zip_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and progress_callback:
                        pct = int(downloaded * 100 / total_size)
                        if pct > last_report:
                            last_report = pct
                            progress_callback(pct)

        if not zipfile.is_zipfile(zip_path):
            os.remove(zip_path)
            return False

        with zipfile.ZipFile(zip_path, 'r') as zf:
            if len(zf.namelist()) == 0:
                os.remove(zip_path)
                return False

        return True

    except Exception:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        return False


def _extract_zip(zip_path, extract_dir):
    """解压 ZIP 文件，自动处理顶层目录。"""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        top_dirs = set()
        for name in zf.namelist():
            parts = name.split('/')
            if len(parts) > 1:
                top_dirs.add(parts[0])

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

    通过尝试访问代理的首页来测试连通性，不依赖特定 URL 格式。
    """
    import requests as req_lib

    for name, base_url, tmpl in proxy_list:
        # 解析代理的原始域名作为测试 URL
        test_url = base_url.rstrip('/')
        try:
            start = time.time()
            resp = req_lib.get(test_url, timeout=timeout, headers={
                'User-Agent': 'Mozilla/5.0',
            })
            if resp.status_code < 500:  # 任何非服务器错误都算可用
                latency = time.time() - start
                _add_event('log', {
                    'message': f'  ✓ {name} ({latency:.2f}s)'
                })
                return [(name, base_url, tmpl, latency)]
        except Exception:
            pass

    return []


def _build_download_urls(download_template, name, base_url):
    """构建多个候选下载 URL，兼容不同代理格式。"""
    candidate_urls = []

    # 格式1: {template_base}/archive_path
    template_base = download_template.replace('{repo}', '')
    if not template_base.endswith('/'):
        template_base += '/'
    candidate_urls.append(f'{template_base}{REPO_ARCHIVE_PATH}')

    # 格式2: base_url + full github URL
    github_url = f'https://github.com/{REPO_ARCHIVE_PATH}'
    b = base_url.rstrip('/')
    candidate_urls.append(f'{b}/{github_url}')

    # 格式3: base_url + archive_path
    candidate_urls.append(f'{b}/{REPO_ARCHIVE_PATH}')

    # 格式4: 标准 DOWNLOAD_URL_FORMATS 模板
    for fmt in DOWNLOAD_URL_FORMATS:
        url = fmt.format(proxy_base=template_base, archive_path=REPO_ARCHIVE_PATH)
        if url not in candidate_urls:
            candidate_urls.append(url)

    return candidate_urls


def _try_download(urls, zip_path, progress_callback, timeout, label):
    """尝试多个 URL 下载 ZIP，返回 (success, temp_dir)。"""
    import tempfile as _tempfile

    for zip_url in urls:
        _add_event('log', {'message': f'  URL: {zip_url}'})
        try:
            success = _download_zip(zip_url, zip_path, progress_callback=progress_callback, timeout=timeout)
            if success:
                _add_event('log', {'message': f'  ✓ {label} 下载成功'})
                temp_dir = _tempfile.mkdtemp(prefix='bhxz_update_')
                _add_event('log', {'message': '正在解压更新包...'})
                _extract_zip(zip_path, temp_dir)
                return True, temp_dir
            else:
                _add_event('log', {'message': '  ✗ 不可用'})
        except Exception as e:
            _add_event('log', {'message': f"  ✗ 异常: {str(e)[:60]}"})
        finally:
            if os.path.isfile(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass

    return False, None


def _run_update():
    """执行一键更新（后台线程）。

    更新顺序：① 优先使用 git（如果当前目录是 git 仓库且系统有 git）→
              ② 代理下载 → ③ GitHub 直连下载。
    只要有一条通道能拉取到代码就继续；全部失败才报错。
    """
    zip_path = None
    temp_dir = None
    used_git = False

    try:
        _add_event('progress', {'percent': 0, 'message': '初始化...'})
        _add_event('log', {'message': '开始检查更新...'})

        proxy_list = list(RELIABLE_PROXIES)
        protected_paths = list(DEFAULT_EXCLUDED)

        try:
            from config import get_config_value

            raw_excluded = get_config_value('UPDATE_EXCLUDED_FILES', '')
            if raw_excluded and isinstance(raw_excluded, str):
                custom_paths = [p.strip() for p in raw_excluded.split(',') if p.strip()]
                if custom_paths:
                    protected_paths = custom_paths

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
                    if not url.endswith('/'):
                        url += '/'
                    download_template = url.rstrip('/') + '/{repo}'
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

        # ------------------------------------------------------------------
        # 方式 1：Git（优先，最稳定、不绕远）
        # ------------------------------------------------------------------
        def _try_git_update():
            """尝试使用 git pull 更新代码。成功返回 True，失败返回 False 并记录日志。"""
            git_dir = os.path.join(APP_ROOT, '.git')
            if not os.path.isdir(git_dir):
                _add_event('log', {'message': '未检测到 .git 目录，跳过 git 更新'})
                return False

            # 检查系统是否有 git
            try:
                subprocess.run(
                    ['git', '--version'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                    encoding='utf-8', errors='replace',
                )
            except Exception:
                _add_event('log', {'message': '系统未安装 git，跳过 git 更新'})
                return False

            _add_event('progress', {'percent': 5, 'message': '正在通过 Git 拉取更新...'})
            _add_event('log', {'message': '✓ 检测到 git 仓库，优先使用 git 更新...'})

            try:
                # 统一 UTF-8，解决 Windows 中文输出
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'

                # fetch
                proc = subprocess.run(
                    ['git', 'fetch', '--all', '--tags'],
                    cwd=APP_ROOT, capture_output=True, timeout=60,
                    encoding='utf-8', errors='replace', env=env,
                )
                if proc.returncode != 0:
                    _add_event('log', {'message': f'  ✗ git fetch 失败: {proc.stderr.strip()[:200]}'})
                    return False

                # reset 到 origin/main（保留 protected_paths 本地文件）
                proc = subprocess.run(
                    ['git', 'reset', '--hard', 'origin/main'],
                    cwd=APP_ROOT, capture_output=True, timeout=30,
                    encoding='utf-8', errors='replace', env=env,
                )
                if proc.returncode != 0:
                    _add_event('log', {'message': f'  ✗ git reset 失败: {proc.stderr.strip()[:200]}'})
                    return False

                _add_event('log', {'message': '  ✓ git pull 完成，代码已同步到 origin/main'})
                return True
            except subprocess.TimeoutExpired:
                _add_event('log', {'message': '  ✗ git 操作超时'})
                return False
            except Exception as e:
                _add_event('log', {'message': f'  ✗ git 异常: {e}'})
                return False

        used_git = _try_git_update()

        # ------------------------------------------------------------------
        # 方式 2 / 3：代理 + 直连（Git 失败时走这条兜底路径）
        # ------------------------------------------------------------------
        download_success = False
        last_error = ''

        if not used_git:
            _add_event('progress', {'percent': 3, 'message': f'正在检测 {len(proxy_list)} 个代理...'})
            _add_event('log', {'message': f'╔══ Git 不可用，开始代理检测（共 {len(proxy_list)} 个，超时 3s）'})
            _add_event('log', {'message': f'║  {", ".join(n for n, *_ in proxy_list)}'})

            available_proxies = detect_fastest_proxy(proxy_list=proxy_list, timeout=3)

            _add_event('log', {'message': f'╚══ 代理检测完成：可用 {len(available_proxies)} 个'})

            if not available_proxies:
                _add_event('log', {'message': '所有代理均不可达，尝试直连下载'})
            else:
                name, base_url, download_template, elapsed = available_proxies[0]
                _add_event('log', {'message': f'→ 使用代理: {name} ({elapsed:.1f}s)'})

                candidate_urls = _build_download_urls(download_template, name, base_url)

                _add_event('log', {'message': f'{"─" * 40}'})
                _add_event('log', {'message': f'尝试从 {name} 下载更新包...'})
                _add_event('progress', {'percent': 5, 'message': f'正在从 {name} 下载更新包...'})

                zip_path = _make_zip_path()

                def _dl_progress(pct):
                    mapped = 5 + int(pct * 65 / 100)
                    _add_event('progress', {'percent': mapped, 'message': f'正在下载更新包... {int(pct)}%'})

                download_success, temp_dir = _try_download(
                    candidate_urls, zip_path, _dl_progress, 30, name
                )
                if download_success:
                    used_git = False  # 标记为下载模式，后续走文件同步分支
                else:
                    _add_event('log', {'message': f'✗ {name} 下载失败'})
                    last_error = f'{name} 下载失败'

            if not download_success:
                _add_event('log', {'message': f'{"─" * 40}'})
                _add_event('log', {'message': '尝试直接下载 GitHub 原始归档（无代理）...'})

                direct_urls = [
                    f'https://github.com/{REPO_ARCHIVE_PATH}',
                    f'https://github.com/kute0213/bhxz/archive/refs/heads/main.zip',
                ]

                def _direct_progress(pct):
                    mapped = 5 + int(pct * 65 / 100)
                    _add_event('progress', {'percent': mapped, 'message': f'正在直连下载更新包... {int(pct)}%'})

                zip_path = _make_zip_path()
                download_success, temp_dir = _try_download(
                    direct_urls, zip_path, _direct_progress, 15, 'GitHub 直连'
                )
                if not download_success:
                    last_error = '直连下载失败'

            if not download_success:
                raise RuntimeError(
                    f'Git、代理及直连均失败。\n最后错误: {last_error[:300]}'
                )

        # ------------------------------------------------------------------
        # 后续步骤：Git 成功或下载成功后共用
        # ------------------------------------------------------------------
        if used_git:
            # Git 方式：已直接写入 APP_ROOT，不需要再同步文件
            _add_event('progress', {'percent': 85, 'message': 'Git 更新完成'})
        else:
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
                    encoding='utf-8', errors='replace',
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

        _add_event('progress', {'percent': 99, 'message': '同步完成，正在准备重启...'})
        _add_event('log', {'message': '正在准备重启服务器...'})

        # 写入重启脚本，再发送 done 事件，确保重启脚本已就绪
        _add_event('progress', {'percent': 100, 'message': '正在重启服务器...'})
        restart_script = _write_restart_script()

        if restart_script and os.path.isfile(restart_script):
            # 启动重启脚本（独立进程组，不依赖当前进程存活）
            try:
                _launch_restart_script(restart_script)
                _add_event('log', {'message': '✓ 重启脚本已启动，服务器将在旧进程退出后自动重启'})
            except Exception as e:
                _add_event('log', {'message': f'✗ 启动重启脚本失败: {e}'})
                # 重启脚本失败时，尝试直接重启
                _add_event('log', {'message': '尝试直接启动新进程...'})
                _direct_restart()

        # 发送 done 事件（此时重启脚本已就绪，新进程必会启动）
        _add_event('done', {
            'success': True,
            'message': '更新成功，服务器正在重启...',
        })

        # 给前端一点时间处理 done 事件
        time.sleep(1)
        _shutdown_current_process()

    except Exception as e:
        error_msg = str(e)
        _add_event('log', {'message': f'✗ 更新失败: {error_msg}'})
        _add_event('error', {'message': f'更新失败: {error_msg}'})
        _add_event('done', {'success': False, 'message': f'更新失败: {error_msg}'})
    finally:
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


# ---------------------------------------------------------------------------
# 重启逻辑（单一 Python 辅助脚本，跨平台，无编码问题）
# ---------------------------------------------------------------------------


# 重启辅助脚本模板：完全独立于当前进程，等待旧进程退出后拉起新服务器。
# 逻辑为纯 ASCII，仅运行时占位符替换（路径含中文时也安全，Python 源码默认 UTF-8）。
_RESTART_TEMPLATE = '''\
import os
import subprocess
import sys
import time


def _process_alive(pid):
    """跨平台判断进程是否存活（Windows 下同样适用）。"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# 等待旧进程退出（最多 60 秒，避免新进程端口占用）
for _ in range(60):
    if not _process_alive({old_pid}):
        break
    time.sleep(1)

kwargs = {{
    'cwd': {app_root!r},
    'env': os.environ.copy(),  # 继承原进程环境（含 uv/虚拟环境变量）
    'stdin': subprocess.DEVNULL,
    'stdout': subprocess.DEVNULL,
    'stderr': subprocess.DEVNULL,
    'close_fds': True,
}}
if sys.platform == 'win32':
    # DETACHED_PROCESS: 脱离会话独立运行，不弹出窗口
    kwargs['creationflags'] = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
        | 0x00000004
    )
else:
    kwargs['preexec_fn'] = os.setsid

subprocess.Popen([{python_exe!r}, {app_script!r}], **kwargs)

# 自清理
try:
    os.remove(os.path.abspath(__file__))
except OSError:
    pass
'''


def _write_restart_script():
    """写入独立重启辅助脚本，返回脚本路径。

    使用纯 Python 实现（而非 bat/sh），避免 Windows 下 cmd 编码、
    tasklist 解析、短路径等问题；同时继承原进程完整环境变量，
    保证 uv / 虚拟环境等任意启动方式下都能正确拉起新进程。
    """
    pid = os.getpid()
    python_exe = sys.executable or sys.argv[0]
    app_script = os.path.join(APP_ROOT, 'app.py')

    content = _RESTART_TEMPLATE.format(
        old_pid=pid,
        python_exe=python_exe,
        app_script=app_script,
        app_root=APP_ROOT,
    )

    path = os.path.join(tempfile.gettempdir(), f'bhxz_restart_{pid}.py')
    try:
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        return path
    except Exception as e:
        _add_event('log', {'message': f'  ✗ 写入重启脚本失败: {e}'})
        return None


def _launch_restart_script(restart_script):
    """启动重启辅助脚本（独立进程组，不依赖当前进程存活）。"""
    python_exe = sys.executable or sys.argv[0]
    popen_kwargs = {
        'cwd': APP_ROOT,
        'close_fds': True,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
        'stdin': subprocess.DEVNULL,
    }
    if sys.platform == 'win32':
        popen_kwargs['creationflags'] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | 0x00000004  # DETACHED_PROCESS
        )
    else:
        popen_kwargs['preexec_fn'] = os.setsid
    subprocess.Popen([python_exe, restart_script], **popen_kwargs)


def _direct_restart():
    """直接启动新进程（兜底方案，当重启脚本写入失败时使用）。"""
    python_exe = sys.executable or sys.argv[0]
    script = os.path.join(APP_ROOT, 'app.py')
    try:
        kwargs = {
            'cwd': APP_ROOT,
            'close_fds': True,
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'stdin': subprocess.DEVNULL,
        }
        if sys.platform == 'win32':
            kwargs['creationflags'] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
                | 0x00000004  # DETACHED_PROCESS
            )
        else:
            kwargs['preexec_fn'] = os.setsid
        subprocess.Popen([python_exe, script], **kwargs)
        _add_event('log', {'message': '✓ 新进程已启动'})
    except Exception as e:
        _add_event('log', {'message': f'✗ 直接启动新进程失败: {e}'})


def _shutdown_current_process():
    """关闭当前进程。"""
    _add_event('log', {'message': '正在关闭旧服务器进程...'})
    if sys.platform == 'win32':
        import signal
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass
    sys.exit(0)