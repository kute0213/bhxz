"""公开 API 路由：网站统计数据、服务器状态。"""

from flask import Blueprint, jsonify
from core.db import get_db

api_bp = Blueprint('api', __name__, url_prefix='/api')


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


# ---------------------------------------------------------------------------
# 服务器状态（基于 RCON 在线玩家追踪器，服务端每 5 秒自动更新）
# ---------------------------------------------------------------------------

@api_bp.route('/server-status')
def api_server_status():
    """获取服务器实时状态（在线玩家列表、人数、CPU、内存等）。

    数据来源：
    - 玩家数据：PlayerTracker 后台线程每 5 秒通过 RCON /list 采集并缓存。
    - 系统资源：使用 psutil 实时采集。
    前端可按需轮询此接口，无需额外更新时间提示（服务端固定周期）。
    """
    from services.rcon import player_tracker
    import psutil

    pl = player_tracker.get_player_list()

    # CPU 使用率：interval=0.1 确保首次调用返回真实值而非 0
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    # 网络：返回自开机以来的累计收发字节数（getattr 兜底，部分平台无该计数器），
    # 上行/下行速率由前端按两次轮询的差值自行换算，服务端不保存跨请求状态。
    net = getattr(psutil, 'net_io_counters', lambda: None)()
    net_sent = net.bytes_sent if net else 0
    net_recv = net.bytes_recv if net else 0

    return jsonify({
        'online': pl.online,
        'max_players': pl.max_players,
        'players': pl.players,
        'error': pl.error,
        'cpu_percent': cpu_percent,
        'memory_percent': mem.percent,
        'memory_used': mem.used,
        'memory_total': mem.total,
        'net_sent': net_sent,
        'net_recv': net_recv,
    })