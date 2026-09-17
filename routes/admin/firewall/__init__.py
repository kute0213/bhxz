"""管理员防火墙管理路由 —— 已从 IP 封禁全面迁移至防火墙模块。"""

from flask import redirect, url_for, flash, request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.firewall import (
    ban_ip, unban_ip, get_bans, get_whitelist,
    whitelist_add, whitelist_remove,
    get_all_warnings,
)
from core.shared.ip import get_client_ip
from config import (
    AUTO_BAN_ENABLED,
    AUTO_BAN_DURATION_MINUTES,
    AUTO_BAN_LOGIN_ENABLED,
    AUTO_BAN_REGISTER_ENABLED,
    AUTO_BAN_EMAIL_ENABLED,
    AUTO_BAN_FORGOT_PASSWORD_ENABLED,
    SUSPICIOUS_BLOCK_ENABLED,
    SUSPICIOUS_BLOCK_DURATION_MINUTES,
    SUSPICIOUS_BLOCK_SQLI_ENABLED,
    SUSPICIOUS_BLOCK_XSS_ENABLED,
    SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED,
    SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED,
    SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED,
    SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED,
    DDOS_GUARD_ENABLED,
    DDOS_GUARD_INTENSITY,
    DDOS_GUARD_BAN_MINUTES,
    DDOS_GUARD_PERMANENT_AFTER,
    DDOS_GUARD_OFFENSE_WINDOW_HOURS,
    get_config_value,
)
from routes.admin import admin_bp


@admin_bp.route('/admin/firewall')
@admin_required
def admin_firewall():
    """管理后台：防火墙总览页（封禁管理 + 白名单 + 全部配置）。"""
    bans = get_bans()
    current_ip = get_client_ip()
    whitelist = get_whitelist()
    warnings = get_all_warnings()
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
        warnings=warnings,
        # 自动 IP 封禁
        auto_ban_enabled=get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED),
        auto_ban_duration_minutes=get_config_value(
            'AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES),
        auto_ban_login_enabled=get_config_value('AUTO_BAN_LOGIN_ENABLED', True),
        auto_ban_register_enabled=get_config_value('AUTO_BAN_REGISTER_ENABLED', True),
        auto_ban_email_enabled=get_config_value('AUTO_BAN_EMAIL_ENABLED', True),
        auto_ban_forgot_password_enabled=get_config_value('AUTO_BAN_FORGOT_PASSWORD_ENABLED', True),
        # 可疑访问拦截
        suspicious_block_enabled=get_config_value(
            'SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED),
        suspicious_block_duration_minutes=get_config_value(
            'SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES),
        suspicious_sqli_enabled=get_config_value('SUSPICIOUS_BLOCK_SQLI_ENABLED', True),
        suspicious_xss_enabled=get_config_value('SUSPICIOUS_BLOCK_XSS_ENABLED', True),
        suspicious_path_traversal_enabled=get_config_value('SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED', True),
        suspicious_command_injection_enabled=get_config_value('SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED', True),
        suspicious_sensitive_probe_enabled=get_config_value('SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED', True),
        suspicious_malicious_ua_enabled=get_config_value('SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED', True),
        # DDoS 防护
        ddos_guard_enabled=get_config_value('DDOS_GUARD_ENABLED', True),
        ddos_guard_intensity=get_config_value('DDOS_GUARD_INTENSITY', 'medium'),
        ddos_guard_ban_minutes=get_config_value('DDOS_GUARD_BAN_MINUTES', 30),
        ddos_guard_permanent_after=get_config_value('DDOS_GUARD_PERMANENT_AFTER', 3),
        ddos_guard_offense_window_hours=get_config_value('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24),
    )


# 防火墙管理页可直接编辑的配置键
FIREWALL_CONFIG_KEYS = {
    'FIREWALL_WHITELIST',
    'AUTO_BAN_ENABLED',
    'AUTO_BAN_DURATION_MINUTES',
    'AUTO_BAN_LOGIN_ENABLED',
    'AUTO_BAN_REGISTER_ENABLED',
    'AUTO_BAN_EMAIL_ENABLED',
    'AUTO_BAN_FORGOT_PASSWORD_ENABLED',
    'SUSPICIOUS_BLOCK_ENABLED',
    'SUSPICIOUS_BLOCK_DURATION_MINUTES',
    'SUSPICIOUS_BLOCK_SQLI_ENABLED',
    'SUSPICIOUS_BLOCK_XSS_ENABLED',
    'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
    'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
    'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
    'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED',
    'DDOS_GUARD_ENABLED',
    'DDOS_GUARD_INTENSITY',
    'DDOS_GUARD_BAN_MINUTES',
    'DDOS_GUARD_PERMANENT_AFTER',
    'DDOS_GUARD_OFFENSE_WINDOW_HOURS',
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
            # 布尔类型
            if key in ('AUTO_BAN_ENABLED', 'AUTO_BAN_LOGIN_ENABLED', 'AUTO_BAN_REGISTER_ENABLED',
                       'AUTO_BAN_EMAIL_ENABLED', 'AUTO_BAN_FORGOT_PASSWORD_ENABLED',
                       'SUSPICIOUS_BLOCK_ENABLED', 'SUSPICIOUS_BLOCK_SQLI_ENABLED',
                       'SUSPICIOUS_BLOCK_XSS_ENABLED', 'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
                       'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
                       'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
                       'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED', 'DDOS_GUARD_ENABLED'):
                if isinstance(value, str):
                    value = value.lower() in ('1', 'true', 'yes', 'on')
                else:
                    value = bool(value)
            # 整数类型
            elif key in ('AUTO_BAN_DURATION_MINUTES', 'SUSPICIOUS_BLOCK_DURATION_MINUTES',
                         'DDOS_GUARD_BAN_MINUTES', 'DDOS_GUARD_PERMANENT_AFTER',
                         'DDOS_GUARD_OFFENSE_WINDOW_HOURS'):
                value = int(value)
            # 字符串/选择类型
            elif key == 'DDOS_GUARD_INTENSITY':
                value = str(value).lower()
                if value not in ('low', 'medium', 'high'):
                    value = 'medium'
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