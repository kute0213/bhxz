"""路由辅助函数 —— 减少重复的 get_current_user() + render_template() 模式。"""

from flask import render_template, flash, redirect, url_for, request
from core.auth import get_current_user, admin_required


def render_page(template, **kwargs):
    """渲染页面模板，自动注入当前用户。

    用法:
        render_page('settings.html', title='设置')
    等价于:
        user = get_current_user()
        return render_template('settings.html', user=user, title='设置')
    """
    if 'user' not in kwargs:
        kwargs['user'] = get_current_user()
    return render_template(template, **kwargs)


def admin_page(template, **kwargs):
    """渲染管理员页面，自动检查管理员权限并注入当前用户。

    用法:
        admin_page('admin/users.html', users=users)
    等价于带 admin_required 检查的:
        user = get_current_user()
        if not user or not user.is_admin: abort(403)
        return render_template('admin/users.html', user=user, users=users)
    """
    user = get_current_user()
    if not user or not user.is_admin:
        flash('权限不足', 'error')
        return redirect(url_for('main.home'))
    kwargs['user'] = user
    return render_template(template, **kwargs)


def redirect_with_flash(endpoint, message, category='success', **kwargs):
    """重定向并携带 flash 消息。

    用法:
        redirect_with_flash('admin.admin_users', '用户已删除', 'success')
    """
    flash(message, category)
    return redirect(url_for(endpoint, **kwargs))