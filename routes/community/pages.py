"""社区页面路由：首页渲染、附件下载。"""

import json

from flask import render_template, send_from_directory, abort

from core.auth import get_current_user
from core.db import get_db
from config import UPLOAD_DIR
from routes.community import community_bp


@community_bp.route('/community')
def community_page():
    user = get_current_user()
    conn = get_db()

    # ---- 投票：批量查询避免 N+1 ----
    poll_rows = conn.execute(
        "SELECT * FROM polls ORDER BY id DESC"
    ).fetchall()

    polls = []
    if poll_rows:
        poll_ids = [p['id'] for p in poll_rows]

        # 一次性获取所有投票的选项
        placeholders = ','.join('?' * len(poll_ids))
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

    # ---- 留言板：批量查询回复避免 N+1 ----
    topic_rows = conn.execute("""
        SELECT t.*, u.username,
               (SELECT COUNT(*) FROM board_replies r WHERE r.topic_id = t.id) AS reply_count
        FROM board_topics t
        JOIN users u ON t.user_id = u.id
        ORDER BY t.id DESC
    """).fetchall()
    board_topics = [dict(r) for r in topic_rows]

    if board_topics:
        topic_ids = [t['id'] for t in board_topics]
        placeholders = ','.join('?' * len(topic_ids))

        # 一次性查询所有 topic 的最近 50 条回复，按 topic 分组
        # 使用窗口函数 row_number() 限定每个 topic 的回复数
        reply_rows = conn.execute(
            f"""
            SELECT r.*, u.username
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY topic_id ORDER BY id DESC) AS rn
                FROM board_replies
                WHERE topic_id IN ({placeholders})
            ) r
            JOIN users u ON r.user_id = u.id
            WHERE r.rn <= 50
            ORDER BY r.topic_id DESC, r.id DESC
            """,
            topic_ids,
        ).fetchall()

        replies_by_topic = {}
        for r in reply_rows:
            r_dict = dict(r)
            r_dict.pop('rn', None)
            # 解析附件：兼容 JSON 数组格式和旧的字符串格式
            if r_dict.get('attachment'):
                try:
                    parsed = json.loads(r_dict['attachment'])
                    r_dict['attachment'] = [parsed] if isinstance(parsed, str) else parsed
                except (json.JSONDecodeError, TypeError):
                    r_dict['attachment'] = [r_dict['attachment']]
            replies_by_topic.setdefault(r_dict['topic_id'], []).append(r_dict)

        for topic in board_topics:
            topic['replies'] = replies_by_topic.get(topic['id'], [])

    conn.close()

    return render_template(
        'community.html',
        user=user,
        polls=polls,
        board_topics=board_topics
    )


# ---------------------------------------------------------------------------
# 文件下载
# ---------------------------------------------------------------------------

@community_bp.route('/uploads/<path:filename>')
def download_attachment(filename):
    if '..' in filename or filename.startswith('/'):
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)
