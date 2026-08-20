"""管理后台 - 系统设置。

提供设置的读取、保存、重置接口，支持通过管理后台在线编辑配置。
"""

from flask import request, jsonify, render_template, abort, flash, redirect, url_for

from core.auth import login_required, get_current_user
from routes.admin import admin_bp
from config import SETTINGS_REGISTRY, get_config_value
from services.logger import log
from services.settings_manager import settings_manager


def _admin_check():
    """检查管理员权限。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return user


@admin_bp.route('/admin/settings')
@login_required
def admin_settings_page():
    """系统设置页面。"""
    user = _admin_check()
    return render_template('admin/admin_settings.html', user=user)


@admin_bp.route('/admin/api/settings')
@login_required
def api_get_settings():
    """获取所有设置（包含默认值和当前数据库存储的值）。"""
    user = _admin_check()

    # 从数据库获取已存储的设置
    from services.settings_manager import get_all_settings
    db_settings = {item['key']: item for item in get_all_settings()}

    # 构建完整的设置列表
    settings_list = []
    for key, default_value, stype, label, description, category in SETTINGS_REGISTRY:
        # 尝试从数据库读取当前值
        current_value = get_config_value(key, default_value)
        db_entry = db_settings.get(key)

        settings_list.append({
            'key': key,
            'label': label,
            'description': description,
            'category': category,
            'type': stype,
            'default': default_value,
            'value': current_value,
            'is_custom': db_entry is not None,
            'updated_at': db_entry.get('updated_at', '') if db_entry else '',
        })

    # 按分类分组
    categories = {}
    for s in settings_list:
        cat = s['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(s)

    return jsonify({
        'success': True,
        'categories': categories,
        'settings': settings_list,
    })


@admin_bp.route('/admin/api/settings/save', methods=['POST'])
@login_required
def api_save_settings():
    """保存一个或多个设置。"""
    user = _admin_check()

    data = request.get_json() or {}
    items = data.get('items', [])

    if not isinstance(items, list):
        return jsonify({'success': False, 'message': '参数格式错误'}), 400

    # 验证并保存
    valid_keys = {reg[0] for reg in SETTINGS_REGISTRY}
    saved = []
    errors = []

    from services.settings_manager import settings_manager

    for item in items:
        key = item.get('key')
        value = item.get('value')

        if not key or key not in valid_keys:
            errors.append({'key': key, 'message': '无效的设置键'})
            continue

        # 获取类型信息
        reg = next((r for r in SETTINGS_REGISTRY if r[0] == key), None)
        if reg:
            default_value = reg[1]
            stype = reg[2]
            # 类型转换
            try:
                if stype == 'bool':
                    if isinstance(value, str):
                        value = value.lower() in ('1', 'true', 'yes', 'on')
                    else:
                        value = bool(value)
                elif stype == 'int':
                    value = int(value)
                elif stype == 'float':
                    value = float(value)
                elif stype == 'time':
                    # 验证时间格式 HH:MM
                    import re
                    if not re.match(r'^\d{2}:\d{2}$', str(value)):
                        errors.append({'key': key, 'message': '时间格式应为 HH:MM'})
                        continue
            except (ValueError, TypeError) as e:
                errors.append({'key': key, 'message': f'值类型错误: {e}'})
                continue

        try:
            settings_manager.set(key, value)
            saved.append(key)
        except Exception as e:
            errors.append({'key': key, 'message': str(e)})

    # 失效缓存
    settings_manager.invalidate_cache()

    return jsonify({
        'success': len(errors) == 0,
        'saved': saved,
        'errors': errors,
        'message': f'成功保存 {len(saved)} 项设置' + (f'，{len(errors)} 项失败' if errors else ''),
    })


@admin_bp.route('/admin/api/settings/<key>/reset', methods=['POST'])
@login_required
def api_reset_setting(key):
    """重置单个设置为默认值。"""
    user = _admin_check()

    valid_keys = {reg[0] for reg in SETTINGS_REGISTRY}
    if key not in valid_keys:
        return jsonify({'success': False, 'message': '无效的设置键'}), 400

    from services.settings_manager import settings_manager
    settings_manager.delete(key)
    settings_manager.invalidate_cache()

    return jsonify({
        'success': True,
        'message': f'已重置 {key} 为默认值',
    })


@admin_bp.route('/admin/api/settings/reset-all', methods=['POST'])
@login_required
def api_reset_all_settings():
    """重置所有设置为默认值。"""
    user = _admin_check()

    from services.settings_manager import settings_manager
    all_settings = settings_manager.get_all()
    configurable_keys = {reg[0] for reg in SETTINGS_REGISTRY}
    deleted_count = 0
    for s in all_settings:
        # 只重置界面中声明的配置
        if s['key'] not in configurable_keys:
            continue
        try:
            settings_manager.delete(s['key'])
            deleted_count += 1
        except Exception:
            pass

    settings_manager.invalidate_cache()

    return jsonify({
        'success': True,
        'message': f'已重置 {deleted_count} 项设置为默认值',
    })