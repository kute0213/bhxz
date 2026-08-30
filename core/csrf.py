"""CSRF 防护模块。

基于 Session 的 CSRF Token 方案：
  - Token 存储在 session 中，用户首次访问时自动生成
  - 所有 POST/PUT/DELETE/PATCH 请求均需校验
  - 使用 hmac.compare_digest 进行常量时间比较，防止时序攻击
  - 不对 /api/* 路由做校验（JSON API 不依赖表单 CSRF）
  - 不对文件上传/下载等无状态路由做校验

用法：
  1. 在模板中：{{ csrf_field() }} 输出隐藏 input
  2. 在 AJAX 中：从 <meta name="csrf-token"> 读取 token，以 X-CSRF-Token 头发送
"""

import hmac
import secrets
from flask import session, request, abort, g


def get_csrf_token():
    """获取或生成 CSRF token。每次请求周期内缓存，避免重复生成。"""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def validate_csrf_token(token):
    """常量时间比较 CSRF token。"""
    stored = session.get('_csrf_token', '')
    if not stored or not token:
        return False
    return hmac.compare_digest(str(stored), str(token))


def csrf_protect():
    """before_request 钩子：对状态变更请求执行 CSRF 校验。

    - 跳过 /api/* 路由（JSON API 使用自己的鉴权方式）
    - 跳过 /cmd/* 路由（WebSocket 类操作）
    - 跳过静态文件、上传文件等 GET 请求
    - 跳过文件上传类路由（它们通过 FormData 提交，需单独处理）
    """
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return

    # 跳过 API 路由（JSON 接口，不依赖表单 CSRF）
    path = request.path
    if path.startswith('/api/'):
        return

    # 跳过 /cmd/* 路由（WebSocket 类操作）
    if path.startswith('/cmd/'):
        return

    # 获取 token：优先表单字段，其次自定义请求头
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')

    if not token or not validate_csrf_token(token):
        # AJAX 请求返回 JSON，普通请求返回 403 页面
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' \
                or request.accept_mimetypes.best == 'application/json':
            abort(403, 'CSRF 验证失败，请刷新页面重试')
        abort(403)