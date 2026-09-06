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

from core.logger import log


def run_startup_checks(app_root: str):
    """运行所有启动检查。"""
    log('INFO', 'Startup', '╔══════════════════════════════════════╗')
    log('INFO', 'Startup', '║     开始服务器健康检查...            ║')
    log('INFO', 'Startup', '╚══════════════════════════════════════╝')

    _check_database()
    _check_directories(app_root)
    _check_config()
    _check_uploads_structure(app_root)

    log('INFO', 'Startup', '╔══════════════════════════════════════╗')
    log('INFO', 'Startup', '║     服务器健康检查完成                ║')
    log('INFO', 'Startup', '╚══════════════════════════════════════╝')


# ---------------------------------------------------------------------------
# 1. 数据库完整性检查
# ---------------------------------------------------------------------------

def _check_database():
    """检查数据库完整性。

    通过 init_db() 自动创建缺失的表和列，这是幂等操作。
    同时确认数据库文件可正常打开和关闭。
    """
    log('INFO', 'Startup', '[1/4] 检查数据库完整性...')
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
    log('INFO', 'Startup', '[2/4] 检查文件结构完整性...')
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
    'UPDATE_EXCLUDED_FILES': 'site.duckdb,site.duckdb.wal,backups,uploads,ssl,.env,__pycache__',
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

    只补充缺失项，不修改已有值。
    """
    log('INFO', 'Startup', '[3/4] 检查系统配置完整性...')
    try:
        from services.settings_manager import get_setting, set_setting
        added = 0
        for key, default_value in _DEFAULT_SETTINGS.items():
            try:
                existing = get_setting(key, None)
                if existing is None:
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
# 4. Uploads 目录结构检查
# ---------------------------------------------------------------------------

def _check_uploads_structure(app_root: str):
    """检查 uploads 目录下的文件结构是否合理。

    不移动不删除文件，仅确保子目录存在。
    """
    log('INFO', 'Startup', '[4/4] 检查 uploads 目录结构...')
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