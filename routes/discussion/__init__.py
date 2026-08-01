"""讨论蓝图包：帖子列表、发帖、回复、管理。"""

from flask import Blueprint

discussion_bp = Blueprint('discussion', __name__, template_folder='../../templates/discussion')

# 导入子模块以注册路由
from routes.discussion import pages  # noqa: E402,F401
from routes.discussion import api    # noqa: E402,F401