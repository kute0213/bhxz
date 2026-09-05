"""游戏账号蓝图 —— 绑定 MC 账号、改密、申请注册。"""

from flask import Blueprint, render_template, request, jsonify

from core.auth import login_required, get_current_user

game_accounts_bp = Blueprint('game_accounts', __name__, url_prefix='/game-accounts')


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------

@game_accounts_bp.route('/')
@login_required
def index():
    """游戏账号功能首页。"""
    user = get_current_user()
    from services.game_accounts.binding_service import get_bound_accounts
    bound = get_bound_accounts(user['id'])
    return render_template('game_accounts/index.html', user=user, bound_accounts=bound)


# 导入子模块注册路由
from routes.game_accounts import bind       # noqa: E402,F401
from routes.game_accounts import password   # noqa: E402,F401
from routes.game_accounts import register   # noqa: E402,F401