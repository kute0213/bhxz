"""全站搜索蓝图包：独立搜索页与搜索 API。"""

from flask import Blueprint

search_bp = Blueprint('search', __name__)

# 导入子模块以注册路由（使用普通 import，避免 fromlist 循环导入反模式）
import routes.search.pages  # noqa: E402,F401
import routes.search.api    # noqa: E402,F401
