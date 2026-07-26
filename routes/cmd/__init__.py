"""CMD 命令控制台蓝图包：实时执行 + 一键命令管理 + MiniScript 脚本。

所有接口仅管理员可用。
Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint

cmd_bp = Blueprint('cmd', __name__)

# 导入子模块以注册路由
from routes.cmd import script     # noqa: E402,F401  （含 _admin_check，需先加载）
from routes.cmd import pages      # noqa: E402,F401
from routes.cmd import commands   # noqa: E402,F401
from routes.cmd import execution  # noqa: E402,F401
from routes.cmd import scripts    # noqa: E402,F401
