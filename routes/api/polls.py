"""投票数据 API。"""

from flask import Blueprint, jsonify
from core.auth import get_current_user
from core.db import get_db

polls_bp = Blueprint('api_polls', __name__, url_prefix='/api')


@polls_bp.route('/polls')
def api_polls():
    """获取所有投票数据（含选项、投票数、百分比、当前用户投票状态）。

    使用批量查询避免 N+1 问题。
    """
    user = get_current_user()
    conn = get_db()
    try:
        poll_rows = conn.execute("SELECT * FROM polls ORDER BY id DESC").fetchall()
        polls = []

        if poll_rows:
            poll_ids = [p['id'] for p in poll_rows]
            placeholders = ','.join('?' * len(poll_ids))

            # 一次性获取所有选项
            option_rows = conn.execute(
                f"SELECT * FROM poll_options WHERE poll_id IN ({placeholders}) ORDER BY id",
                poll_ids,
            ).fetchall()
            options_by_poll = {}
            for opt in option_rows:
                options_by_poll.setdefault(opt['poll_id'], []).append(dict(opt))

            # 一次性统计每个 poll 的去重投票用户数
            vote_count_rows = conn.execute(
                f"SELECT poll_id, COUNT(DISTINCT user_id) AS c "
                f"FROM poll_votes WHERE poll_id IN ({placeholders}) "
                f"GROUP BY poll_id",
                poll_ids,
            ).fetchall()
            vote_counts = {r['poll_id']: r['c'] for r in vote_count_rows}

            # 一次性获取当前用户在所有 poll 中的投票记录
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
