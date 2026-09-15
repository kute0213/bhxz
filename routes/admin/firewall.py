"""管理员防火墙管理路由 —— 已从 IP 封禁全面迁移至防火墙模块。"""

from flask import redirect, url_for, flash, request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.firewall import (
    ban_ip, unban_ip, get_bans, get_whitelist, is_whitelisted,
    whitelist_add, whitelist_remove, SYSTEM_BANNER_ID,
    add_warning, get_warnings, get_warning_count,
)
from services.ip import get_client_ip
from config import (
    AUTO_BAN_ENABLED,
    AUTO_BAN_DURATION_MINUTES,
    SUSPICIOUS_BLOCK_ENABLED,
    SUSPICIOUS_BLOCK_DURATION_MINUTES,
    get_config_value,
)
from routes.admin import admin_bp


@admin_bp.route('/admin/firewall')
@admin_required
def admin_firewall():
    """管理后台：防火墙总览页（封禁管理 + 白名单 + 配置）。"""
    bans = get_bans()
    current_ip = get_client_ip()
    whitelist = get_whitelist()
    # 检查当前 IP 状态
    from core.firewall import is_banned
    current_banned, current_reason = is_banned(current_ip)
    return render_page(
        'admin/admin_firewall.html',
        bans=bans,
        current_ip=current_ip,
        current_banned=current_banned,
        current_reason=current_reason,
        whitelist=whitelist,
        auto_ban_enabled=get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED),
        auto_ban_duration_minutes=get_config_value(
            'AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES),
        suspicious_block_enabled=get_config_value(
            'SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED),
        suspicious_block_duration_minutes=get_config_value(
            'SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES),
    )


# 防火墙管理页可直接编辑的配置键
FIREWALL_CONFIG_KEYS = {
    'FIREWALL_WHITELIST',
    'AUTO_BAN_ENABLED',
    'AUTO_BAN_DURATION_MINUTES',
    'SUSPICIOUS_BLOCK_ENABLED',
    'SUSPICIOUS_BLOCK_DURATION_MINUTES',
}


@admin_bp.route('/admin/firewall/settings', methods=['POST'])
@admin_required
def admin_firewall_settings():
    """保存防火墙配置（白名单/自动封禁开关与时长/可疑拦截开关与时长）。"""
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
        if not key or key not in FIREWALL_CONFIG_KEYS:
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


@admin_bp.route('/admin/firewall/create', methods=['POST'])
@admin_required
def admin_firewall_create():
    """管理后台：创建封禁。"""
    user = get_current_user()

    ip_address = (request.form.get('ip_address') or '').strip()
    reason = (request.form.get('reason') or '').strip()
    duration_days = (request.form.get('duration_days') or '').strip()

    if not ip_address:
        flash('IP 地址不能为空', 'error')
        return redirect(url_for('admin.admin_firewall'))

    # 将天数转换为分钟
    duration_minutes = None
    if duration_days:
        try:
            duration_minutes = float(duration_days) * 1440
        except (ValueError, TypeError):
            flash('封禁时长无效', 'error')
            return redirect(url_for('admin.admin_firewall'))

    success, message = ban_ip(
        ip_address=ip_address,
        reason=reason,
        banned_by=user['id'],
        duration_minutes=duration_minutes,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


@admin_bp.route('/admin/firewall/<int:ban_id>/delete', methods=['POST'])
@admin_required
def admin_firewall_delete(ban_id):
    """管理后台：解除封禁。"""
    success, message, _ = unban_ip(ban_id=ban_id)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


# ---- 白名单快捷管理 ----


@admin_bp.route('/admin/firewall/whitelist/add', methods=['POST'])
@admin_required
def admin_firewall_whitelist_add():
    """管理后台：添加白名单。"""
    ip_address = (request.form.get('ip_address') or '').strip()
    if not ip_address:
        flash('IP 地址不能为空', 'error')
        return redirect(url_for('admin.admin_firewall'))
    success, message = whitelist_add(ip_address)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


@admin_bp.route('/admin/firewall/whitelist/remove', methods=['POST'])
@admin_required
def admin_firewall_whitelist_remove():
    """管理后台：移除白名单。"""
    ip_address = (request.form.get('ip_address') or '').strip()
    if not ip_address:
        flash('IP 地址不能为空', 'error')
        return redirect(url_for('admin.admin_firewall'))
    success, message = whitelist_remove(ip_address)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))