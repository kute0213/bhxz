"""用户业务服务包。

所有函数均为 Flask 无关的纯业务逻辑，接收必要参数，返回 (success, data_or_error) 元组。
"""

from services.user.auth import (
    check_username_available,
    register,
    login,
    forgot_password,
)
from services.user.profile import (
    change_username,
    change_password,
    change_email,
    delete_account,
)
from services.user.admin import (
    admin_delete_user,
    admin_toggle_admin,
)

__all__ = [
    'check_username_available', 'register', 'login', 'forgot_password',
    'change_username', 'change_password', 'change_email', 'delete_account',
    'admin_delete_user', 'admin_toggle_admin',
]