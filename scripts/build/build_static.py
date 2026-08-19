#!/usr/bin/env python3
"""
静态资源构建脚本：下载所有外部 CDN 资源到本地，生成静态 CSS/JS 文件。
每次更新后自动运行，确保网站不依赖外部 CDN 加载，提升页面响应速度。

使用方式：
    python scripts/build/build_static.py

运行后会生成：
    static/lib/lucide/        - Lucide 图标库
    static/lib/marked/        - Marked.js Markdown 渲染
    static/lib/fonts/         - Google Fonts 字体文件（Noto Sans SC + JetBrains Mono）
    static/lib/monaco/        - Monaco Editor 代码编辑器（HTTP 下载，无需 npm）
"""

import os
import json
import shutil
import tarfile
import time
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 从 scripts/build/ 上溯两级得到项目根目录（/workspace）
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
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
            print(f'  [OK] {desc}')
        return True
    except Exception as e:
        if desc:
            print(f'  [FAIL] {desc}: {type(e).__name__}: {str(e)[:60]}')
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
            print(f'  [OK] {desc}')
        return True
    except Exception as e:
        if desc:
            print(f'  [FAIL] {desc}: {type(e).__name__}: {str(e)[:60]}')
        return False


# ---------------------------------------------------------------------------
# 1. Lucide Icons
# ---------------------------------------------------------------------------

LUCIDE_URL = 'https://unpkg.com/lucide@latest'


def download_lucide():
    """下载 Lucide 图标库。"""
    print('\n=== Lucide Icons ===', flush=True)
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
# 2. Marked.js
# ---------------------------------------------------------------------------

MARKED_URL = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js'


def download_marked():
    """下载 Marked.js Markdown 渲染库。"""
    print('\n=== Marked.js ===', flush=True)
    lib_dir = os.path.join(LIB_DIR, 'marked')
    os.makedirs(lib_dir, exist_ok=True)

    dest = os.path.join(lib_dir, 'marked.min.js')
    _download_with_redirect(MARKED_URL, dest, 'marked.min.js')


# ---------------------------------------------------------------------------
# 3. 字体处理
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
    print('\n=== 字体 ===', flush=True)

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
        ' * 自动生成的字体定义 — 由 scripts/build/build_static.py 生成',
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
                print(f'  [OK] 解压 {extracted} 个 JetBrains Mono woff2 文件')

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
                    print(f'  [OK] 添加 {imported} 个 JetBrains Mono @font-face 定义')

        except Exception as e:
            print(f'  [FAIL] 解压 JetBrains Mono 失败: {e}')
        finally:
            # 删除 zip 文件
            try:
                os.remove(zip_path)
            except Exception:
                pass
    else:
        print('  [WARN] JetBrains Mono 下载失败，使用系统等宽字体')
        css_lines.append('/* JetBrains Mono 下载失败，使用系统字体 */')
        css_lines.append('')

    # 写入 fonts.css
    fonts_css_path = os.path.join(fonts_dir, 'fonts.css')
    with open(fonts_css_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(css_lines))
    print(f'  [OK] 生成 fonts.css')


# ---------------------------------------------------------------------------
# 4. Monaco Editor (HTTP 下载，无需 npm)
# ---------------------------------------------------------------------------

MONACO_VERSION = '0.45.0'
MONACO_TGZ_URL = f'https://registry.npmjs.org/monaco-editor/-/monaco-editor-{MONACO_VERSION}.tgz'


def download_monaco():
    """从 npm registry 直接下载 Monaco Editor 压缩包，无需 npm。"""
    print('\n=== Monaco Editor ===', flush=True)

    lib_dir = os.path.join(LIB_DIR, 'monaco')
    target_dir = os.path.join(lib_dir, 'vs')
    os.makedirs(target_dir, exist_ok=True)

    # 下载 .tgz 文件
    tgz_path = os.path.join(lib_dir, f'monaco-editor-{MONACO_VERSION}.tgz')
    print(f'  正在下载 monaco-editor@{MONACO_VERSION}...')
    success = _download_with_redirect(MONACO_TGZ_URL, tgz_path, 'monaco-editor.tgz')

    if not success:
        print('  [FAIL] Monaco Editor 下载失败')
        print('  提示: 网站仍使用 CDN 加载 Monaco')
        # 清理空目录
        try:
            shutil.rmtree(lib_dir, ignore_errors=True)
        except Exception:
            pass
        return

    try:
        # 解压 .tgz
        print('  正在解压...')
        extract_dir = os.path.join(lib_dir, '.extracted')
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(tgz_path, 'r:gz') as tar:
            tar.extractall(extract_dir)

        # 复制 package/min/vs 到目标目录
        src_vs = os.path.join(extract_dir, 'package', 'min', 'vs')
        if os.path.isdir(src_vs):
            # 先删除旧的 vs 目录
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            shutil.copytree(src_vs, target_dir)
            # 计算大小
            size_mb = 0
            for dirpath, dirnames, filenames in os.walk(target_dir):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    try:
                        size_mb += os.path.getsize(fp)
                    except Exception:
                        pass
            print(f'  [OK] Monaco Editor 已复制到 static/lib/monaco/ ({size_mb / 1024 / 1024:.1f} MB)')
        else:
            print(f'  [FAIL] 未找到 min/vs 目录: {src_vs}')

    except Exception as e:
        print(f'  [FAIL] 解压 Monaco Editor 失败: {e}')

    finally:
        # 清理临时文件
        try:
            os.remove(tgz_path)
        except Exception:
            pass
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 4.5 xterm.js 终端模拟器
# ---------------------------------------------------------------------------

XTERM_VERSION = '5.3.0'
XTERM_ADDON_FIT_VERSION = '0.8.0'


def download_xterm():
    """下载 xterm.js 终端模拟器及其 fit 自适应插件。

    实时终端 / 弹窗终端基于 xterm.js 渲染字符网格，替代自制的脆弱的
    ANSI 渲染器，确保回车执行、光标、清屏、换行排版等在浏览器中表现一致。
    """
    print('\n=== xterm.js 终端 ===', flush=True)
    lib_dir = os.path.join(LIB_DIR, 'xterm')
    os.makedirs(lib_dir, exist_ok=True)

    files = [
        (
            f'https://cdn.jsdelivr.net/npm/xterm@{XTERM_VERSION}/lib/xterm.min.js',
            os.path.join(lib_dir, 'xterm.min.js'),
            'xterm.min.js',
        ),
        (
            f'https://cdn.jsdelivr.net/npm/xterm@{XTERM_VERSION}/css/xterm.min.css',
            os.path.join(lib_dir, 'xterm.min.css'),
            'xterm.min.css',
        ),
        (
            f'https://cdn.jsdelivr.net/npm/xterm-addon-fit@{XTERM_ADDON_FIT_VERSION}/lib/xterm-addon-fit.min.js',
            os.path.join(lib_dir, 'addon-fit.min.js'),
            'xterm-addon-fit.min.js',
        ),
    ]
    for url, dest, desc in files:
        _download_with_redirect(url, dest, desc)


# ---------------------------------------------------------------------------
# 5. 生成静态资源版本文件
# ---------------------------------------------------------------------------

def generate_version_file():
    """生成 lib-version.json，记录构建时间和版本，用于模板缓存刷新。"""
    version = {
        'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'monaco_version': MONACO_VERSION,
        'xterm_version': XTERM_VERSION,
    }
    dest = os.path.join(LIB_DIR, 'lib-version.json')
    with open(dest, 'w') as f:
        json.dump(version, f, ensure_ascii=False, indent=2)
    print(f'\n  [OK] 生成 lib-version.json')


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    print('=' * 60, flush=True)
    print('  静态资源构建脚本', flush=True)
    print(f'  项目根目录: {PROJECT_ROOT}', flush=True)
    print(f'  输出目录: {LIB_DIR}', flush=True)
    print('=' * 60, flush=True)

    # 确保 lib 目录存在
    os.makedirs(LIB_DIR, exist_ok=True)

    # 1. Lucide Icons
    download_lucide()

    # 2. Marked.js
    download_marked()

    # 3. Google Fonts
    download_fonts()

    # 4. Monaco Editor（HTTP 下载，无需 npm）
    download_monaco()

    # 4.5 xterm.js 终端模拟器
    download_xterm()

    # 5. 版本文件
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

    print(f'\n{"=" * 60}', flush=True)
    print(f'  构建完成！', flush=True)
    print(f'  文件数: {file_count}', flush=True)
    print(f'  总大小: {total_size / 1024 / 1024:.1f} MB', flush=True)
    print(f'  输出目录: {LIB_DIR}', flush=True)
    print(f'  {"=" * 60}', flush=True)
    print(f'  提示: 如果 Monaco Editor 下载失败，', flush=True)
    print(f'        网站仍使用 CDN 加载 Monaco，其他资源已全部本地化。', flush=True)
    print(f'  {"=" * 60}', flush=True)


if __name__ == '__main__':
    main()