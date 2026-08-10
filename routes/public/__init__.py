"""公开文件服务路由包。

功能：管理员可在后台配置将本地文件/目录映射到指定 URL 路径对外公开。
"""

from flask import Blueprint

public_bp = Blueprint('public', __name__)

from routes.public import files  # noqa: E402,F401
from routes.public.files import try_serve_public  # noqa: E402,F401

__all__ = ['public_bp', 'try_serve_public']