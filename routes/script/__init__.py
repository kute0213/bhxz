"""终端控制台蓝图包：快捷命令 + 实时终端。

所有接口仅管理员可用。
Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint

script_bp = Blueprint('script', __name__)

# 导入子模块以注册路由
from routes.script import pages      # noqa: E402,F401
from routes.script import commands   # noqa: E402,F401
from routes.script import execution  # noqa: E402,F401
from routes.script import terminal   # noqa: E402,F401