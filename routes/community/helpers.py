"""社区路由辅助函数：统一处理 AJAX / 表单响应。"""

from flask import request, url_for, jsonify, flash, redirect


def _is_ajax():
    """检测是否为 AJAX 或 JSON 请求"""
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.is_json
            or 'application/json' in request.headers.get('Accept', ''))


def _respond(message, category='success', redirect_to=None):
    """统一响应：AJAX 返回 JSON，否则 flash + redirect"""
    redirect_url = redirect_to or url_for('community.community_page')
    if _is_ajax():
        response = jsonify({
            'success': category == 'success',
            'message': message,
            'redirect': redirect_url
        })
        response.headers['X-Redirect'] = redirect_url
        return response
    flash(message, category)
    return redirect(redirect_url)
