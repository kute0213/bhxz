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


def _wmic_temperature(temperature_class):
    """通过 WMI 获取温度，返回摄氏度或 None。temperature_class 如 'MSAcpi_ThermalZoneTemperature'。"""
    import subprocess
    # 用 CurrentTemperature 或 CurrentReading 两种字段名
    if temperature_class == 'MSAcpi_ThermalZoneTemperature':
        field = 'CurrentTemperature'
    else:
        field = 'CurrentReading'
    result = subprocess.run(
        ['wmic', '/namespace:\\\\root\\wmi', 'path', temperature_class, 'get', field],
        capture_output=True, text=True, timeout=5,
        encoding='utf-8', errors='replace',
    )
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    # 跳过表头，取第一个数值
    for line in lines:
        if line.lower() == field.lower():
            continue
        try:
            val = int(line)
            # 单位是 0.1 开尔文 → 摄氏度
            celsius = val / 10.0 - 273.15
            if 0 < celsius < 150:  # 合理范围校验
                return round(celsius, 1)
        except (ValueError, TypeError):
            continue
    return None


def _powershell_temperature():
    """通过 PowerShell 获取 MSAcpi_ThermalZoneTemperature，返回摄氏度或 None。"""
    import subprocess
    script = (
        'Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature '
        '| Select-Object -ExpandProperty CurrentTemperature'
    )
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command', script],
        capture_output=True, text=True, timeout=5,
        encoding='utf-8', errors='replace',
    )
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                val = int(line)
                celsius = val / 10.0 - 273.15
                if 0 < celsius < 150:
                    return round(celsius, 1)
            except (ValueError, TypeError):
                continue
    return None


def _get_cpu_temperature(psutil, platform):
    """跨平台获取 CPU 温度，返回摄氏度或 None。"""
    system = platform.system()

    # 1. psutil 原生传感器（Linux / WSL）
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            # 优先取 coretemp（Intel），其次 k10temp（AMD），然后常见名称
            for key in ('coretemp', 'k10temp', 'cpu_thermal', 'acpitz', 'cpu-thermal', 'soc-thermal'):
                if key in temps:
                    return round(temps[key][0].current, 1)
            # 兜底：取第一个非空传感器
            for key in temps:
                entries = temps[key]
                if entries:
                    return round(entries[0].current, 1)
    except Exception:
        pass

    # 2. Windows — 多策略获取
    if system == 'Windows':
        # 2a. WMI MSAcpi_ThermalZoneTemperature（Windows 10 最可靠）
        try:
            val = _wmic_temperature('MSAcpi_ThermalZoneTemperature')
            if val is not None:
                return val
        except Exception:
            pass

        # 2b. WMI Win32_TemperatureProbe（旧版兼容）
        try:
            val = _wmic_temperature('Win32_TemperatureProbe')
            if val is not None:
                return val
        except Exception:
            pass

        # 2c. PowerShell 兜底
        try:
            val = _powershell_temperature()
            if val is not None:
                return val
        except Exception:
            pass

        # 2d. 最后尝试: wmic /namespace 旧语法
        try:
            import subprocess
            result = subprocess.run(
                ['wmic', '/namespace:\\\\root\\wmi', 'path', 'MSAcpi_ThermalZoneTemperature',
                 'get', 'CurrentTemperature', '/format:csv'],
                capture_output=True, text=True, timeout=5,
                encoding='utf-8', errors='replace',
            )
            for line in result.stdout.strip().splitlines():
                parts = line.strip().split(',')
                for p in parts:
                    p = p.strip()
                    if p and p != 'CurrentTemperature':
                        try:
                            val = int(p)
                            celsius = val / 10.0 - 273.15
                            if 0 < celsius < 150:
                                return round(celsius, 1)
                        except (ValueError, TypeError):
                            continue
        except Exception:
            pass

    # 3. macOS — 通过 sysctl 获取
    if system == 'Darwin':
        try:
            import subprocess
            result = subprocess.run(
                ['sysctl', '-n', 'machdep.xcpm.cpu_thermal_level'],
                capture_output=True, text=True, timeout=5,
                encoding='utf-8', errors='replace',
            )
            if result.returncode == 0 and result.stdout.strip():
                val = int(result.stdout.strip())
                # 0-127 scale, approximate to 0-100°C
                if val > 0:
                    return round(100.0 - (val / 127.0 * 100.0), 1)
        except Exception:
            pass

    return None