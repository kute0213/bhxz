"""服务器指南蓝图包：公开页面与成员API。"""

from flask import Blueprint

guides_bp = Blueprint('guides', __name__)

# 导入子模块以注册路由（使用普通 import，避免 fromlist 循环导入反模式）
import routes.guides.pages  # noqa: E402,F401
import routes.guides.api    # noqa: E402,F401
