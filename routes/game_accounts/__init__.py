"""游戏账号蓝图 —— 仅保留申请注册 MC 账号功能。"""

from flask import Blueprint, render_template

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
    return render_template('game_accounts/index.html', user=user)


# 导入子模块注册路由
from routes.game_accounts import register   # noqa: E402,F401