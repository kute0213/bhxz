"""管理员防火墙管理路由 —— 三种页面：主页（IP+账号封禁列表）、设置、手动封禁。"""

from flask import redirect, url_for, flash, request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from routes.firewall.spam import SPAM_LIMITS
from routes.firewall import (
    ban_ip, unban_ip, get_bans, get_whitelist,
    whitelist_add, whitelist_remove,
    get_all_warnings, get_account_bans, ban_account, unban_account,
    get_ban_detail_service,           # 封禁详情查询
    get_account_whitelist,            # 账号白名单
    whitelist_account, unwhitelist_account,
    ban_ip_manual, ban_account_manual,  # 手动封禁（自动推送 context）
    get_combined_bans,                 # 合并封禁列表
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
    IPV6_BLOCK_ENABLED,
    get_config_value,
)
from routes.admin import admin_bp


def _payload():
    """读取 JSON（或表单兜底）请求体。"""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict()


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
    """主页：合并的 IP + 账号封禁列表，分页每页 10 条。"""
    bans, total = get_combined_bans(offset=0, limit=10)
    current_ip = get_client_ip()
    whitelist = get_whitelist()
    account_whitelist = get_account_whitelist()
    return render_page(
        'admin/firewall.html',
        page='main',
        bans=bans, bans_total=total,
        current_ip=current_ip, whitelist=whitelist,
        account_whitelist=account_whitelist,
    )


# ===========================================================================
# 防火墙日志页面
# ===========================================================================

@admin_bp.route('/admin/firewall/logs')
@admin_required
def admin_firewall_logs_page():
    """防火墙日志页面，自动筛选 Firewall 相关日志。"""
    return render_page(
        'admin/firewall.html',
        page='logs',
        current_ip=get_client_ip(),
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
        'admin/firewall.html',
        page='settings',
        FIREWALL_CONFIG_KEYS=FIREWALL_CONFIG_KEYS,
        warnings=warnings, current_ip=current_ip,
        auto_ban_enabled=get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED),
        auto_ban_duration_minutes=get_config_value('AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES),
        auto_ban_login_enabled=get_config_value('AUTO_BAN_LOGIN_ENABLED', True),
        auto_ban_register_enabled=get_config_value('AUTO_BAN_REGISTER_ENABLED', True),
        auto_ban_email_enabled=get_config_value('AUTO_BAN_EMAIL_ENABLED', True),
        auto_ban_forgot_password_enabled=get_config_value('AUTO_BAN_FORGOT_PASSWORD_ENABLED', True),
        auto_ban_permanent_after=get_config_value('AUTO_BAN_PERMANENT_AFTER', 0),
        auto_ban_offense_window_hours=get_config_value('AUTO_BAN_OFFENSE_WINDOW_HOURS', 24),
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
        # IPv6 拦截
        ipv6_block_enabled=get_config_value('IPV6_BLOCK_ENABLED', IPV6_BLOCK_ENABLED),
        # 发布频率限制（从 SPAM_LIMITS 读取默认值）
        spam_limit_building=get_config_value('SPAM_LIMIT_BUILDING', SPAM_LIMITS.get('building', (2, 120))[0]),
        spam_limit_building_window=get_config_value('SPAM_LIMIT_BUILDING_WINDOW', SPAM_LIMITS.get('building', (2, 120))[1]),
        spam_limit_building_comment=get_config_value('SPAM_LIMIT_BUILDING_COMMENT', SPAM_LIMITS.get('building_comment', (5, 60))[0]),
        spam_limit_building_comment_window=get_config_value('SPAM_LIMIT_BUILDING_COMMENT_WINDOW', SPAM_LIMITS.get('building_comment', (5, 60))[1]),
        spam_limit_discussion_topic=get_config_value('SPAM_LIMIT_DISCUSSION_TOPIC', SPAM_LIMITS.get('discussion_topic', (2, 60))[0]),
        spam_limit_discussion_topic_window=get_config_value('SPAM_LIMIT_DISCUSSION_TOPIC_WINDOW', SPAM_LIMITS.get('discussion_topic', (2, 60))[1]),
        spam_limit_discussion_reply=get_config_value('SPAM_LIMIT_DISCUSSION_REPLY', SPAM_LIMITS.get('discussion_reply', (5, 60))[0]),
        spam_limit_discussion_reply_window=get_config_value('SPAM_LIMIT_DISCUSSION_REPLY_WINDOW', SPAM_LIMITS.get('discussion_reply', (5, 60))[1]),
        spam_limit_guide=get_config_value('SPAM_LIMIT_GUIDE', SPAM_LIMITS.get('guide', (2, 120))[0]),
        spam_limit_guide_window=get_config_value('SPAM_LIMIT_GUIDE_WINDOW', SPAM_LIMITS.get('guide', (2, 120))[1]),
        spam_limit_background=get_config_value('SPAM_LIMIT_BACKGROUND', SPAM_LIMITS.get('background', (6, 60))[0]),
        spam_limit_background_window=get_config_value('SPAM_LIMIT_BACKGROUND_WINDOW', SPAM_LIMITS.get('background', (6, 60))[1]),
        spam_limit_music=get_config_value('SPAM_LIMIT_MUSIC', SPAM_LIMITS.get('music', (3, 600))[0]),
        spam_limit_music_window=get_config_value('SPAM_LIMIT_MUSIC_WINDOW', SPAM_LIMITS.get('music', (3, 600))[1]),
    )


# ===========================================================================
# 手动添加封禁页面
# ===========================================================================

@admin_bp.route('/admin/firewall/ban')
@admin_required
def admin_firewall_ban_page():
    """手动添加封禁页面（IP + 账号）。"""
    return render_page(
        'admin/firewall.html',
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
    'AUTO_BAN_PERMANENT_AFTER', 'AUTO_BAN_OFFENSE_WINDOW_HOURS',
    'SUSPICIOUS_BLOCK_ENABLED', 'SUSPICIOUS_BLOCK_DURATION_MINUTES',
    'SUSPICIOUS_BLOCK_SQLI_ENABLED', 'SUSPICIOUS_BLOCK_XSS_ENABLED',
    'SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED',
    'SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED',
    'SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED',
    'SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED',
    'DDOS_GUARD_ENABLED', 'DDOS_GUARD_INTENSITY',
    'DDOS_GUARD_BAN_MINUTES', 'DDOS_GUARD_PERMANENT_AFTER',
    'DDOS_GUARD_OFFENSE_WINDOW_HOURS',
    # IPv6 拦截
    'IPV6_BLOCK_ENABLED',
    # 发布内容注入检测
    'CONTENT_INJECTION_BAN_ENABLED',
    'CONTENT_INJECTION_BAN_DURATION_MINUTES',
    # 发布频率限制
    'SPAM_LIMIT_BUILDING', 'SPAM_LIMIT_BUILDING_WINDOW',
    'SPAM_LIMIT_BUILDING_COMMENT', 'SPAM_LIMIT_BUILDING_COMMENT_WINDOW',
    'SPAM_LIMIT_DISCUSSION_TOPIC', 'SPAM_LIMIT_DISCUSSION_TOPIC_WINDOW',
    'SPAM_LIMIT_DISCUSSION_REPLY', 'SPAM_LIMIT_DISCUSSION_REPLY_WINDOW',
    'SPAM_LIMIT_GUIDE', 'SPAM_LIMIT_GUIDE_WINDOW',
    'SPAM_LIMIT_BACKGROUND', 'SPAM_LIMIT_BACKGROUND_WINDOW',
    'SPAM_LIMIT_MUSIC', 'SPAM_LIMIT_MUSIC_WINDOW',
}

# ===========================================================================
# 合并封禁列表 API（分页）
# ===========================================================================


@admin_bp.route('/admin/firewall/bans/api')
@admin_required
def admin_firewall_bans_api():
    """返回合并封禁列表 JSON（分页，每页 10 条）。"""
    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1
    offset = (page - 1) * 10
    bans, total = get_combined_bans(offset=offset, limit=10)
    has_more = (offset + 10) < total
    items = []
    for b in bans:
        items.append({
            'id': b['id'],
            'ban_type': b['ban_type'],
            'identifier': b['identifier'],
            'identifier_label': b['identifier_label'],
            'user_id': b['user_id'],
            'username': b['username'],
            'reason': (b['reason'] or '')[:30],
            'created_at': b['created_at'],
            'expires_at': b['expires_at'],
            'is_permanent': b['expires_at'] is None,
            'expires_date': b['expires_at'][:10] if b['expires_at'] else None,
        })
    return jsonify({'success': True, 'items': items, 'total': total, 'has_more': has_more, 'page': page})


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
        'IPV6_BLOCK_ENABLED',
    }
    int_keys = {
        'AUTO_BAN_DURATION_MINUTES', 'SUSPICIOUS_BLOCK_DURATION_MINUTES',
        'DDOS_GUARD_BAN_MINUTES', 'DDOS_GUARD_PERMANENT_AFTER',
        'DDOS_GUARD_OFFENSE_WINDOW_HOURS',
        'SPAM_LIMIT_BUILDING', 'SPAM_LIMIT_BUILDING_WINDOW',
        'SPAM_LIMIT_BUILDING_COMMENT', 'SPAM_LIMIT_BUILDING_COMMENT_WINDOW',
        'SPAM_LIMIT_DISCUSSION_TOPIC', 'SPAM_LIMIT_DISCUSSION_TOPIC_WINDOW',
        'SPAM_LIMIT_DISCUSSION_REPLY', 'SPAM_LIMIT_DISCUSSION_REPLY_WINDOW',
        'SPAM_LIMIT_GUIDE', 'SPAM_LIMIT_GUIDE_WINDOW',
        'SPAM_LIMIT_BACKGROUND', 'SPAM_LIMIT_BACKGROUND_WINDOW',
        'SPAM_LIMIT_MUSIC', 'SPAM_LIMIT_MUSIC_WINDOW',
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
    """手动封禁 IP（JSON API，前端无刷新）。"""
    user = get_current_user()
    data = _payload()
    ip_address = (data.get('ip_address') or '').strip()
    reason = (data.get('reason') or '').strip()
    duration_days = str(data.get('duration_days') or '').strip()
    if not ip_address:
        return jsonify({'success': False, 'message': 'IP 地址不能为空'}), 400
    duration_minutes = None
    if duration_days:
        try:
            duration_minutes = float(duration_days) * 1440
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '封禁时长无效'}), 400
    success, message = ban_ip(
        ip_address=ip_address, reason=reason,
        banned_by=user['id'], duration_minutes=duration_minutes,
    )
    return jsonify({'success': success, 'message': message}), (200 if success else 400)


@admin_bp.route('/admin/firewall/<int:ban_id>/delete', methods=['POST'])
@admin_required
def admin_firewall_delete(ban_id):
    """解除 IP 封禁（JSON API，前端无刷新）。"""
    success, message, _ = unban_ip(ban_id=ban_id)
    return jsonify({'success': success, 'message': message}), (200 if success else 404)


# ---- 账号封禁操作 ----

@admin_bp.route('/admin/firewall/ban-account', methods=['POST'])
@admin_required
def admin_firewall_ban_account():
    """手动封禁账号（JSON API，前端无刷新）。"""
    user = get_current_user()
    data = _payload()
    user_id = str(data.get('user_id') or '').strip()
    reason = (data.get('reason') or '').strip()
    duration_minutes = str(data.get('duration_minutes') or '').strip()
    if not user_id:
        return jsonify({'success': False, 'message': '用户 ID 不能为空'}), 400
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '用户 ID 必须为数字'}), 400
    dur = None
    if duration_minutes:
        try:
            dur = int(duration_minutes)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '封禁时长无效'}), 400
    success, message = ban_account(
        user_id=uid, reason=reason or '管理员封禁',
        banned_by=user['id'], duration_minutes=dur,
    )
    return jsonify({'success': success, 'message': message}), (200 if success else 400)


@admin_bp.route('/admin/firewall/unban-account/<int:ban_id>', methods=['POST'])
@admin_required
def admin_firewall_unban_account(ban_id):
    """解除账号封禁（JSON API，前端无刷新）。"""
    success, message, _ = unban_account(ban_id)
    return jsonify({'success': success, 'message': message}), (200 if success else 404)


# ---- 白名单操作 ----

@admin_bp.route('/admin/firewall/whitelist/add', methods=['POST'])
@admin_required
def admin_firewall_whitelist_add():
    """添加 IP 白名单（JSON API，前端无刷新）。"""
    data = _payload()
    ip_address = (data.get('ip_address') or '').strip()
    if not ip_address:
        return jsonify({'success': False, 'message': 'IP 地址不能为空'}), 400
    success, message = whitelist_add(ip_address)
    return jsonify({'success': success, 'message': message, 'ip_address': ip_address}), (200 if success else 400)


@admin_bp.route('/admin/firewall/whitelist/remove', methods=['POST'])
@admin_required
def admin_firewall_whitelist_remove():
    """移除 IP 白名单（JSON API，前端无刷新）。"""
    data = _payload()
    ip_address = (data.get('ip_address') or '').strip()
    if not ip_address:
        return jsonify({'success': False, 'message': 'IP 地址不能为空'}), 400
    success, message = whitelist_remove(ip_address)
    return jsonify({'success': success, 'message': message}), (200 if success else 400)


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
        'admin/firewall.html',
        page='whitelist',
        whitelist=whitelist,
        account_whitelist=enriched,
    )


@admin_bp.route('/admin/firewall/whitelist/account/add', methods=['POST'])
@admin_required
def admin_firewall_whitelist_account_add():
    """添加账号白名单（JSON API，前端无刷新）。"""
    data = _payload()
    user_id = str(data.get('user_id') or '').strip()
    note = (data.get('note') or '').strip()
    if not user_id:
        return jsonify({'success': False, 'message': '用户 ID 不能为空'}), 400
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '用户 ID 必须为数字'}), 400
    success, message = whitelist_account(uid, note)
    return jsonify({'success': success, 'message': message, 'user_id': uid, 'note': note}), (200 if success else 400)


@admin_bp.route('/admin/firewall/whitelist/account/remove', methods=['POST'])
@admin_required
def admin_firewall_whitelist_account_remove():
    """移除账号白名单（JSON API，前端无刷新）。"""
    data = _payload()
    user_id = str(data.get('user_id') or '').strip()
    if not user_id:
        return jsonify({'success': False, 'message': '用户 ID 不能为空'}), 400
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '用户 ID 必须为数字'}), 400
    success, message = unwhitelist_account(uid)
    return jsonify({'success': success, 'message': message}), (200 if success else 400)


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