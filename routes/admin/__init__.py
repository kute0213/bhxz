"""管理后台蓝图包：用户管理、模组介绍、访问日志、数据库备份、系统设置。

Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

# 导入子模块以注册路由。
# 注意：必须使用普通 import（而非 `from routes.admin import X`）。
# fromlist 自导入在子模块处于"导入中"状态时会抛出
# "cannot import name X from partially initialized module"，是经典的循环导入反模式。
import routes.admin.pages            # noqa: E402,F401
import routes.admin.users            # noqa: E402,F401
import routes.admin.mod_intros       # noqa: E402,F401
import routes.admin.guides           # noqa: E402,F401
import routes.admin.buildings        # noqa: E402,F401
import routes.admin.guide_bans       # noqa: E402,F401
import routes.admin.backup           # noqa: E402,F401
import routes.admin.settings         # noqa: E402,F401
import routes.admin.broadcast        # noqa: E402,F401
import routes.admin.discussion       # noqa: E402,F401
import routes.admin.music            # noqa: E402,F401
import routes.admin.backgrounds      # noqa: E402,F401
import routes.admin.logs             # noqa: E402,F401
import routes.admin.account_applications  # noqa: E402,F401
import routes.admin.firewall         # noqa: E402,F401
