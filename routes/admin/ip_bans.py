"""管理员 IP 封禁管理路由。"""

from flask import redirect, url_for, flash, request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from services import ip_ban_service
from services.ip import get_client_ip
from config import (
    AUTO_BAN_ENABLED,
    AUTO_BAN_DURATION_MINUTES,
    SUSPICIOUS_BLOCK_ENABLED,
    SUSPICIOUS_BLOCK_DURATION_MINUTES,
    get_config_value,
)
from routes.admin import admin_bp


@admin_bp.route('/admin/ip-bans')
@admin_required
def admin_ip_bans():
    """管理后台：IP 封禁列表。"""
    bans = ip_ban_service.get_bans()
    current_ip = get_client_ip()
    return render_page(
        'admin/admin_ip_bans.html',
        bans=bans,
        current_ip=current_ip,
        whitelist=ip_ban_service.get_whitelist(),
        auto_ban_enabled=get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED),
        auto_ban_duration_minutes=get_config_value(
            'AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES),
        suspicious_block_enabled=get_config_value(
            'SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED),
        suspicious_block_duration_minutes=get_config_value(
            'SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES),
    )


# IP 封禁管理页可直接编辑的配置键
IP_BAN_CONFIG_KEYS = {
    'IP_BAN_WHITELIST',
    'AUTO_BAN_ENABLED',
    'AUTO_BAN_DURATION_MINUTES',
    'SUSPICIOUS_BLOCK_ENABLED',
    'SUSPICIOUS_BLOCK_DURATION_MINUTES',
}


@admin_bp.route('/admin/ip-bans/settings', methods=['POST'])
@admin_required
def admin_ip_ban_settings():
    """保存 IP 封禁相关配置（白名单/自动封禁开关与时长/可疑拦截开关与时长）。

    在 IP 封禁管理页面直接编辑并保存，无需跳转到系统设置。
    """
    from services.settings_manager import settings_manager

    data = request.get_json() or {}
    items = data.get('items', [])

    if not isinstance(items, list):
        return jsonify({'success': False, 'message': '参数格式错误'}), 400

    saved = []
    errors = []
    for item in items:
        key = item.get('key')
        value = item.get('value')
        if not key or key not in IP_BAN_CONFIG_KEYS:
            errors.append({'key': key, 'message': '无效的设置键'})
            continue
        try:
            if key in ('AUTO_BAN_ENABLED', 'SUSPICIOUS_BLOCK_ENABLED'):
                if isinstance(value, str):
                    value = value.lower() in ('1', 'true', 'yes', 'on')
                else:
                    value = bool(value)
            elif key in ('AUTO_BAN_DURATION_MINUTES', 'SUSPICIOUS_BLOCK_DURATION_MINUTES'):
                value = int(value)
            settings_manager.set(key, value)
            saved.append(key)
        except Exception as e:
            errors.append({'key': key, 'message': str(e)})

    settings_manager.invalidate_cache()

    return jsonify({
        'success': len(errors) == 0,
        'saved': saved,
        'errors': errors,
        'message': f'成功保存 {len(saved)} 项配置' + (f'，{len(errors)} 项失败' if errors else ''),
    })


@admin_bp.route('/admin/ip-bans/create', methods=['POST'])
@admin_required
def admin_ip_ban_create():
    """管理后台：创建封禁。"""
    user = get_current_user()

    ip_address = (request.form.get('ip_address') or '').strip()
    reason = (request.form.get('reason') or '').strip()
    duration_days = (request.form.get('duration_days') or '').strip()

    if not ip_address:
        flash('IP 地址不能为空', 'error')
        return redirect(url_for('admin.admin_ip_bans'))

    success, message = ip_ban_service.create_ban(
        ip_address=ip_address,
        reason=reason,
        banned_by=user['id'],
        duration_days=duration_days or None,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_ip_bans'))


@admin_bp.route('/admin/ip-bans/<int:ban_id>/delete', methods=['POST'])
@admin_required
def admin_ip_ban_delete(ban_id):
    """管理后台：解除封禁。"""
    user = get_current_user()

    success, message = ip_ban_service.unban(
        ban_id=ban_id,
        admin_id=user['id'],
        admin_username=user['username'],
        ip_address=get_client_ip(),
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_ip_bans'))
