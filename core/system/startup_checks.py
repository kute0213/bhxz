"""服务器启动健康检查 —— 每次启动自动运行，幂等自愈。

检查项：
1. 模块导入完整性：扫描项目模块并尝试导入，尽早发现导入错误
2. 数据库完整性：检查所有表是否存在，缺失时自动创建
3. 文件结构完整性：检查必需目录是否存在，缺失时自动创建
4. 配置完整性：检查关键系统设置是否存在，缺失时自动写入默认值
5. Uploads 目录结构：确保 uploads 分类子目录存在

原则：
- 只创建不删除
- 所有修复操作都是幂等的
- 检查失败不阻塞启动，仅记录警告
"""

import os
import sys
import shutil
import importlib

from core.system.logger import log


# 已废弃目录：结构重构后可能由旧版本残留。
# 网站的在线更新机制是「覆盖式」（见 update.py），不会删除上游已移除的文件，
# 这些旧模块会引用已删除的符号（如 record_spam），导致「模块导入失败」误报，
# 因此启动时统一清理（幂等，目录不存在时静默）。
_OBSOLETE_DIRS = [
    'routes/firewall',  # 防火墙已完整下沉 services/firewall/，路由仅保留 routes/admin/firewall
]


def _remove_obsolete_dirs(app_root: str):
    """清理旧版本残留的废弃目录（在模块导入检查之前执行）。"""
    for rel in _OBSOLETE_DIRS:
        full = os.path.join(app_root, rel)
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
            log('INFO', 'Startup', f'  - 清理废弃目录: {rel}')


def run_startup_checks(app_root: str):
    """运行所有启动检查。"""
    log('INFO', 'Startup', '╔══════════════════════════════════════╗')
    log('INFO', 'Startup', '║     开始服务器健康检查...            ║')
    log('INFO', 'Startup', '╚══════════════════════════════════════╝')

    _remove_obsolete_dirs(app_root)
    _check_module_imports()
    _check_database()
    _check_directories(app_root)
    _check_config()
    _check_uploads_structure(app_root)

    log('INFO', 'Startup', '╔══════════════════════════════════════╗')
    log('INFO', 'Startup', '║     服务器健康检查完成                ║')
    log('INFO', 'Startup', '╚══════════════════════════════════════╝')


# ---------------------------------------------------------------------------
# 1. 模块导入完整性检查
# ---------------------------------------------------------------------------

# 需要检查的项目顶层包名
_PROJECT_PACKAGES = ['core', 'routes', 'services', 'models', 'forms']


def _check_module_imports():
    """扫描所有项目模块并尝试导入，检测导入错误。

    不阻塞启动，仅记录警告。Windows 下可能因包名与标准库冲突（大小写不敏感）
    或相对导入路径错误导致导入失败，此检查确保在开发阶段尽早发现。
    """
    log('INFO', 'Startup', '[1/5] 检查模块导入完整性...')

    failures = []
    for pkg_name in _PROJECT_PACKAGES:
        pkg_path = os.path.join(os.getcwd(), pkg_name)
        if not os.path.isdir(pkg_path):
            continue

        for root, dirs, files in os.walk(pkg_path):
            if '__pycache__' in root:
                continue
            if '__init__.py' not in files:
                continue

            rel = os.path.relpath(root, os.getcwd())
            mod_name = rel.replace(os.sep, '.')

            if mod_name in sys.modules:
                continue

            try:
                importlib.import_module(mod_name)
            except Exception as e:
                failures.append((mod_name, str(e)))
                continue

            # 也检查子模块
            for f in files:
                if f.endswith('.py') and f != '__init__.py':
                    sub_mod = mod_name + '.' + f[:-3]
                    if sub_mod in sys.modules:
                        continue
                    try:
                        importlib.import_module(sub_mod)
                    except Exception as e:
                        failures.append((sub_mod, str(e)))

    if not failures:
        log('INFO', 'Startup', '  ✓ 所有模块导入正常')
    else:
        log('WARNING', 'Startup', f'  ! {len(failures)} 个模块导入失败:')
        for mod, err in failures:
            log('WARNING', 'Startup', f'    - {mod}: {err}')


# ---------------------------------------------------------------------------
# 2. 数据库完整性检查
# ---------------------------------------------------------------------------

def _check_database():
    """检查数据库完整性。

    通过 init_db() 自动创建缺失的表和列，这是幂等操作。
    同时确认数据库文件可正常打开和关闭。
    """
    log('INFO', 'Startup', '[2/5] 检查数据库完整性...')
    try:
        from core.db.schema import init_db
        init_db()
        log('INFO', 'Startup', '  ✓ 数据库结构完整')
    except Exception as e:
        log('ERROR', 'Startup', f'  ✗ 数据库检查失败: {e}')


# ---------------------------------------------------------------------------
# 3. 文件结构完整性检查
# ---------------------------------------------------------------------------

_REQUIRED_DIRS = [
    'uploads',
    'uploads/sitemap',
    'uploads/backgrounds',
    'logs',
    'scripts/build',
]


def _check_directories(app_root: str):
    """检查必需目录是否存在，缺失时自动创建。

    只创建不删除。
    """
    log('INFO', 'Startup', '[3/5] 检查文件结构完整性...')
    created = 0
    for rel_path in _REQUIRED_DIRS:
        full_path = os.path.join(app_root, rel_path)
        if not os.path.isdir(full_path):
            try:
                os.makedirs(full_path, exist_ok=True)
                log('INFO', 'Startup', f'  + 创建目录: {rel_path}')
                created += 1
            except Exception as e:
                log('WARNING', 'Startup', f'  ! 创建目录失败 {rel_path}: {e}')

    if created == 0:
        log('INFO', 'Startup', '  ✓ 所有必需目录已存在')
    else:
        log('INFO', 'Startup', f'  ✓ 已创建 {created} 个缺失目录')


# ---------------------------------------------------------------------------
# 4. 配置完整性检查
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    'SITE_NAME': '滨海小镇',
    'SITE_DESCRIPTION': '一个 Minecraft 服务器',
    'SITE_URL': '',
    'ENABLE_REGISTER': '1',
    'RCON_HOST': '127.0.0.1',
    'RCON_PORT': '25575',
    'RCON_PASSWORD': '',
    'SESSION_LIFETIME': '86400',
    'MAX_CONTENT_LENGTH': '16777216',
    'UPDATE_EXCLUDED_FILES': 'db,backups,uploads,.env,__pycache__',
    'GITHUB_PROXIES': '',
    'BUILD_STATIC_ON_UPDATE': '0',
    'MAIL_SERVER': '',
    'MAIL_PORT': '587',
    'MAIL_USE_TLS': '1',
    'MAIL_USERNAME': '',
    'MAIL_PASSWORD': '',
    'MAIL_DEFAULT_SENDER': '',
}


def _check_config():
    """检查关键系统设置是否存在，缺失时自动写入默认值。

    只补充缺失项，不修改已有值。判断依据是数据库是否存在该键，
    空字符串是合法值（如留空的 MAIL_* / GITHUB_PROXIES），不算缺失。
    """
    log('INFO', 'Startup', '[4/5] 检查系统配置完整性...')
    try:
        from services.settings_manager import get_all_settings, set_setting
        existing_keys = {item['key'] for item in get_all_settings()}
        added = 0
        for key, default_value in _DEFAULT_SETTINGS.items():
            if key in existing_keys:
                continue
            try:
                set_setting(key, default_value)
                log('INFO', 'Startup', f'  + 添加配置: {key}')
                added += 1
            except Exception as e:
                log('WARNING', 'Startup', f'  ! 检查配置 {key} 失败: {e}')

        if added == 0:
            log('INFO', 'Startup', '  ✓ 所有系统配置已存在')
        else:
            log('INFO', 'Startup', f'  ✓ 已添加 {added} 个缺失配置项')
    except Exception as e:
        log('WARNING', 'Startup', f'  ! 配置检查失败: {e}')


# ---------------------------------------------------------------------------
# 5. Uploads 目录结构检查
# ---------------------------------------------------------------------------

def _check_uploads_structure(app_root: str):
    """检查 uploads 目录下的文件结构是否合理。

    不移动不删除文件，仅确保子目录存在。
    """
    log('INFO', 'Startup', '[5/5] 检查 uploads 目录结构...')
    uploads_dir = os.path.join(app_root, 'uploads')
    if not os.path.isdir(uploads_dir):
        log('INFO', 'Startup', '  ✓ uploads 目录不存在，无需检查')
        return

    # 确保分类子目录存在
    subdirs = ['sitemap', 'backgrounds']
    created = 0
    for sub in subdirs:
        sub_path = os.path.join(uploads_dir, sub)
        if not os.path.isdir(sub_path):
            try:
                os.makedirs(sub_path, exist_ok=True)
                log('INFO', 'Startup', f'  + 创建 uploads/{sub} 目录')
                created += 1
            except Exception as e:
                log('WARNING', 'Startup', f'  ! 创建 uploads/{sub} 失败: {e}')

    if created == 0:
        log('INFO', 'Startup', '  ✓ uploads 子目录结构完整')
    else:
        log('INFO', 'Startup', f'  ✓ 已创建 {created} 个 uploads 子目录')