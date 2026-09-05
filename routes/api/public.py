"""公开 API 路由：性能监控、统计数据。"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify
from core.db import get_db
from services.monitoring import performance_tracker
from services.rcon import player_tracker

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ---------------------------------------------------------------------------
# 性能监控（从后台缓存读取，每 5 秒自动更新）
# ---------------------------------------------------------------------------

@api_bp.route('/performance')
def api_performance():
    """获取系统性能数据（CPU、内存、温度、运行时间）。公开访问。

    数据由后台 PerformanceTracker 每 5 秒自动采集并缓存。
    """
    perf = performance_tracker.get_performance_data()

    return jsonify({
        'cpu_usage': perf.cpu_usage,
        'cpu_temp': perf.cpu_temp,
        'memory': perf.memory,
        'system': perf.system,
        'players': _get_player_data(),
        'timestamp': perf.timestamp or datetime.now(timezone.utc).astimezone().strftime(
            '%Y-%m-%d %H:%M:%S %z'
        ),
    })


def _get_player_data():
    """获取在线玩家列表数据（用于前端渲染）。"""
    pl = player_tracker.get_player_list()
    if pl.error:
        return {'online': 0, 'max': 0, 'list': [], 'connected': False, 'error': pl.error}
    return {
        'online': pl.online,
        'max': pl.max_players,
        'list': pl.players,
        'connected': True,
        'error': None,
        'updated_at': pl.updated_at,
    }


# ---------------------------------------------------------------------------
# 网站统计数据
# ---------------------------------------------------------------------------

@api_bp.route('/stats')
def api_stats():
    """获取网站统计数据（用户数、投票数、留言数等）"""
    conn = get_db()
    try:
        stats = {
            'total_users': conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c'],
        }
    finally:
        conn.close()
    return jsonify(stats)


