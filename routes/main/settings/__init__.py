"""设置路由：修改用户名、密码、邮箱、删除账号。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
页面表单走 ``/settings/*``（整页提交），前端无刷新操作走 ``/api/settings/*``（JSON 响应）。
"""

from flask import request, redirect, url_for, session, flash, jsonify
from core.auth import login_required, get_current_user
from core.helpers import render_page
from services.mail import normalize_email
from services.user import (
    change_username as svc_change_username,
    change_password as svc_change_password,
    change_email as svc_change_email,
    delete_account as svc_delete_account,
)
from core.shared.ip import get_client_ip
from routes.main import main_bp


def _form_value(name, default=''):
    """读取字段：兼容 JSON 请求体与普通表单。"""
    data = request.get_json(silent=True)
    if isinstance(data, dict) and name in data:
        value = data.get(name)
    else:
        value = request.form.get(name, default)
    return default if value is None else value


# ---------------------------------------------------------------------------
# 设置页面
# ---------------------------------------------------------------------------

@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    return render_page('settings/index.html', tab=request.args.get('tab', 'username'))


# ---------------------------------------------------------------------------
# 无刷新 API（返回 JSON）
# ---------------------------------------------------------------------------

@main_bp.route('/api/settings/username', methods=['POST'])
@login_required
def api_change_username():
    """修改用户名（无刷新）。"""
    user = get_current_user()
    new_username = str(_form_value('new_username')).strip()
    success, message = svc_change_username(
        user_id=user['id'],
        current_username=user['username'],
        new_username=new_username,
        current_password=_form_value('current_password'),
        ip_address=get_client_ip(),
    )
    if success:
        session['username'] = new_username
    return jsonify({
        'success': success,
        'message': message,
        'username': new_username if success else None,
    })


@main_bp.route('/api/settings/password', methods=['POST'])
@login_required
def api_change_password():
    """修改密码（无刷新）。"""
    user = get_current_user()
    success, message = svc_change_password(
        user_id=user['id'],
        username=user['username'],
        current_password=_form_value('current_password'),
        new_password=_form_value('new_password'),
        confirm_password=_form_value('confirm_password'),
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})


@main_bp.route('/api/settings/email', methods=['POST'])
@login_required
def api_change_email():
    """修改邮箱（无刷新）。"""
    user = get_current_user()
    new_email = normalize_email(_form_value('new_email'))
    success, message = svc_change_email(
        user_id=user['id'],
        username=user['username'],
        new_email=new_email,
        email_code=str(_form_value('email_code')).strip(),
        current_password=_form_value('current_password'),
        ip_address=get_client_ip(),
    )
    return jsonify({
        'success': success,
        'message': message,
        'email': new_email if success else None,
    })


@main_bp.route('/api/settings/delete', methods=['POST'])
@login_required
def api_delete_account():
    """注销账号（无刷新，成功后前端跳转首页）。"""
    user = get_current_user()
    success, message = svc_delete_account(
        user_id=user['id'],
        username=user['username'],
        confirm_username=str(_form_value('confirm_username')).strip(),
        ip_address=get_client_ip(),
    )
    if success:
        session.clear()
    return jsonify({'success': success, 'message': message, 'redirect': '/' if success else None})


# ---------------------------------------------------------------------------
# 兼容旧表单提交（整页跳转）
# ---------------------------------------------------------------------------

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
