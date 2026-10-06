#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滨海小镇 - 一键更新脚本（跨平台 · 纯下载覆盖）。

设计要点：
  - **纯 Python 全平台兼容**：仅依赖标准库（urllib / zipfile / threading），
    Windows / macOS / Linux 双击或 `python update.py` 均可直接运行。
  - **只走下载覆盖**：不使用 git，直接把 GitHub 最新源码 ZIP 解压后覆盖到项目，
    保留数据库、上传文件、备份、`.env` 等运行期数据。
  - **自动清理已删除文件**：覆盖只会新增/覆盖，随后按新版清单删除「GitHub 上已
    删除」的文件与目录；`uploads/` 等运行期数据在保护名单中，强制跳过、绝不删除。
  - **多线程同时测速**：所有镜像同时发起探测，单个镜像 2 秒超时，
    整个测速环节最大 2 秒（用屏障同步起跑 + 统一截止时间收敛）。
  - **镜像路径正确拼接**：每个镜像声明自己的 URL 模板（前缀型代理 / 主机替换型 /
    官方直连），统一用 `{repo}` / `{branch}` 占位符拼接，杜绝路径拼错。
  - **无需确认**：启动即开始，不做任何交互式询问。

用法:
    python update.py                 # 直接更新（无确认）
    python update.py --branch dev    # 指定分支（默认 main，失败自动回退 master）
"""

import os
import sys
import time
import shutil
import zipfile
import tempfile
import threading
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'kute0213/bhxz'
DEFAULT_BRANCH = 'main'
FALLBACK_BRANCHES = ['main', 'master']
REQUIREMENTS_FILE = os.path.join(PROJECT_ROOT, 'requirements.txt')

USER_AGENT = 'Mozilla/5.0 (compatible; BHXZ-Updater/2.0)'

# 测速：单个镜像探测超时 & 整个测速阶段总预算（秒）
MIRROR_TIMEOUT = 2.0
SPEEDTEST_BUDGET = 2.0
# 探测时读取的字节数（用于计算下载速度，避免拉取整个压缩包）
PROBE_BYTES = 128 * 1024
# 正式下载时的单次 socket 超时（大文件较宽松）
DOWNLOAD_TIMEOUT = 120

# 覆盖时保留的根级内容（运行期数据 / 本地配置，绝不覆盖）
EXCLUDE_ROOT = {
    'db', 'backups', 'uploads', 'ssl', 'logs',
    '.env', '.env.local', '.git',
    '.venv', 'venv', 'env', 'node_modules', '.trae',
    'release', '__pycache__', '.pytest_cache',
}
# 覆盖时跳过的不需要的文件 / 目录名（任意层级）
SKIP_NAMES = {'__pycache__', '.pytest_cache', '.DS_Store', 'Thumbs.db'}
SKIP_SUFFIX = (
    '.pyc', '.pyo', '.zip', '.log', '.so', '.swp', '.swo',
    '.db', '.db-journal', '.db-wal', '.db-shm',
    '.sqlite', '.sqlite3', '.duckdb', '.duckdb.wal', '.duckdb.bak',
)

# 清理「GitHub 上已删除的文件」时**绝不删除**的路径（相对项目根，posix 风格）。
# 这些都是运行期数据或本地生成物（与 .gitignore 的忽略项保持一致），
# 它们本来就不在仓库里，不能被当成「新版已删除」而误删。
PROTECTED_PATHS = {
    # 用户数据：强制跳过，任何情况下都不删除
    'uploads',
    # 运行期数据 / 本地配置 / 生成物（见 .gitignore）
    'backups', 'logs', 'ssl', 'db', 'release', 'dist', 'build',
    '.git', '.venv', 'venv', 'env', 'ENV', '.env', '.env.local',
    '.trae', '.trae-html-share-packages', '.vscode', '.idea',
    # 本地下载的构建产物（.gitignore 排除，服务器上必须保留）
    'templates/static/lib/monaco',
    # 运行期下载的 ffmpeg 可执行文件
    'scripts/ffmpeg',
    'scripts/build/node_modules',
}
# 任意层级都不删除的目录 / 文件名
PROTECTED_NAMES = {'__pycache__', '.pytest_cache', 'node_modules', '.DS_Store', 'Thumbs.db'}

# ── 镜像源（URL 模板） ────────────────────────────────────────────────
# 官方归档地址：github.com 会 302 到 codeload.github.com
_GH_ARCHIVE = 'https://github.com/{repo}/archive/refs/heads/{branch}.zip'
_GH_CODELOAD = 'https://codeload.github.com/{repo}/zip/refs/heads/{branch}'

# 前缀型代理：在其后拼接完整 GitHub 归档地址
_PREFIX_PROXIES = [
    'https://ghproxy.net/',
    'https://ghfast.top/',
    'https://gh-proxy.com/',
    'https://ghproxy.cc/',
    'https://mirror.ghproxy.com/',
    'https://github.moeyy.xyz/',
    'https://gh.llkk.cc/',
    'https://gh.ddlc.top/',
    'https://hub.gitmirror.com/',
    'https://ghproxy.1888866.xyz/',
    'https://slink.ltd/',
    'https://ghps.cc/',
    'https://gh-proxy.net/',
    'https://github.boki.moe/',
    'https://gh.h233.eu.org/',
    'https://ghproxy.imciel.com/',
    'https://gh.jasonzeng.dev/',
    'https://gh-proxy.ygxz.in/',
    'https://gh.xxooo.cf/',
    'https://ghproxy.cfd/',
]

# 主机替换型镜像：直接替换 github.com 主机
_HOST_MIRRORS = [
    'https://kkgithub.com/',
    'https://hub.nuaa.cf/',
]


def build_mirrors():
    """构造镜像列表 [(显示名, URL 模板), ...]。

    模板统一使用 `{repo}` / `{branch}` 占位符，路径拼接规则：
      - 官方直连：`https://github.com/<repo>/archive/refs/heads/<branch>.zip`
      - 前缀代理：`<代理前缀>https://github.com/<repo>/archive/refs/heads/<branch>.zip`
      - 主机替换：`https://<镜像域名>/<repo>/archive/refs/heads/<branch>.zip`
    """
    mirrors = [('GitHub 官方', _GH_ARCHIVE), ('GitHub codeload', _GH_CODELOAD)]
    for prefix in _PREFIX_PROXIES:
        name = prefix.rstrip('/').replace('https://', '')
        mirrors.append((name, prefix + _GH_ARCHIVE))
    for host in _HOST_MIRRORS:
        name = host.rstrip('/').replace('https://', '')
        mirrors.append((name, host + '{repo}/archive/refs/heads/{branch}.zip'))
    return mirrors


def build_url(template, branch):
    """按模板拼接下载 URL（正确转义 repo / branch）。"""
    return template.format(
        repo=GITHUB_REPO,
        branch=urllib.parse.quote(branch, safe=''),
    )


# ── 终端颜色（Windows 兼容） ──────────────────────────────────────────
def _enable_ansi():
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


_enable_ansi()
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
CYAN = '\033[0;36m'
RED = '\033[0;31m'
NC = '\033[0m'


def log(msg, color=NC):
    """带时间戳的日志输出。"""
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    if color and sys.stdout.isatty():
        line = f'{color}{line}{NC}'
    print(line)
    sys.stdout.flush()


# ── 多线程测速 ────────────────────────────────────────────────────────
def _probe(index, mirror, barrier, results, branch):
    """探测单个镜像：下载速度 + 内容合法性（是否 PK 开头的 ZIP）。"""
    try:
        barrier.wait(timeout=SPEEDTEST_BUDGET)
    except Exception:
        return

    name, template = mirror
    url = build_url(template, branch)
    try:
        start = time.monotonic()
        req = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Range': f'bytes=0-{PROBE_BYTES - 1}',
        })
        resp = urllib.request.urlopen(req, timeout=MIRROR_TIMEOUT)
        try:
            data = resp.read(PROBE_BYTES)
        finally:
            resp.close()
        elapsed = max(time.monotonic() - start, 1e-6)
        if not data:
            results[index] = None
            return
        results[index] = {
            'name': name,
            'template': template,               # 保留模板，便于切换分支时重建 URL
            'url': url,
            'bytes': len(data),
            'elapsed': elapsed,
            'speed': len(data) / elapsed,       # bytes/s
            'is_zip': data[:2] == b'PK',        # 是否为合法 ZIP 内容
        }
    except Exception:
        results[index] = None


def speedtest(branch):
    """并发探测全部镜像，返回按速度降序排列的可用镜像列表。

    整个测速环节被限制在 SPEEDTEST_BUDGET 秒内：所有线程经屏障同时起跑，
    主线程按统一截止时间 join，超时线程（守护线程）直接放弃。
    """
    mirrors = build_mirrors()
    log(f'正在同时测速 {len(mirrors)} 个镜像源（超时 {SPEEDTEST_BUDGET:.0f} 秒）...', CYAN)

    barrier = threading.Barrier(len(mirrors))
    results = [None] * len(mirrors)
    threads = []
    start = time.monotonic()

    for i, mirror in enumerate(mirrors):
        t = threading.Thread(
            target=_probe,
            args=(i, mirror, barrier, results, branch),
            daemon=True,
        )
        t.start()
        threads.append(t)

    deadline = start + SPEEDTEST_BUDGET
    for t in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        t.join(remaining)

    used = time.monotonic() - start
    available = [r for r in results if r]
    # 能返回合法 ZIP 的优先，其次按速度降序
    available.sort(key=lambda r: (r['is_zip'], r['speed']), reverse=True)
    log(f'测速完成，用时 {used:.2f} 秒，可用镜像 {len(available)} 个', GREEN if available else RED)
    return available


# ── 下载与解压 ────────────────────────────────────────────────────────
def _print_progress(got, total, speed):
    done = int(got * 20 / total) if total > 0 else 0
    bar = '█' * done + '░' * (20 - done)
    if total > 0:
        text = f'  {bar} {got * 100 // total:3d}%  {got // 1024}KB/{total // 1024}KB  {speed / 1024:.0f}KB/s'
    else:
        text = f'  {bar}  {got // 1024}KB  {speed / 1024:.0f}KB/s'
    sys.stdout.write('\r' + text)
    sys.stdout.flush()


def download_zip(url, dest):
    """下载 ZIP 并做基础校验，返回 (success, error_msg)。"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT)
    except Exception as e:
        return False, f'连接失败: {e}'

    try:
        code = resp.getcode()
        if code != 200:
            return False, f'HTTP {code}'
        total = int(resp.headers.get('Content-Length') or 0)
        got = 0
        started = time.monotonic()
        with open(dest, 'wb') as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                elapsed = max(time.monotonic() - started, 1e-6)
                _print_progress(got, total, got / elapsed)
        sys.stdout.write('\n')
        sys.stdout.flush()
    except Exception as e:
        sys.stdout.write('\n')
        return False, f'下载中断: {e}'
    finally:
        resp.close()

    if got == 0:
        return False, '下载内容为空'

    # ZIP 魔数校验：镜像返回 HTML 错误页时在此拦截
    with open(dest, 'rb') as f:
        if f.read(2) != b'PK':
            return False, '返回内容非 ZIP（镜像可能返回错误页）'

    # 压缩包完整性校验（CRC）
    try:
        with zipfile.ZipFile(dest, 'r') as zf:
            bad = zf.testzip()
        if bad is not None:
            return False, f'压缩包损坏: {bad}'
    except zipfile.BadZipFile as e:
        return False, f'压缩包无法解析: {e}'

    return True, ''


def _find_source_dir(extract_dir):
    """定位解压后的项目根目录（兼容有无外层 `bhxz-<branch>/` 两种结构）。"""
    for entry in os.listdir(extract_dir):
        full = os.path.join(extract_dir, entry)
        if os.path.isdir(full) and os.path.isfile(os.path.join(full, 'app.py')):
            return full
    if os.path.isfile(os.path.join(extract_dir, 'app.py')):
        return extract_dir
    return None


def _skip(name):
    """判断是否跳过该文件 / 目录名。"""
    if name in SKIP_NAMES:
        return True
    if name.lower().endswith(SKIP_SUFFIX):
        return True
    return False


def _merge_copy(src, dst):
    """把 src 目录内容合并覆盖到 dst：同名覆盖，目标多余文件保留。

    采用「合并」而非「删除后重建」，可保留 node_modules、ffmpeg 等运行期产物。
    """
    if not os.path.isdir(dst):
        os.makedirs(dst, exist_ok=True)
    for entry in os.listdir(src):
        if _skip(entry):
            continue
        s = os.path.join(src, entry)
        d = os.path.join(dst, entry)
        if os.path.isdir(s):
            if os.path.exists(d) and not os.path.isdir(d):
                os.remove(d)
            _merge_copy(s, d)
        else:
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
            shutil.copy2(s, d)


def _protected(rel):
    """判断相对路径（posix 风格）是否受保护、绝不参与清理。"""
    if rel in PROTECTED_PATHS:
        return True
    parts = rel.split('/')
    if parts[0] in PROTECTED_PATHS:
        return True
    return parts[-1] in PROTECTED_NAMES


def _has_protected_child(rel):
    """rel 之下是否存在受保护路径（用于避免整目录删除时误删保护内容）。"""
    prefix = rel + '/'
    return any(p.startswith(prefix) for p in PROTECTED_PATHS)


def _rm_path(path):
    """删除文件或目录，返回删除的文件数（失败返回 0）。"""
    try:
        if os.path.isdir(path):
            n = sum(len(files) for _, _, files in os.walk(path))
            shutil.rmtree(path, ignore_errors=True)
            return n
        os.remove(path)
        return 1
    except OSError:
        return 0


def _prune_tree(src_dir, dst_dir, rel=''):
    """递归清理 dst_dir 中「新版 src_dir 已不存在」的文件与目录，返回删除的文件数。

    合并覆盖只会新增/覆盖，无法反映「GitHub 上已删除」，此函数负责补齐：
      - `/uploads` 等运行期数据在 PROTECTED_PATHS 中被强制跳过，绝不触碰
      - 任意层级的 SKIP_NAMES / SKIP_SUFFIX 命中项同样跳过
      - 新版已移除的目录会被整棵删除；但若其下仍有受保护路径，
        则改为递归清理，保证保护内容不被连带删除
    """
    try:
        names = os.listdir(dst_dir)
    except OSError:
        return 0

    removed = 0
    for name in names:
        child_rel = f'{rel}/{name}' if rel else name
        if _skip(name) or _protected(child_rel):
            continue
        d = os.path.join(dst_dir, name)
        s = os.path.join(src_dir, name)
        if os.path.isdir(d):
            if os.path.isdir(s) or _has_protected_child(child_rel):
                # 新版无此目录但目录内有需保护的内容：递归清理，保留保护项
                removed += _prune_tree(s, d, child_rel)
            else:
                removed += _rm_path(d)
        elif not os.path.exists(s):
            removed += _rm_path(d)
    return removed


def apply_update(src_dir):
    """把新代码合并覆盖到项目目录（保留运行期数据），并清理已在 GitHub 删除的文件。"""
    log('正在覆盖项目文件...', CYAN)
    count = 0
    for entry in os.listdir(src_dir):
        if entry in EXCLUDE_ROOT or _skip(entry):
            continue
        s = os.path.join(src_dir, entry)
        d = os.path.join(PROJECT_ROOT, entry)
        if os.path.isdir(s):
            _merge_copy(s, d)
        else:
            shutil.copy2(s, d)
        count += 1
    log(f'覆盖完成，共处理 {count} 项', GREEN)

    # 清理新版已删除的文件（uploads 等运行期数据强制跳过）
    removed = _prune_tree(src_dir, PROJECT_ROOT)
    if removed:
        log(f'已清理 {removed} 个 GitHub 上已被删除的文件', GREEN)
    else:
        log('无过时文件需要清理', GREEN)
    return removed


# ── 依赖安装 ──────────────────────────────────────────────────────────
def install_requirements():
    """安装 / 更新 Python 依赖。"""
    if not os.path.isfile(REQUIREMENTS_FILE):
        return
    log('正在检查 Python 依赖...', CYAN)
    try:
        code = subprocess.call(
            [sys.executable, '-m', 'pip', 'install', '-r', REQUIREMENTS_FILE, '--quiet'],
            cwd=PROJECT_ROOT,
        )
    except Exception:
        code = -1
    if code == 0:
        log('依赖检查完成', GREEN)
    else:
        log('依赖安装存在警告（通常不影响运行）', YELLOW)


# ── 主流程 ────────────────────────────────────────────────────────────
def parse_args(argv):
    """解析参数：--branch <名称> / --yes（兼容旧用法，均无需确认）。"""
    branch = DEFAULT_BRANCH
    for i, arg in enumerate(argv):
        if arg in ('--branch', '-b') and i + 1 < len(argv):
            branch = argv[i + 1]
        elif arg.startswith('--branch='):
            branch = arg.split('=', 1)[1]
    branches = [branch]
    for b in FALLBACK_BRANCHES:
        if b not in branches:
            branches.append(b)
    return branches


def update_via_download(ranked, branches):
    """从测速结果下载并覆盖（逐个镜像 × 逐个分支尝试）。"""
    if not ranked:
        log('无可用镜像源，更新终止', RED)
        return False

    log(f'首选镜像: {ranked[0]["name"]} '
        f'({ranked[0]["speed"] / 1024:.0f}KB/s)', GREEN)
    if len(ranked) > 1:
        backups = ', '.join(r['name'] for r in ranked[1:4])
        log(f'备用镜像: {backups}', YELLOW)

    tmp_dir = tempfile.mkdtemp(prefix='bhxz_update_')
    zip_path = os.path.join(tmp_dir, 'update.zip')
    try:
        for i, item in enumerate(ranked):
            for branch in branches:
                url = build_url(item['template'], branch)
                log(f'尝试下载 [{i + 1}/{len(ranked)}] {item["name"]}（分支 {branch}）', CYAN)
                ok, err = download_zip(url, zip_path)
                if not ok:
                    log(f'  失败: {err}', YELLOW)
                    continue

                extract_dir = os.path.join(tmp_dir, 'extracted')
                if os.path.isdir(extract_dir):
                    shutil.rmtree(extract_dir, ignore_errors=True)
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)

                src_dir = _find_source_dir(extract_dir)
                if not src_dir:
                    log('  解压后未找到项目目录，重试其他镜像', YELLOW)
                    continue

                apply_update(src_dir)
                return True

        log('所有镜像与分支均下载失败，请检查网络后重试', RED)
        return False
    except Exception as e:
        log(f'更新失败: {e}', RED)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    print()
    log('╔══════════════════════════════════════════════╗', CYAN)
    log('║     滨海小镇 - 一键更新（纯下载覆盖）         ║', CYAN)
    log('╚══════════════════════════════════════════════╝', CYAN)
    log(f'项目目录: {PROJECT_ROOT}')
    log(f'仓库: {GITHUB_REPO}')
    print()

    branches = parse_args(sys.argv[1:])

    # 1. 多线程同时测速（整个环节 ≤ 2 秒）
    ranked = speedtest(branches[0])
    if not ranked:
        log('无法连接到任何镜像源，请检查网络后重试', RED)
        return False

    # 2. 下载并覆盖
    if not update_via_download(ranked, branches):
        return False

    # 3. 安装依赖
    print()
    install_requirements()

    print()
    log('╔══════════════════════════════════════════════╗', GREEN)
    log('║     更新完成！                               ║', GREEN)
    log('╚══════════════════════════════════════════════╝', GREEN)
    log('提示: 请手动重启服务器使新代码生效', YELLOW)
    print()
    return True


if __name__ == '__main__':
    try:
        sys.exit(0 if main() else 1)
    except KeyboardInterrupt:
        print()
        log('已取消更新', YELLOW)
        sys.exit(0)
    except Exception as exc:
        log(f'更新失败: {exc}', RED)
        import traceback
        traceback.print_exc()
        sys.exit(1)
