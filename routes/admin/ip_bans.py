"""管理员 IP 封禁管理路由。"""

from flask import redirect, url_for, flash, request

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from services import ip_ban_service
from services.ip import get_client_ip
from config import (
    IP_BAN_WHITELIST,
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
        whitelist=IP_BAN_WHITELIST,
        auto_ban_enabled=get_config_value('AUTO_BAN_ENABLED', AUTO_BAN_ENABLED),
        auto_ban_duration_minutes=get_config_value(
            'AUTO_BAN_DURATION_MINUTES', AUTO_BAN_DURATION_MINUTES),
        suspicious_block_enabled=get_config_value(
            'SUSPICIOUS_BLOCK_ENABLED', SUSPICIOUS_BLOCK_ENABLED),
        suspicious_block_duration_minutes=get_config_value(
            'SUSPICIOUS_BLOCK_DURATION_MINUTES', SUSPICIOUS_BLOCK_DURATION_MINUTES),
    )


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
