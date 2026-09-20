"""公共建筑蓝图包：公开页面与成员 API。"""

from flask import Blueprint

buildings_bp = Blueprint('buildings', __name__)

import routes.buildings.pages   # noqa: E402,F401
import routes.buildings.api     # noqa: E402,F401