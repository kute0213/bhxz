"""主路由包：首页、登录、注册、设置、性能监控。

Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint

main_bp = Blueprint('main', __name__)

# 导入子模块以注册路由
from routes.main import pages     # noqa: E402,F401
from routes.main import auth      # noqa: E402,F401
from routes.main import settings  # noqa: E402,F401
from routes.main import media     # noqa: E402,F401
