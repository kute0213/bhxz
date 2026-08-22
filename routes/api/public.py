"""公开 API 路由：性能监控、统计数据、大喇叭音频列表。"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from core.db import get_db
from services.monitoring import (
    get_cpu_usage, get_cpu_temperature, get_memory_info, get_system_info
)
from services import music_service

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ---------------------------------------------------------------------------
# 性能监控
# ---------------------------------------------------------------------------

@api_bp.route('/performance')
def api_performance():
    """获取系统性能数据（CPU、内存、温度、运行时间）。公开访问。"""
    return jsonify({
        'cpu_usage': get_cpu_usage(),
        'cpu_temp': get_cpu_temperature(),
        'memory': get_memory_info(),
        'system': get_system_info(),
        'timestamp': datetime.now(timezone.utc).astimezone().strftime(
            '%Y-%m-%d %H:%M:%S %z'
        ),
    })


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
# 大喇叭音频
# ---------------------------------------------------------------------------

@api_bp.route('/music/list')
def api_music_list():
    """获取所有公开的大喇叭音频列表（游戏内大喇叭使用，无需登录）。

    返回每个音频的播放链接（m3u8）。链接同时提供相对路径与基于当前
    请求 Host 的绝对地址，游戏端可任选其一拼接。
    """
    musics = music_service.get_public_musics()
    base = request.host_url.rstrip('/')
    items = []
    for m in musics:
        items.append({
            'id': m['id'],
            'title': m['title'],
            'username': m['username'],
            'created_at': m['created_at'],
            'url': f'/music/{m["id"]}.m3u8',
            'url_absolute': f'{base}/music/{m["id"]}.m3u8',
        })
    return jsonify({'success': True, 'count': len(items), 'musics': items})


