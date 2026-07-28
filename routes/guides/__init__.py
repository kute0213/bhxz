"""服务器指南蓝图包：公开页面与成员API。"""

from flask import Blueprint

guides_bp = Blueprint('guides', __name__)

from routes.guides import pages  # noqa: E402,F401
from routes.guides import api    # noqa: E402,F401
