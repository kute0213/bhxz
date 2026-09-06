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
    import platform

    pl = player_tracker.get_player_list()

    # CPU 使用率：interval=0.1 确保首次调用返回真实值而非 0
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    # CPU 温度（全平台兼容）
    cpu_temp = _get_cpu_temperature(psutil, platform)

    return jsonify({
        'online': pl.online,
        'max_players': pl.max_players,
        'players': pl.players,
        'error': pl.error,
        'cpu_percent': cpu_percent,
        'cpu_temp': cpu_temp,
        'memory_percent': mem.percent,
        'memory_used': mem.used,
        'memory_total': mem.total,
    })


def _get_cpu_temperature(psutil, platform):
    """跨平台获取 CPU 温度，返回摄氏度或 None。"""
    # 1. psutil 原生传感器（Linux）
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            # 优先取 coretemp（Intel），其次 k10temp（AMD），最后任意第一个
            for key in ('coretemp', 'k10temp', 'cpu_thermal', 'acpitz'):
                if key in temps:
                    return round(temps[key][0].current, 1)
            # 兜底：取第一个传感器
            for key in temps:
                return round(temps[key][0].current, 1)
    except Exception:
        pass

    # 2. Windows — 通过 WMI 获取
    if platform.system() == 'Windows':
        try:
            import subprocess
            result = subprocess.run(
                ['wmic', 'path', 'Win32_TemperatureProbe', 'get', 'CurrentReading'],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            if len(lines) > 1 and lines[1].isdigit():
                # 单位是 0.1 开尔文，转换为摄氏度
                return round(int(lines[1]) / 10.0 - 273.15, 1)
        except Exception:
            pass

    # 3. macOS — 通过 sysctl 获取
    if platform.system() == 'Darwin':
        try:
            import subprocess
            result = subprocess.run(
                ['sysctl', '-n', 'machdep.xcpm.cpu_thermal_level'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                val = int(result.stdout.strip())
                # 0-127 scale, approximate to 0-100°C
                if val > 0:
                    return round(100.0 - (val / 127.0 * 100.0), 1)
        except Exception:
            pass

    return None