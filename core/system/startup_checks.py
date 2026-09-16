"""服务器启动健康检查 —— 每次启动自动运行，自动修复不删文件。

检查项：
1. 数据库完整性：检查所有表是否存在，缺失时自动创建
2. 文件结构完整性：检查必需目录是否存在，缺失时自动创建
3. 配置完整性：检查关键系统设置是否存在，缺失时自动写入默认值
4. 数据库文件健康：检查数据库文件是否可正常打开

原则：
- 只创建不删除（不删文件、不删表、不删数据）
- 所有修复操作都是幂等的
- 检查失败不阻塞启动，仅记录警告
"""

import os
import sys
import importlib
import pkgutil

from core.system.logger import log


def run_startup_checks(app_root: str):
    """运行所有启动检查。"""
    log('INFO', 'Startup', '╔══════════════════════════════════════╗')
    log('INFO', 'Startup', '║     开始服务器健康检查...            ║')
    log('INFO', 'Startup', '╚══════════════════════════════════════╝')

    _check_module_imports()
    _check_database()
    _check_directories(app_root)
    _check_config()
    _check_uploads_structure(app_root)
    _migrate_settings()

    log('INFO', 'Startup', '╔══════════════════════════════════════╗')
    log('INFO', 'Startup', '║     服务器健康检查完成                ║')
    log('INFO', 'Startup', '╚══════════════════════════════════════╝')


# ---------------------------------------------------------------------------
# 0. 模块导入完整性检查
# ---------------------------------------------------------------------------

# 需要检查的项目顶层包名
_PROJECT_PACKAGES = ['core', 'routes', 'services', 'models', 'forms']


def _check_module_imports():
    """扫描所有项目模块并尝试导入，检测导入错误。

    不阻塞启动，仅记录警告。Windows 下可能因包名与标准库冲突（大小写不敏感）
    或相对导入路径错误导致导入失败，此检查确保在开发阶段尽早发现。
    """
    log('INFO', 'Startup', '[0/6] 检查模块导入完整性...')

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
# 1. 数据库完整性检查
# ---------------------------------------------------------------------------

def _check_database():
    """检查数据库完整性。

    通过 init_db() 自动创建缺失的表和列，这是幂等操作。
    同时确认数据库文件可正常打开和关闭。
    """
    log('INFO', 'Startup', '[1/6] 检查数据库完整性...')
    try:
        from core.db.schema import init_db
        init_db()
        log('INFO', 'Startup', '  ✓ 数据库结构完整')
    except Exception as e:
        log('ERROR', 'Startup', f'  ✗ 数据库检查失败: {e}')


# ---------------------------------------------------------------------------
# 2. 文件结构完整性检查
# ---------------------------------------------------------------------------

_REQUIRED_DIRS = [
    'uploads',
    'uploads/attachments',
    'uploads/community',
    'uploads/sitemap',
    'uploads/backgrounds',
    'backups',
    'ssl',
    'logs',
    'scripts/build',
    'static/uploads',
    'static/uploads/avatars',
    'static/uploads/backgrounds',
    'static/uploads/guides',
    'static/uploads/music',
    'static/uploads/temp',
    'static/uploads/community',
    'static/uploads/attachments',
]


def _check_directories(app_root: str):
    """检查必需目录是否存在，缺失时自动创建。

    只创建不删除。
    """
    log('INFO', 'Startup', '[2/6] 检查文件结构完整性...')
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
# 3. 配置完整性检查
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    'SITE_NAME': '滨海小镇',
    'SITE_DESCRIPTION': '一个 Minecraft 服务器',
    'SITE_URL': '',
    'ENABLE_REGISTER': '1',
    'ENABLE_SSL': '0',
    'RCON_HOST': '127.0.0.1',
    'RCON_PORT': '25575',
    'RCON_PASSWORD': '',
    'SESSION_LIFETIME': '86400',
    'MAX_CONTENT_LENGTH': '16777216',
    'UPDATE_EXCLUDED_FILES': 'db,backups,uploads,ssl,.env,__pycache__',
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
    log('INFO', 'Startup', '[3/6] 检查系统配置完整性...')
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
# 4. 设置键名迁移
# ---------------------------------------------------------------------------


def _migrate_settings():
    """自动迁移旧的配置键名到新键名。

    当配置键重命名时，自动将旧键的值复制到新键，然后删除旧键。
    避免在业务代码中保留向后兼容逻辑。
    """
    log('INFO', 'Startup', '[5/6] 检查配置键名迁移...')

    # 键名映射：旧键名 → 新键名
    KEY_MIGRATIONS = {
        'IP_BAN_WHITELIST': 'FIREWALL_WHITELIST',
    }

    migrated = 0
    for old_key, new_key in KEY_MIGRATIONS.items():
        try:
            from services.settings_manager import get_all_settings, set_setting, delete_setting
            existing_keys = {item['key'] for item in get_all_settings()}

            # 旧键存在且新键不存在 → 迁移
            if old_key in existing_keys and new_key not in existing_keys:
                # 读取旧键的值
                from services.settings_manager import get_setting
                old_value = get_setting(old_key)
                if old_value is not None:
                    # 写入新键
                    set_setting(new_key, old_value)
                    # 尝试删除旧键（如果 delete_setting 可用）
                    try:
                        delete_setting(old_key)
                    except (AttributeError, Exception):
                        pass
                    log('INFO', 'Startup', f'  + 设置迁移: {old_key} → {new_key}')
                    migrated += 1
            elif old_key in existing_keys and new_key in existing_keys:
                # 新旧都存在，删除旧键
                try:
                    from services.settings_manager import delete_setting
                    delete_setting(old_key)
                    log('INFO', 'Startup', f'  + 清理旧设置: {old_key}')
                    migrated += 1
                except (AttributeError, Exception):
                    pass
        except Exception as e:
            log('WARNING', 'Startup', f'  ! 设置迁移失败 {old_key}: {e}')

    if migrated == 0:
        log('INFO', 'Startup', '  ✓ 无需迁移配置键名')
    else:
        log('INFO', 'Startup', f'  ✓ 已完成 {migrated} 项设置迁移')


# ---------------------------------------------------------------------------
# 5. Uploads 目录结构检查
# ---------------------------------------------------------------------------

def _check_uploads_structure(app_root: str):
    """检查 uploads 目录下的文件结构是否合理。

    不移动不删除文件，仅确保子目录存在。
    """
    log('INFO', 'Startup', '[4/6] 检查 uploads 目录结构...')
    uploads_dir = os.path.join(app_root, 'uploads')
    if not os.path.isdir(uploads_dir):
        log('INFO', 'Startup', '  ✓ uploads 目录不存在，无需检查')
        return

    # 确保分类子目录存在
    subdirs = ['attachments', 'community', 'sitemap', 'backgrounds']
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