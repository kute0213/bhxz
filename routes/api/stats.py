"""网站统计数据 API。"""

from flask import Blueprint, jsonify
from core.database import get_db

stats_bp = Blueprint('api_stats', __name__, url_prefix='/api')


@stats_bp.route('/stats')
def api_stats():
    """获取网站统计数据（用户数、投票数、留言数等）"""
    conn = get_db()
    stats = {
        'total_users': conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c'],
        'total_polls': conn.execute("SELECT COUNT(*) AS c FROM polls").fetchone()['c'],
        'total_votes': conn.execute("SELECT COUNT(*) AS c FROM poll_votes").fetchone()['c'],
        'total_board_topics': conn.execute("SELECT COUNT(*) AS c FROM board_topics").fetchone()['c'],
        'total_board_replies': conn.execute("SELECT COUNT(*) AS c FROM board_replies").fetchone()['c'],
    }
    conn.close()
    return jsonify(stats)
