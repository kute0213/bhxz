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


# 各类待审核内容的统计信息：类型键 -> (表名, 用户列, 待审核条件, 单独上限配置键, 显示名)
_PENDING_TYPES = {
    'building':   ('public_buildings', 'author_id', "status = 'pending'", 'MAX_PENDING_BUILDING', '公共建筑'),
    'guide':      ('server_guides',    'author_id', "status = 'pending'", 'MAX_PENDING_GUIDE', '服务器指南'),
    'music':      ('music',            'user_id',   'status = 1',         'MAX_PENDING_MUSIC', '大喇叭音频'),
    'background': ('backgrounds',      'user_id',   'status = 0',         'MAX_PENDING_BACKGROUND', '背景图片'),
}


def check_pending_limit(user, content_type=None) -> tuple:
    """检查用户的待审核内容是否达到上限（总量上限 + 单类型上限）。

    管理员豁免。返回 (allowed: bool, message: str)。

    content_type 为 _PENDING_TYPES 的键（building/guide/music/background）时，
    额外校验该类型的单独上限；总量与单类型上限取「先达到者」。
    任一上限设为 0 表示不限制。
    """
    if user.get('is_admin'):
        return True, ''

    from core.db import get_db
    from config import get_config_value

    conn = get_db()
    try:
        counts = {}
        for key, (table, user_col, condition, _, _) in _PENDING_TYPES.items():
            row = conn.execute(
                f'SELECT COUNT(*) AS c FROM {table} WHERE {user_col} = ? AND {condition}',
                (user['id'],),
            ).fetchone()
            counts[key] = row['c'] if row else 0
    finally:
        conn.close()

    # 总量上限
    total_limit = int(get_config_value('MAX_PENDING_CONTENT', 5) or 0)
    if total_limit > 0 and sum(counts.values()) >= total_limit:
        return False, f'您的待审核内容已达上限（共 {total_limit} 个），请等待现有内容审核通过后再发布'

    # 单类型上限
    if content_type in _PENDING_TYPES:
        _, _, _, limit_key, label = _PENDING_TYPES[content_type]
        limit = int(get_config_value(limit_key, 0) or 0)
        if limit > 0 and counts[content_type] >= limit:
            return False, f'您的{label}待审核数量已达上限（{limit} 个），请等待现有内容审核通过后再发布'

    return True, ''