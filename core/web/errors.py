"""统一错误页 —— 全站所有 HTTP 错误共用同一模板（错误号 / 原因 / 建议）。

- register_error_handlers(app)：注册 Flask 全局错误处理器，覆盖常见 HTTP 错误码
- render_error_page()：统一错误页构建函数，供中间件（IP 封禁 / 可疑拦截）等直接调用
- 调用方可用 abort(code, description) 覆盖默认「原因」，description 未传时使用各错误码默认文案
"""

from flask import render_template

from core.auth import get_current_user

# 各错误码默认配置：(标题, 原因, 建议, 图标)
_ERROR_PAGES = {
    400: ('Bad Request', '请求格式不正确。', '请检查请求内容后重试。', 'alert-circle'),
    401: ('Unauthorized', '您尚未登录或登录状态已过期。', '请先登录后再访问该页面。', 'lock'),
    403: ('Forbidden', '您没有权限访问此页面。', '请检查账号权限，或联系管理员。', 'shield-alert'),
    404: ('Not Found', '您访问的页面不存在或已被移除。', '请检查网址是否正确，或返回首页继续浏览。', 'compass'),
    405: ('Method Not Allowed', '请求方式不被允许。', '请使用正确的方式访问。', 'ban'),
    413: ('Payload Too Large', '请求内容超出大小限制。', '请减小上传内容大小后重试。', 'file-warning'),
    429: ('Too Many Requests', '请求过于频繁。', '请稍后重试，勿频繁操作。', 'timer'),
    500: ('Internal Server Error', '服务器内部出现错误。', '请稍后重试，若持续出现请联系管理员。', 'server-crash'),
    502: ('Bad Gateway', '服务器网关异常。', '请稍后重试。', 'server-crash'),
    503: ('Service Unavailable', '服务暂时不可用。', '请稍后重试。', 'server-crash'),
    504: ('Gateway Timeout', '服务器响应超时。', '请稍后重试。', 'server-crash'),
}


def render_error_page(code, title, reason, advice, icon='alert-circle'):
    """渲染统一错误页（错误号 / 原因 / 建议），自动注入当前用户。

    用法:
        render_error_page(403, 'Forbidden', '该 IP 已被封禁', '如有疑问请联系管理员。', 'shield-alert')
    """
    return render_template(
        'error.html',
        code=code,
        title=title,
        reason=reason,
        advice=advice,
        icon=icon,
        user=get_current_user(),
    )


def _defaults(code):
    """获取指定错误码的默认配置，未注册的错误码使用通用兜底文案。"""
    return _ERROR_PAGES.get(code, ('Error', '服务器返回错误。', '请稍后重试。', 'alert-circle'))


def _handle_error(code, e):
    """错误处理器：abort(code, description) 传参可覆盖默认「原因」。"""
    from werkzeug.exceptions import HTTPException
    title, reason, advice, icon = _defaults(code)
    # 调用方通过 abort(code, description) 自定义了原因时，覆盖默认文案
    if isinstance(e, HTTPException):
        default_desc = type(e).description
        desc = e.description
        if desc and desc != default_desc:
            reason = str(desc)
    return render_error_page(code, title, reason, advice, icon), code


def register_error_handlers(app):
    """注册全局统一错误处理页面（错误号 / 原因 / 建议）。"""
    for code in _ERROR_PAGES:
        app.errorhandler(code)(lambda e, c=code: _handle_error(c, e))