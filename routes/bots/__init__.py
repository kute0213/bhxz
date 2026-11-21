"""申请假人（BOT）蓝图 —— 用户提交申请，管理员审核后由 RCON 生成。

入口：导航「服务器 → 申请假人」
功能：
  - 设置坐标（支持从在线玩家位置一键获取）
  - 设置 BOT 名称与下线时间
  - 管理员审核通过后执行生成指令；到期由统一调度器执行杀死指令
"""

import re

from flask import Blueprint, render_template, request, jsonify

from config import get_config_value
from core.auth import login_required, get_current_user
from core.shared.validation import validate_mc_username, sanitize_rcon_username
from services.content_limits import check_pending_limit
from services.bot_applications import (
    create_application,
    get_user_applications,
)
from services.rcon.client import execute_command
from services.rcon import player_tracker

bots_bp = Blueprint('bots', __name__)

# `/data get entity <玩家> Pos` 回传示例：
# XCZSS has the following entity data: [50000.39276052492d, 61.0d, -49794.751065425844d]
_POS_RE = re.compile(
    r'\[\s*(-?\d+(?:\.\d+)?)d?\s*,\s*(-?\d+(?:\.\d+)?)d?\s*,\s*(-?\d+(?:\.\d+)?)d?\s*\]'
)


def parse_pos_response(resp):
    """从 `/data get entity <玩家> Pos` 的应答中解析坐标，失败返回 None。"""
    if not resp or (isinstance(resp, str) and resp.startswith('RCON ')):
        return None
    match = _POS_RE.search(resp)
    if not match:
        return None
    return (float(match.group(1)), float(match.group(2)), float(match.group(3)))


def _online_players():
    """读取在线玩家列表（复用统一调度器维护的 player_tracker 缓存）。"""
    try:
        return list(player_tracker.get_player_list().players)
    except Exception:
        return []


@bots_bp.route('/bots/apply')
@login_required
def apply_page():
    """申请假人页面。"""
    user = get_current_user()
    my_apps = get_user_applications(user['id'])
    pending_used = sum(1 for a in my_apps if a['status'] == 'pending')
    pending_limit = int(get_config_value('BOT_PENDING_LIMIT', 2) or 0)
    return render_template(
        'bots/apply.html',
        user=user,
        my_applications=my_apps,
        pending_used=pending_used,
        pending_limit=pending_limit,
        online_players=_online_players(),
    )


@bots_bp.route('/api/bots/players')
@login_required
def api_players():
    """在线玩家列表（供搜索选择，读取 player_tracker 缓存）。"""
    q = (request.args.get('q') or '').strip().lower()
    names = [n for n in _online_players() if not q or q in n.lower()]
    return jsonify({'success': True, 'players': names})


@bots_bp.route('/api/bots/player-position', methods=['POST'])
@login_required
def api_player_position():
    """执行 `/data get entity <玩家> Pos` 并返回解析后的坐标。"""
    data = request.get_json(silent=True) or {}
    player_name = (data.get('player_name') or '').strip()

    valid, err = validate_mc_username(player_name)
    if not valid:
        return jsonify({'success': False, 'message': err}), 400

    safe_name = sanitize_rcon_username(player_name)
    if not safe_name:
        return jsonify({'success': False, 'message': '玩家名包含非法字符'}), 400

    resp = execute_command(f'/data get entity {safe_name} Pos', timeout=5)
    if not resp or (isinstance(resp, str) and resp.startswith('RCON ')):
        return jsonify({'success': False, 'message': 'RCON 执行失败，请确认服务器与 RCON 连接正常'}), 502

    coords = parse_pos_response(resp)
    if coords is None:
        return jsonify({
            'success': False,
            'message': '未能获取该玩家坐标（玩家可能不在线），请确认后重试',
        }), 404

    x, y, z = coords
    return jsonify({'success': True, 'player_name': player_name, 'x': x, 'y': y, 'z': z})


@bots_bp.route('/api/bots/apply', methods=['POST'])
@login_required
def api_apply():
    """提交假人申请（计入待审核余额，并受假人单独上限约束）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    bot_name = (data.get('bot_name') or '').strip()
    x = data.get('x')
    y = data.get('y')
    z = data.get('z')
    offline_at = (data.get('offline_at') or '').strip()

    if not bot_name or x in (None, '') or y in (None, '') or z in (None, ''):
        return jsonify({'success': False, 'message': '请填写 BOT 名称与完整坐标'}), 400
    if not offline_at:
        return jsonify({'success': False, 'message': '请设置下线时间'}), 400

    # 待审核余额（总量 + 假人单独上限，管理员豁免）
    allowed, limit_msg = check_pending_limit(user, 'bot')
    if not allowed:
        return jsonify({'success': False, 'message': limit_msg}), 400

    success, message = create_application(user['id'], bot_name, x, y, z, offline_at)
    return jsonify({'success': success, 'message': message})
