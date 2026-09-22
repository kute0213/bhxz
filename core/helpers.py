"""路由辅助函数 —— 减少重复的 get_current_user() + render_template() 模式。"""

from flask import render_template, flash, redirect, url_for
from core.auth import get_current_user


def render_page(template, **kwargs):
    """渲染页面模板，自动注入当前用户。

    用法:
        render_page('settings/index.html', title='设置')
    等价于:
        user = get_current_user()
        return render_template('settings/index.html', user=user, title='设置')
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


def check_pending_limit(user) -> tuple:
    """检查用户的待审核内容是否达到上限。

    管理员豁免。返回 (allowed: bool, message: str)。
    """
    if user.get('is_admin'):
        return True, ''

    from core.db import get_db
    from config import get_config_value

    limit = get_config_value('MAX_PENDING_CONTENT', 5)
    conn = get_db()
    try:
        # 统计所有待审核内容：公共建筑、服务器指南、音频（status=1）、背景（status=0）
        pending = conn.execute(
            """
            SELECT (
                SELECT COUNT(*) FROM public_buildings WHERE author_id = ? AND status = 'pending'
            ) + (
                SELECT COUNT(*) FROM server_guides WHERE author_id = ? AND status = 'pending'
            ) + (
                SELECT COUNT(*) FROM music WHERE author_id = ? AND status = 1
            ) + (
                SELECT COUNT(*) FROM backgrounds WHERE author_id = ? AND status = 0
            ) AS total
            """,
            (user['id'], user['id'], user['id'], user['id']),
        ).fetchone()
        count = pending['total'] if pending else 0
        if count >= limit:
            return False, f'您的待审核内容已达上限（{limit} 个），请等待现有内容审核通过后再发布'
    finally:
        conn.close()

    return True, ''