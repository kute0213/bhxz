"""管理员防火墙管理路由 —— 三种页面：主页（IP+账号封禁列表）、设置、手动封禁。"""

from flask import redirect, url_for, flash, request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.firewall import (
    ban_ip, unban_ip, get_bans, get_whitelist,
    whitelist_add, whitelist_remove,
    get_all_warnings, get_account_bans, ban_account, unban_account,
    get_ban_detail_service,           # 封禁详情查询
    get_account_whitelist,            # 账号白名单
    whitelist_account, unwhitelist_account,
    ban_ip_manual, ban_account_manual,  # 手动封禁（自动推送 context）
)
from core.shared.ip import get_client_ip
from config import (
    AUTO_BAN_ENABLED, AUTO_BAN_DURATION_MINUTES,
    AUTO_BAN_LOGIN_ENABLED, AUTO_BAN_REGISTER_ENABLED,
    AUTO_BAN_EMAIL_ENABLED, AUTO_BAN_FORGOT_PASSWORD_ENABLED,
    SUSPICIOUS_BLOCK_ENABLED, SUSPICIOUS_BLOCK_DURATION_MINUTES,
    SUSPICIOUS_BLOCK_SQLI_ENABLED, SUSPICIOUS_BLOCK_XSS_ENABLED,
    SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED,
    SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED,
    SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED,
    SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED,
    DDOS_GUARD_ENABLED, DDOS_GUARD_INTENSITY,
    DDOS_GUARD_BAN_MINUTES, DDOS_GUARD_PERMANENT_AFTER,
    DDOS_GUARD_OFFENSE_WINDOW_HOURS,
    get_config_value,
)
from routes.admin import admin_bp


def _resolve_account_usernames(account_bans):
    """为账号封禁列表补充用户名。"""
    from core.db import get_db
    result = []
    for ban in account_bans:
        ban = dict(ban)
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT username FROM users WHERE id = ?", (ban['user_id'],)
            ).fetchone()
            ban['username'] = row[0] if row else f"用户{ban['user_id']}"
            conn.close()
            if ban['banned_by']:
                conn2 = get_db()
                banner = conn2.execute(
                    "SELECT username FROM users WHERE id = ?", (ban['banned_by'],)
                ).fetchone()
                ban['banned_by_name'] = banner[0] if banner else f"用户{ban['banned_by']}"
                conn2.close()
            else:
                ban['banned_by_name'] = '系统'
        except Exception:
            ban['username'] = f"用户{ban['user_id']}"
            ban['banned_by_name'] = '系统'
        result.append(ban)
    return result


# ===========================================================================
# 主页：IP 封禁 + 账号封禁列表
# ===========================================================================

@admin_bp.route('/admin/firewall')
@admin_required
def admin_firewall():
    """主页：同时显示 IP 封禁与账号封禁列表。"""
    bans = get_bans()
    account_bans = _resolve_account_usernames(get_account_bans())
    current_ip = get_client_ip()
    whitelist = get_whitelist()
    account_whitelist = get_account_whitelist()
    return render_page(
        'admin/admin_firewall.html',
        page='main',
        bans=bans, account_bans=account_bans,
        current_ip=current_ip, whitelist=whitelist,
        account_whitelist=account_whitelist,
    )


# ===========================================================================
# 设置页面
# ===========================================================================

@admin_bp.route('/admin/firewall/settings')
@admin_required
def admin_firewall_settings_page():
    """防火墙设置页面。"""
    warnings = get_all_warnings()
    current_ip = get_client_ip()
    return render_page(
        'admin/admin_firewall.html',
        page='settings',
        warnings=warnings, current_ip=current_ip,
        auto_ban_enabled=get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED),
        auto_ban_duration_minutes=get_config_value('AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES),
        auto_ban_login_enabled=get_config_value('AUTO_BAN_LOGIN_ENABLED', True),
        auto_ban_register_enabled=get_config_value('AUTO_BAN_REGISTER_ENABLED', True),
        auto_ban_email_enabled=get_config_value('AUTO_BAN_EMAIL_ENABLED', True),
        auto_ban_forgot_password_enabled=get_config_value('AUTO_BAN_FORGOT_PASSWORD_ENABLED', True),
        suspicious_block_enabled=get_config_value('SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED),
        suspicious_block_duration_minutes=get_config_value('SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES),
        suspicious_sqli_enabled=get_config_value('SUSPICIOUS_BLOCK_SQLI_ENABLED', True),
        suspicious_xss_enabled=get_config_value('SUSPICIOUS_BLOCK_XSS_ENABLED', True),
        suspicious_path_traversal_enabled=get_config_value('SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED', True),
        suspicious_command_injection_enabled=get_config_value('SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED', True),
        suspicious_sensitive_probe_enabled=get_config_value('SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED', True),
        suspicious_malicious_ua_enabled=get_config_value('SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED', True),
        ddos_guard_enabled=get_config_value('DDOS_GUARD_ENABLED', True),
        ddos_guard_intensity=get_config_value('DDOS_GUARD_INTENSITY', 'medium'),
        ddos_guard_ban_minutes=get_config_value('DDOS_GUARD_BAN_MINUTES', 30),
        ddos_guard_permanent_after=get_config_value('DDOS_GUARD_PERMANENT_AFTER', 3),
        ddos_guard_offense_window_hours=get_config_value('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24),
        # 发布内容注入检测
        content_injection_enabled=get_config_value('CONTENT_INJECTION_BAN_ENABLED', True),
        content_injection_duration=get_config_value('CONTENT_INJECTION_BAN_DURATION_MINUTES', 30),
    )


# ===========================================================================
# 手动添加封禁页面
# ===========================================================================

@admin_bp.route('/admin/firewall/ban')
@admin_required
def admin_firewall_ban_page():
    """手动添加封禁页面（IP + 账号）。"""
    return render_page(
        'admin/admin_firewall.html',
        page='ban',
        current_ip=get_client_ip(),
    )


# ===========================================================================
# 共享配置
# ===========================================================================

FIREWALL_CONFIG_KEYS = {
    'FIREWALL_WHITELIST', 'AUTO_BAN_ENABLED', 'AUTO_BAN_DURATION_MINUTES',
    'AUTO_BAN_LOGIN_ENABLED', 'AUTO_BAN_REGISTER_ENABLED',
    'AUTO_BAN_EMAIL_ENABLED', 'AUTO_BAN_FORGOT_PASSWORD_ENABLED',
    'SUSPICIOUS_BLOCK_ENABLED', 'SUSPICIOUS_BLOCK_DURATION_MINUTES',
    'SUSPICIOUS_BLOCK_SQLI_ENABLED', 'SUSPICIOUS_BLOCK_XSS_ENABLED',
    'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
    'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
    'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
    'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED',
    'DDOS_GUARD_ENABLED', 'DDOS_GUARD_INTENSITY',
    'DDOS_GUARD_BAN_MINUTES', 'DDOS_GUARD_PERMANENT_AFTER',
    'DDOS_GUARD_OFFENSE_WINDOW_HOURS',
    # 发布内容注入检测
    'CONTENT_INJECTION_BAN_ENABLED',
    'CONTENT_INJECTION_BAN_DURATION_MINUTES',
}

# ===========================================================================
# API / POST 操作
# ===========================================================================


@admin_bp.route('/admin/firewall/settings/save', methods=['POST'])
@admin_required
def admin_firewall_settings_save():
    """保存防火墙配置（AJAX）。"""
    from services.settings_manager import settings_manager
    data = request.get_json() or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'success': False, 'message': '参数格式错误'}), 400
    saved = []
    errors = []
    bool_keys = {
        'AUTO_BAN_ENABLED', 'AUTO_BAN_LOGIN_ENABLED', 'AUTO_BAN_REGISTER_ENABLED',
        'AUTO_BAN_EMAIL_ENABLED', 'AUTO_BAN_FORGOT_PASSWORD_ENABLED',
        'SUSPICIOUS_BLOCK_ENABLED', 'SUSPICIOUS_BLOCK_SQLI_ENABLED',
        'SUSPICIOUS_BLOCK_XSS_ENABLED', 'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
        'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
        'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
        'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED', 'DDOS_GUARD_ENABLED',
    }
    int_keys = {
        'AUTO_BAN_DURATION_MINUTES', 'SUSPICIOUS_BLOCK_DURATION_MINUTES',
        'DDOS_GUARD_BAN_MINUTES', 'DDOS_GUARD_PERMANENT_AFTER',
        'DDOS_GUARD_OFFENSE_WINDOW_HOURS',
    }
    for item in items:
        key = item.get('key')
        value = item.get('value')
        if not key or key not in FIREWALL_CONFIG_KEYS:
            errors.append({'key': key, 'message': '无效的设置键'})
            continue
        try:
            if key in bool_keys:
                if isinstance(value, str):
                    value = value.lower() in ('1', 'true', 'yes', 'on')
                else:
                    value = bool(value)
            elif key in int_keys:
                value = int(value)
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
        'saved': saved, 'errors': errors,
        'message': f'成功保存 {len(saved)} 项配置' + (f'，{len(errors)} 项失败' if errors else ''),
    })


# ---- IP 封禁操作 ----

@admin_bp.route('/admin/firewall/ban-ip', methods=['POST'])
@admin_required
def admin_firewall_ban_ip():
    """手动封禁 IP。"""
    user = get_current_user()
    ip_address = (request.form.get('ip_address') or '').strip()
    reason = (request.form.get('reason') or '').strip()
    duration_days = (request.form.get('duration_days') or '').strip()
    if not ip_address:
        flash('IP 地址不能为空', 'error')
        return redirect(url_for('admin.admin_firewall'))
    duration_minutes = None
    if duration_days:
        try:
            duration_minutes = float(duration_days) * 1440
        except (ValueError, TypeError):
            flash('封禁时长无效', 'error')
            return redirect(url_for('admin.admin_firewall'))
    success, message = ban_ip(
        ip_address=ip_address, reason=reason,
        banned_by=user['id'], duration_minutes=duration_minutes,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


@admin_bp.route('/admin/firewall/<int:ban_id>/delete', methods=['POST'])
@admin_required
def admin_firewall_delete(ban_id):
    """解除 IP 封禁。"""
    success, message, _ = unban_ip(ban_id=ban_id)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


# ---- 账号封禁操作 ----

@admin_bp.route('/admin/firewall/ban-account', methods=['POST'])
@admin_required
def admin_firewall_ban_account():
    """手动封禁账号。"""
    user = get_current_user()
    user_id = (request.form.get('user_id') or '').strip()
    reason = (request.form.get('reason') or '').strip()
    duration_minutes = (request.form.get('duration_minutes') or '').strip()
    if not user_id:
        flash('用户 ID 不能为空', 'error')
        return redirect(url_for('admin.admin_firewall'))
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        flash('用户 ID 必须为数字', 'error')
        return redirect(url_for('admin.admin_firewall'))
    dur = None
    if duration_minutes:
        try:
            dur = int(duration_minutes)
        except (ValueError, TypeError):
            flash('封禁时长无效', 'error')
            return redirect(url_for('admin.admin_firewall'))
    success, message = ban_account(
        user_id=uid, reason=reason or '管理员封禁',
        banned_by=user['id'], duration_minutes=dur,
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


@admin_bp.route('/admin/firewall/unban-account/<int:ban_id>', methods=['POST'])
@admin_required
def admin_firewall_unban_account(ban_id):
    """解除账号封禁。"""
    success, message, _ = unban_account(ban_id)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


# ---- 白名单操作 ----

@admin_bp.route('/admin/firewall/whitelist/add', methods=['POST'])
@admin_required
def admin_firewall_whitelist_add():
    """添加 IP 白名单。"""
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
    """移除 IP 白名单。"""
    ip_address = (request.form.get('ip_address') or '').strip()
    if not ip_address:
        flash('IP 地址不能为空', 'error')
        return redirect(url_for('admin.admin_firewall'))
    success, message = whitelist_remove(ip_address)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall'))


# ===========================================================================
# 白名单设置页面
# ===========================================================================

@admin_bp.route('/admin/firewall/whitelist')
@admin_required
def admin_firewall_whitelist_page():
    """IP 白名单 + 账号白名单设置页面。"""
    whitelist = get_whitelist()
    account_whitelist = get_account_whitelist()

    # 为账号白名单补充用户名
    from core.db import get_db
    enriched = []
    for entry in account_whitelist:
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT username FROM users WHERE id = ?",
                (entry['user_id'],),
            ).fetchone()
            entry['username'] = row[0] if row else f"用户{entry['user_id']}"
            conn.close()
        except Exception:
            entry['username'] = f"用户{entry['user_id']}"
        enriched.append(entry)

    return render_page(
        'admin/admin_firewall.html',
        page='whitelist',
        whitelist=whitelist,
        account_whitelist=enriched,
    )


@admin_bp.route('/admin/firewall/whitelist/account/add', methods=['POST'])
@admin_required
def admin_firewall_whitelist_account_add():
    """添加账号白名单。"""
    user_id = (request.form.get('user_id') or '').strip()
    note = (request.form.get('note') or '').strip()
    if not user_id:
        flash('用户 ID 不能为空', 'error')
        return redirect(url_for('admin.admin_firewall_whitelist_page'))
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        flash('用户 ID 必须为数字', 'error')
        return redirect(url_for('admin.admin_firewall_whitelist_page'))
    success, message = whitelist_account(uid, note)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall_whitelist_page'))


@admin_bp.route('/admin/firewall/whitelist/account/remove', methods=['POST'])
@admin_required
def admin_firewall_whitelist_account_remove():
    """移除账号白名单。"""
    user_id = (request.form.get('user_id') or '').strip()
    if not user_id:
        flash('用户 ID 不能为空', 'error')
        return redirect(url_for('admin.admin_firewall_whitelist_page'))
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        flash('用户 ID 必须为数字', 'error')
        return redirect(url_for('admin.admin_firewall_whitelist_page'))
    success, message = unwhitelist_account(uid)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin.admin_firewall_whitelist_page'))


# ===========================================================================
# 封禁详情 API
# ===========================================================================

@admin_bp.route('/admin/firewall/<int:ban_id>/detail')
@admin_required
def admin_firewall_ban_detail(ban_id):
    """封禁详情 API：返回 JSON 格式的完整封禁信息，供前端弹窗展示。

    权限控制：仅管理员可访问（@admin_required）。
    """
    if ban_id <= 0:
        return jsonify({'success': False, 'message': '无效的封禁 ID'}), 400
    detail = get_ban_detail_service(ban_id)
    if detail is None:
        return jsonify({'success': False, 'message': '封禁详情不存在'}), 404
    return jsonify({'success': True, 'detail': detail})