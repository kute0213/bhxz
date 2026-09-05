"""设置路由：修改用户名、密码、邮箱、删除账号。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, request, redirect, url_for, session, flash
from core.auth import login_required, get_current_user
from services.email import normalize_email
from services.user_service import (
    change_username as svc_change_username,
    change_password as svc_change_password,
    change_email as svc_change_email,
    delete_account as svc_delete_account,
)
from services.ip import get_client_ip
from routes.main import main_bp


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------

@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = get_current_user()
    return render_template('settings.html', user=user, tab=request.args.get('tab', 'username'))


@main_bp.route('/settings/username', methods=['POST'])
@login_required
def change_username():
    user = get_current_user()
    success, message = svc_change_username(
        user_id=user['id'],
        current_username=user['username'],
        new_username=request.form.get('new_username', '').strip(),
        current_password=request.form.get('current_password', ''),
        ip_address=get_client_ip(),
    )
    if success:
        session['username'] = request.form.get('new_username', '').strip()
    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.settings'))

@main_bp.route('/settings/password', methods=['POST'])
@login_required
def change_password():
    user = get_current_user()
    success, message = svc_change_password(
        user_id=user['id'],
        username=user['username'],
        current_password=request.form.get('current_password', ''),
        new_password=request.form.get('new_password', ''),
        confirm_password=request.form.get('confirm_password', ''),
        ip_address=get_client_ip(),
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.settings'))

@main_bp.route('/settings/email', methods=['POST'])
@login_required
def change_email():
    user = get_current_user()
    success, message = svc_change_email(
        user_id=user['id'],
        username=user['username'],
        new_email=normalize_email(request.form.get('new_email', '')),
        email_code=request.form.get('email_code', '').strip(),
        current_password=request.form.get('current_password', ''),
        ip_address=get_client_ip(),
    )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('main.settings'))


@main_bp.route('/settings/delete', methods=['POST'])
@login_required
def delete_account():
    user = get_current_user()
    success, message = svc_delete_account(
        user_id=user['id'],
        username=user['username'],
        confirm_username=request.form.get('confirm_username', '').strip(),
        ip_address=get_client_ip(),
    )
    if success:
        session.clear()
        flash(message, 'success')
        return redirect(url_for('main.home'))
    flash(message, 'error')
    return redirect(url_for('main.settings'))
