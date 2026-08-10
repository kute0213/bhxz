"""文档页面路由包。"""

from flask import Blueprint

docs_bp = Blueprint('docs', __name__)

from routes.docs import pages  # noqa: E402,F401