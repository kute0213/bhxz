"""社区蓝图包：文件下载。

Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint

community_bp = Blueprint('community', __name__)

# 导入子模块以注册路由
from routes.community import pages    # noqa: E402,F401
