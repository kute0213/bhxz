"""公开 API 路由：性能监控、统计数据。"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify
from core.db import get_db
from services.monitoring import performance_tracker
from services.rcon import player_tracker
from services.rcon.mspt_tracker import mspt_tracker

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
        'mspt': _get_mspt_data(),
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


def _get_mspt_data():
    """获取 MSPT/TPS 数据（用于前端渲染）。"""
    md = mspt_tracker.get_mspt_data()
    if md.error:
        return {
            'connected': False,
            'error': md.error,
            'mspt_current': 0,
            'tps_5s': 0, 'tps_10s': 0, 'tps_1m': 0, 'tps_5m': 0, 'tps_15m': 0,
            'tick_min_10s': 0, 'tick_med_10s': 0, 'tick_p95_10s': 0, 'tick_max_10s': 0,
            'tick_min_1m': 0, 'tick_med_1m': 0, 'tick_p95_1m': 0, 'tick_max_1m': 0,
            'cpu_system': 0, 'cpu_process': 0,
        }
    return {
        'connected': True,
        'error': None,
        'mspt_current': md.mspt_current,
        'tps_5s': md.tps_5s, 'tps_10s': md.tps_10s,
        'tps_1m': md.tps_1m, 'tps_5m': md.tps_5m, 'tps_15m': md.tps_15m,
        'tick_min_10s': md.tick_min_10s, 'tick_med_10s': md.tick_med_10s,
        'tick_p95_10s': md.tick_p95_10s, 'tick_max_10s': md.tick_max_10s,
        'tick_min_1m': md.tick_min_1m, 'tick_med_1m': md.tick_med_1m,
        'tick_p95_1m': md.tick_p95_1m, 'tick_max_1m': md.tick_max_1m,
        'cpu_system': md.cpu_system, 'cpu_process': md.cpu_process,
        'updated_at': md.updated_at,
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


