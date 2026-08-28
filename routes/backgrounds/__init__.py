"""背景图片路由：上传、列表、审核。

背景图片上传后需要管理员审核才能显示，所有用户可上传。
"""

from flask import Blueprint

backgrounds_bp = Blueprint('backgrounds', __name__)

# 导入子模块以注册路由
from routes.backgrounds import pages  # noqa: E402,F401
