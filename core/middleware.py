"""请求中间件 —— 公共文件服务、请求钩子注册。

设计原则：所有请求钩子在此模块集中管理，避免在 app.py 中散落。
"""

from flask import request, session
from werkzeug.exceptions import HTTPException

from core.logger import log
from services.ip import get_client_ip

# 跳过公共文件服务的路径前缀（这些路径由 Flask 蓝图处理）
ROUTE_PREFIXES = (
    '/static/', '/admin', '/api/', '/cmd/',
    '/scheduled', '/community', '/docs',
    '/login', '/register', '/logout', '/settings', '/health',
    '/music', '/sitemap.xml',
)


# ---------------------------------------------------------------------------
# 安全响应标头（Security Headers）
# ---------------------------------------------------------------------------
# 全站安全标头统一在此集中配置，并通过 after_request 钩子下发，方便调试与维护。
# 所有标头对 HTML 页面、JSON API、SSE 流与静态资源统一生效。
#
# —— 为「不误伤站点自身功能」所做的取舍（勿随意收紧，否则会锁死自己）——
#   1) CSP script-src 保留 'unsafe-inline'：全站 14+ 个模板使用内联事件属性
#      （onclick/onsubmit/onchange 等）与内联初始化 <script>（登录/注册/上传/
#      文档/首页等），在迁移为外置脚本 + 哈希前不可移除；
#   2) CSP img-src 放行 https:：指南/帖子封面等允许填写外部图片 URL；
#   3) CSP 不启用 upgrade-insecure-requests / COEP：避免 HTTP 部署模式
#      下静态资源与 HLS(blob worker) 被强制升级/限制而无法加载；
#   4) HSTS 仅对 HTTPS 请求下发：HTTP 部署下若强制 HSTS，浏览器会拒绝访问。
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' blob:; "
    "media-src 'self' blob:; "
    "worker-src 'self' blob:; "
    "child-src 'self' blob:; "
    "frame-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'"
)

# 浏览器功能权限：默认全部拒绝（空列表 = 禁止），仅放行本域剪贴板写入（复制链接按钮）。
PERMISSIONS_POLICY = (
    "geolocation=(), camera=(), microphone=(), payment=(), usb=(), "
    "magnetometer=(), gyroscope=(), accelerometer=(), clipboard-write=(self)"
)

# HSTS：一年 + 含子域。preload 需要官方站点登记，故不写入以免难以撤销。
HSTS_POLICY = "max-age=31536000; includeSubDomains"


def _set_security_headers(response):
    """为每个响应统一写入安全标头（after_request 钩子）。

    放在 after_request 而非 before_request：即使请求被提前终止（404/403 错误页、
    公共文件命中）也能完整下发标头；使用 setdefault 保留个别路由自定义的标头。
    """
    # ---- 基础防护：防 MIME 嗅探 / 防点击劫持 / 防 Referer 泄露 ----
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')

    # ---- 浏览器功能权限 ----
    response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)

    # ---- 跨源隔离 ----
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')

    # ---- 内容安全策略 ----
    response.headers.setdefault('Content-Security-Policy', CSP_POLICY)

    # ---- 强制 HTTPS：仅 HTTPS 请求下发，避免 HTTP 部署被强制升级而无法访问 ----
    if request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', HSTS_POLICY)

    return response


def _ssl_redirect(response):
    """当 ENABLE_SSL 开启且请求为 HTTP 时，301 跳转到 HTTPS 相同 URL。"""
    import os
    enable_ssl = os.environ.get('ENABLE_SSL', '0').lower() in ('1', 'true', 'yes', 'on')
    if enable_ssl and not request.is_secure and request.method in ('GET', 'HEAD'):
        from werkzeug.urls import url_parse
        parsed = url_parse(request.url)
        if parsed.scheme != 'https':
            https_url = request.url.replace('http://', 'https://', 1)
            from flask import redirect
            return redirect(https_url, code=301)
    return response


def register_hooks(app, try_serve_public):
    """注册所有请求钩子。

    Args:
        app: Flask 应用实例
        try_serve_public: 公共文件服务函数（由 routes.public 提供）
    """

    @app.before_request
    def csrf_check_hook():
        """全站 CSRF 防护（除 /api/* 和 /cmd/* 外所有 POST/PUT/DELETE/PATCH 请求）。"""
        from core.csrf import csrf_protect
        csrf_protect()

    @app.before_request
    def serve_public_files_hook():
        """优先检查公共静态文件，避免与蓝图路由冲突。"""
        path = request.path
        if path.startswith(ROUTE_PREFIXES):
            return None
        try:
            resp = try_serve_public(path.lstrip('/'))
            if resp is not None:
                return resp
        except HTTPException:
            raise
        except Exception:
            pass
        return None

    # 统一为所有响应写入安全标头（在 before_request 之后注册，顺序无关紧要）
    app.after_request(_set_security_headers)

    # HTTPS 强制跳转（在安全标头之后注册，确保跳转优先）
    app.after_request(_ssl_redirect)

    # 统一记录 403 授权失败日志，避免在每个路由中重复写 log()
    @app.after_request
    def log_403_response(response):
        if response.status_code == 403:
            user = session.get('username', 'anonymous')
            log('Auth', f'403 授权拒绝', username=user,
                ip=get_client_ip(), path=request.path, method=request.method)
        return response
