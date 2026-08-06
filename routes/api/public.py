"""公开 API 路由：性能监控、统计数据、投票数据。

合并自原 monitoring.py、stats.py、polls.py 三个文件。
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify
from core.auth import get_current_user
from core.db import get_db
from services.monitoring import (
    get_cpu_usage, get_cpu_temperature, get_memory_info, get_system_info
)

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
            'total_polls': conn.execute("SELECT COUNT(*) AS c FROM polls").fetchone()['c'],
            'total_votes': conn.execute("SELECT COUNT(*) AS c FROM poll_votes").fetchone()['c'],
            'total_board_topics': conn.execute("SELECT COUNT(*) AS c FROM board_topics").fetchone()['c'],
            'total_board_replies': conn.execute("SELECT COUNT(*) AS c FROM board_replies").fetchone()['c'],
        }
    finally:
        conn.close()
    return jsonify(stats)


# ---------------------------------------------------------------------------
# 投票数据
# ---------------------------------------------------------------------------

@api_bp.route('/polls')
def api_polls():
    """获取所有投票数据（含选项、投票数、百分比、当前用户投票状态）。"""
    user = get_current_user()
    conn = get_db()
    try:
        poll_rows = conn.execute("SELECT * FROM polls ORDER BY id DESC").fetchall()
        polls = []

        if poll_rows:
            poll_ids = [p['id'] for p in poll_rows]
            placeholders = ','.join('?' * len(poll_ids))

            option_rows = conn.execute(
                f"SELECT * FROM poll_options WHERE poll_id IN ({placeholders}) ORDER BY id",
                poll_ids,
            ).fetchall()
            options_by_poll = {}
            for opt in option_rows:
                options_by_poll.setdefault(opt['poll_id'], []).append(dict(opt))

            vote_count_rows = conn.execute(
                f"SELECT poll_id, COUNT(DISTINCT user_id) AS c "
                f"FROM poll_votes WHERE poll_id IN ({placeholders}) "
                f"GROUP BY poll_id",
                poll_ids,
            ).fetchall()
            vote_counts = {r['poll_id']: r['c'] for r in vote_count_rows}

            voted_poll_ids = set()
            if user:
                voted_rows = conn.execute(
                    f"SELECT DISTINCT poll_id FROM poll_votes "
                    f"WHERE user_id = ? AND poll_id IN ({placeholders})",
                    [user['id']] + poll_ids,
                ).fetchall()
                voted_poll_ids = {r['poll_id'] for r in voted_rows}

            for poll in poll_rows:
                poll_dict = dict(poll)
                options = options_by_poll.get(poll['id'], [])
                total_votes = vote_counts.get(poll['id'], 0)
                poll_dict['total_votes'] = total_votes
                for opt in options:
                    opt['percent'] = round(
                        (opt['vote_count'] / total_votes * 100) if total_votes > 0 else 0
                    )
                poll_dict['options'] = options
                poll_dict['user_voted'] = poll['id'] in voted_poll_ids
                polls.append(poll_dict)
    finally:
        conn.close()
    return jsonify({'polls': polls})