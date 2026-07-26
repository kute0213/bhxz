"""定时任务管理蓝图包：任务 CRUD、启用/禁用、手动触发、执行日志查看。

Blueprint 在此创建，子模块从本包导入 bp 后用 @bp.route 注册路由。
"""

from flask import Blueprint, abort

from core.auth import get_current_user

scheduled_bp = Blueprint('scheduled', __name__)


def _admin_check():
    """管理员校验：非管理员返回 403。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)
    return user


# 导入子模块以注册路由
from routes.scheduled import tasks  # noqa: E402,F401
from routes.scheduled import logs   # noqa: E402,F401
