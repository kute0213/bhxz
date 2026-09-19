"""文档页面路由包。"""

from flask import Blueprint

docs_bp = Blueprint('docs', __name__)

# 导入子模块以注册路由（使用普通 import，避免 fromlist 循环导入反模式）
import routes.docs.pages  # noqa: E402,F401