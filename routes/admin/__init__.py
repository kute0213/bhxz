"""管理后台蓝图包：用户管理、模组介绍、访问日志、数据库备份、系统设置。

Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

# 导入子模块以注册路由
from routes.admin import pages       # noqa: E402,F401
from routes.admin import users       # noqa: E402,F401
from routes.admin import mod_intros   # noqa: E402,F401
from routes.admin import guides       # noqa: E402,F401
from routes.admin import guide_bans   # noqa: E402,F401
from routes.admin import logs         # noqa: E402,F401
from routes.admin import backup       # noqa: E402,F401
from routes.admin import settings     # noqa: E402,F401
