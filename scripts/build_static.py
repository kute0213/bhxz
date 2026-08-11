#!/usr/bin/env python3
"""
静态资源构建脚本：下载所有外部 CDN 资源到本地，生成静态 CSS/JS 文件。
每次更新后自动运行，确保网站不依赖外部 CDN 加载，提升页面响应速度。

使用方式：
    python scripts/build_static.py

运行后会生成：
    static/lib/highlight/     - Highlight.js 代码高亮
    static/lib/lucide/        - Lucide 图标库
    static/lib/marked/        - Marked.js Markdown 渲染
    static/lib/fonts/         - Google Fonts 字体文件（Noto Sans SC + JetBrains Mono）
    static/lib/monaco/        - Monaco Editor（仅当 npm 可用时）
"""

import os
import sys
import re
import json
import glob
import shutil
import tarfile
import subprocess
import time
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
LIB_DIR = os.path.join(STATIC_DIR, 'lib')

DOWNLOAD_TIMEOUT = 30


# ---------------------------------------------------------------------------
# SSL / HTTP 工具
# ---------------------------------------------------------------------------

def _create_ssl_context():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
    def http_error_302(self, req, fp, code, msg, headers):
        return fp
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _make_opener():
    ctx = _create_ssl_context()
    return build_opener(NoRedirectHandler, HTTPSHandler(context=ctx))


def _urlretrieve(url, dest_path, desc=''):
    """下载 URL 到本地文件，返回是否成功。"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    opener = _make_opener()
    try:
        req = Request(url, method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; BuildScript)')
        resp = opener.open(req, timeout=DOWNLOAD_TIMEOUT)
        with open(dest_path, 'wb') as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
        if desc:
            print(f'  ✓ {desc}')
        return True
    except Exception as e:
        if desc:
            print(f'  ✗ {desc}: {type(e).__name__}: {str(e)[:60]}')
        return False


def _download_with_redirect(url, dest_path, desc=''):
    """下载 URL（跟随重定向）到本地文件。"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        ctx = _create_ssl_context()
        req = Request(url, method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; BuildScript)')
        resp = urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=ctx)
        with open(dest_path, 'wb') as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
        if desc:
            print(f'  ✓ {desc}')
        return True
    except Exception as e:
        if desc:
            print(f'  ✗ {desc}: {type(e).__name__}: {str(e)[:60]}')
        return False


# ---------------------------------------------------------------------------
# 1. Highlight.js
# ---------------------------------------------------------------------------

HIGHLIGHT_VERSION = '11.9.0'
HIGHLIGHT_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js'

HIGHLIGHT_FILES = [
    ('styles/github-dark.min.css', 'github-dark.min.css'),
    ('highlight.min.js', 'highlight.min.js'),
    ('languages/python.min.js', 'languages/python.min.js'),
    ('languages/bash.min.js', 'languages/bash.min.js'),
    ('languages/json.min.js', 'languages/json.min.js'),
    ('languages/yaml.min.js', 'languages/yaml.min.js'),
    ('languages/sql.min.js', 'languages/sql.min.js'),
    ('languages/javascript.min.js', 'languages/javascript.min.js'),
    ('languages/css.min.js', 'languages/css.min.js'),
]


def download_highlight():
    """下载 Highlight.js 所有需要的文件。"""
    print('\n=== Highlight.js ===')
    lib_dir = os.path.join(LIB_DIR, 'highlight')
    os.makedirs(os.path.join(lib_dir, 'languages'), exist_ok=True)

    for src_path, dest_name in HIGHLIGHT_FILES:
        url = f'{HIGHLIGHT_BASE}/{HIGHLIGHT_VERSION}/{src_path}'
        dest = os.path.join(lib_dir, dest_name)
        _urlretrieve(url, dest, f'highlight.js/{dest_name}')


# ---------------------------------------------------------------------------
# 2. Lucide Icons
# ---------------------------------------------------------------------------

LUCIDE_URL = 'https://unpkg.com/lucide@latest'


def download_lucide():
    """下载 Lucide 图标库。"""
    print('\n=== Lucide Icons ===')
    lib_dir = os.path.join(LIB_DIR, 'lucide')
    os.makedirs(lib_dir, exist_ok=True)

    # 先获取最新版本号
    try:
        ctx = _create_ssl_context()
        req = Request('https://unpkg.com/lucide/package.json', method='GET')
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=ctx)
        pkg = json.loads(resp.read().decode('utf-8'))
        version = pkg.get('version', 'latest')
        print(f'  Lucide 版本: {version}')
    except Exception:
        version = '0.468.0'  # 已知稳定版本

    # 下载 lucide.min.js (UMD bundle)
    url = f'https://unpkg.com/lucide@{version}/dist/umd/lucide.min.js'
    dest = os.path.join(lib_dir, 'lucide.min.js')
    success = _download_with_redirect(url, dest, 'lucide.min.js')

    if not success:
        # 备选：使用最新版
        _download_with_redirect(
            'https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js',
            dest, 'lucide.min.js (fallback)'
        )


# ---------------------------------------------------------------------------
# 3. Marked.js
# ---------------------------------------------------------------------------

MARKED_URL = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js'


def download_marked():
    """下载 Marked.js Markdown 渲染库。"""
    print('\n=== Marked.js ===')
    lib_dir = os.path.join(LIB_DIR, 'marked')
    os.makedirs(lib_dir, exist_ok=True)

    dest = os.path.join(lib_dir, 'marked.min.js')
    _download_with_redirect(MARKED_URL, dest, 'marked.min.js')


# ---------------------------------------------------------------------------
# 4. 字体处理
# ---------------------------------------------------------------------------
# 注意：Noto Sans SC（CJK 字体）在 Google Fonts 中被拆分为大量
# unicode-range 子集（~50+ 文件/字重），下载全部子集不现实。
# 改用系统字体栈，各平台已有预装中文字体，零下载、零延迟。
#
# JetBrains Mono 从 GitHub Releases 下载完整 woff2 文件。

JETBRAINS_MONO_VERSION = '2.304'
JETBRAINS_MONO_URL = (
    f'https://github.com/JetBrains/JetBrainsMono/releases/download/v{JETBRAINS_MONO_VERSION}/'
    'JetBrainsMono-2.304.zip'
)


def download_fonts():
    """生成字体 CSS（使用系统字体栈），下载 JetBrains Mono 编程字体。"""
    print('\n=== 字体 ===')

    fonts_dir = os.path.join(LIB_DIR, 'fonts')
    os.makedirs(fonts_dir, exist_ok=True)

    # ---- 生成 fonts.css：使用系统字体栈 ----
    # 各平台中文字体:
    #   Windows: Microsoft YaHei, SimHei
    #   macOS: PingFang SC, Hiragino Sans GB
    #   Linux: Noto Sans CJK SC, WenQuanYi Micro Hei
    # 英文字体: -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial
    css_lines = [
        '/*',
        ' * 自动生成的字体定义 — 由 scripts/build_static.py 生成',
        ' *',
        ' * 使用系统字体栈，无需下载任何字体文件：',
        ' *   - Windows: Microsoft YaHei, SimHei',
        ' *   - macOS:   PingFang SC, Hiragino Sans GB',
        ' *   - Linux:   Noto Sans CJK SC, WenQuanYi Micro Hei',
        ' *',
        ' * JetBrains Mono 用于代码编辑器，下载自 GitHub Releases。',
        ' */',
        '',
        '.font-system {',
        '  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",',
        '               "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC",',
        '               "WenQuanYi Micro Hei", "Helvetica Neue", Arial, sans-serif;',
        '}',
        '',
        'body, .font-body {',
        '  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",',
        '               "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC",',
        '               "WenQuanYi Micro Hei", "Helvetica Neue", Arial, sans-serif;',
        '}',
        '',
    ]

    # ---- 下载 JetBrains Mono ----
    import zipfile

    zip_path = os.path.join(fonts_dir, 'JetBrainsMono.zip')
    print(f'  正在下载 JetBrains Mono v{JETBRAINS_MONO_VERSION}...')
    success = _download_with_redirect(JETBRAINS_MONO_URL, zip_path, 'JetBrainsMono.zip')

    if success:
        try:
            # 解压 woff2 文件
            with zipfile.ZipFile(zip_path, 'r') as zf:
                woff2_files = [f for f in zf.namelist() if 'woff2' in f and f.endswith('.woff2')]
                extracted = 0
                for name in woff2_files:
                    basename = os.path.basename(name)
                    if not basename:
                        continue
                    dest = os.path.join(fonts_dir, basename)
                    with zf.open(name) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())
                    extracted += 1
                print(f'  ✓ 解压 {extracted} 个 JetBrains Mono woff2 文件')

                # 添加 @font-face 到 fonts.css
                css_lines.append('/* JetBrains Mono (本地) */')
                css_lines.append('')
                imported = 0
                for name in woff2_files:
                    basename = os.path.basename(name)
                    if not basename:
                        continue
                    # 从文件名解析字重和样式
                    # 例如: JetBrainsMono-Bold.woff2, JetBrainsMono-MediumItalic.woff2
                    stem = basename.replace('.woff2', '')
                    parts = stem.split('-')
                    weight_map = {
                        'ExtraLight': '200', 'Light': '300', 'Regular': '400',
                        'Medium': '500', 'SemiBold': '600', 'Bold': '700',
                        'ExtraBold': '800',
                    }
                    style = 'normal'
                    w = '400'
                    if len(parts) > 1:
                        w_name = parts[1]
                        if 'Italic' in w_name:
                            style = 'italic'
                            w_name = w_name.replace('Italic', '')
                        w = weight_map.get(w_name, '400')

                    css_lines.append(f"@font-face {{")
                    css_lines.append(f"  font-family: 'JetBrains Mono';")
                    css_lines.append(f"  font-style: {style};")
                    css_lines.append(f"  font-weight: {w};")
                    css_lines.append(f"  font-display: swap;")
                    css_lines.append(f"  src: url('/static/lib/fonts/{basename}') format('woff2');")
                    css_lines.append('}')
                    css_lines.append('')
                    imported += 1

                if imported:
                    print(f'  ✓ 添加 {imported} 个 JetBrains Mono @font-face 定义')

        except Exception as e:
            print(f'  ✗ 解压 JetBrains Mono 失败: {e}')
        finally:
            # 删除 zip 文件
            try:
                os.remove(zip_path)
            except Exception:
                pass
    else:
        print('  ⚠ JetBrains Mono 下载失败，使用系统等宽字体')
        css_lines.append('/* JetBrains Mono 下载失败，使用系统字体 */')
        css_lines.append('')

    # 写入 fonts.css
    fonts_css_path = os.path.join(fonts_dir, 'fonts.css')
    with open(fonts_css_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(css_lines))
    print(f'  ✓ 生成 fonts.css')


# ---------------------------------------------------------------------------
# 5. Monaco Editor
# ---------------------------------------------------------------------------

MONACO_VERSION = '0.45.0'


def download_monaco():
    """使用 npm 下载 Monaco Editor 并复制到 static/lib/monaco。"""
    print('\n=== Monaco Editor ===')

    # 检查 npm 是否可用
    npm_path = shutil.which('npm')
    if not npm_path:
        print('  ⚠ npm 不可用，跳过 Monaco Editor 下载')
        print('  提示: Monaco Editor 仍使用 CDN 加载')
        return

    # 用 npm pack 下载 Monaco 包
    work_dir = os.path.join(LIB_DIR, '.monaco_tmp')
    os.makedirs(work_dir, exist_ok=True)

    target_dir = os.path.join(LIB_DIR, 'monaco', 'vs')
    os.makedirs(target_dir, exist_ok=True)

    try:
        # 使用 npm pack 获取包
        print('  正在下载 monaco-editor 包...')
        result = subprocess.run(
            [npm_path, 'pack', f'monaco-editor@{MONACO_VERSION}'],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f'  ✗ npm pack 失败: {result.stderr[:200]}')
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        # 找到 .tgz 文件
        tgz_files = glob.glob(os.path.join(work_dir, '*.tgz'))
        if not tgz_files:
            print('  ✗ 未找到 .tgz 文件')
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        tgz_path = tgz_files[0]
        print(f'  下载完成: {os.path.basename(tgz_path)}')

        # 解压
        print('  正在解压...')
        extract_dir = os.path.join(work_dir, 'extracted')
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(tgz_path, 'r:gz') as tar:
            tar.extractall(extract_dir)

        # 复制 min/vs 目录到 static/lib/monaco/vs
        package_dir = os.path.join(extract_dir, 'package')
        src_vs = os.path.join(package_dir, 'min', 'vs')
        if os.path.isdir(src_vs):
            # 先删除旧的 vs 目录（如果存在）
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            shutil.copytree(src_vs, target_dir)
            size_mb = 0
            for dirpath, dirnames, filenames in os.walk(target_dir):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    try:
                        size_mb += os.path.getsize(fp)
                    except Exception:
                        pass
            print(f'  ✓ Monaco Editor 已复制到 static/lib/monaco/ ({size_mb / 1024 / 1024:.1f} MB)')
        else:
            print(f'  ✗ 未找到 min/vs 目录: {src_vs}')

    except subprocess.TimeoutExpired:
        print('  ✗ npm pack 超时（120s）')
    except Exception as e:
        print(f'  ✗ 下载 Monaco Editor 失败: {e}')
    finally:
        # 清理临时文件
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 6. 生成静态资源版本文件
# ---------------------------------------------------------------------------

def generate_version_file():
    """生成 lib-version.json，记录构建时间和版本，用于模板缓存刷新。"""
    version = {
        'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'highlight_version': HIGHLIGHT_VERSION,
        'monaco_version': MONACO_VERSION,
    }
    dest = os.path.join(LIB_DIR, 'lib-version.json')
    with open(dest, 'w') as f:
        json.dump(version, f, ensure_ascii=False, indent=2)
    print(f'\n  ✓ 生成 lib-version.json')


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    print('=' * 60)
    print('  静态资源构建脚本')
    print(f'  项目根目录: {PROJECT_ROOT}')
    print(f'  输出目录: {LIB_DIR}')
    print('=' * 60)

    # 确保 lib 目录存在
    os.makedirs(LIB_DIR, exist_ok=True)

    # 1. Highlight.js
    download_highlight()

    # 2. Lucide Icons
    download_lucide()

    # 3. Marked.js
    download_marked()

    # 4. Google Fonts
    download_fonts()

    # 5. Monaco Editor (可选，需要 npm)
    download_monaco()

    # 6. 版本文件
    generate_version_file()

    # 统计
    total_size = 0
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(LIB_DIR):
        # 跳过临时目录
        if '.monaco_tmp' in dirpath.split(os.sep):
            continue
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                total_size += os.path.getsize(fp)
                file_count += 1
            except Exception:
                pass

    print(f'\n{"=" * 60}')
    print(f'  构建完成！')
    print(f'  文件数: {file_count}')
    print(f'  总大小: {total_size / 1024 / 1024:.1f} MB')
    print(f'  输出目录: {LIB_DIR}')
    print(f'  {"=" * 60}')
    print(f'  提示: 如果 Monaco Editor 下载失败，')
    print(f'        网站仍使用 CDN 加载 Monaco，其他资源已全部本地化。')
    print(f'  {"=" * 60}')


if __name__ == '__main__':
    main()