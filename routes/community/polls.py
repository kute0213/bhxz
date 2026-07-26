"""投票管理路由：创建、投票、删除、启停。"""

import datetime

from flask import request, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.community import community_bp
from routes.community.helpers import _respond


@community_bp.route('/poll/create', methods=['POST'])
@login_required
def create_poll():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    options_text = request.form.get('options', '').strip()
    is_multiple = 1 if request.form.get('is_multiple') == '1' else 0

    if not title or not options_text:
        return _respond('请填写完整信息', 'error')

    options = [line.strip() for line in options_text.split('\n') if line.strip()]
    if len(options) < 2:
        return _respond('至少需要2个选项', 'error')

    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "INSERT INTO polls (title, description, is_multiple, created_at) VALUES (?, ?, ?, ?)",
            (title, description, is_multiple, now)
        )
        poll_id = cursor.lastrowid
        for opt in options:
            cursor.execute(
                "INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)",
                (poll_id, opt)
            )
        conn.commit()
        return _respond('投票已创建', 'success')
    except Exception:
        conn.rollback()
        return _respond('创建失败，请重试', 'error')
    finally:
        conn.close()


@community_bp.route('/poll/<int:poll_id>/vote', methods=['POST'])
@login_required
def vote_poll(poll_id):
    user = get_current_user()
    option_ids = request.form.getlist('option_id')

    if not option_ids:
        return _respond('请至少选择一个选项', 'error')

    conn = get_db()
    try:
        poll = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
        if not poll or not poll['is_active']:
            return _respond('投票不存在或已结束', 'error')

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 检查用户是否已投过票
        already_voted = conn.execute(
            "SELECT id FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user['id'])
        ).fetchone()
        if already_voted:
            return _respond('你已经投过票了', 'error')

        for option_id in option_ids:
            option = conn.execute(
                "SELECT id FROM poll_options WHERE id = ? AND poll_id = ?",
                (option_id, poll_id)
            ).fetchone()
            if option:
                conn.execute(
                    "INSERT OR IGNORE INTO poll_votes (poll_id, user_id, option_id, created_at) VALUES (?, ?, ?, ?)",
                    (poll_id, user['id'], option_id, now)
                )
                conn.execute(
                    "UPDATE poll_options SET vote_count = vote_count + 1 WHERE id = ?",
                    (option_id,)
                )

        conn.commit()
        return _respond('投票成功', 'success')
    except Exception:
        conn.rollback()
        return _respond('投票失败，请重试', 'error')
    finally:
        conn.close()


@community_bp.route('/poll/<int:poll_id>/delete', methods=['POST'])
@login_required
def delete_poll(poll_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        # 手动级联删除（DuckDB 不支持 ON DELETE CASCADE）
        conn.execute("DELETE FROM poll_votes WHERE poll_id = ?", (poll_id,))
        conn.execute("DELETE FROM poll_options WHERE poll_id = ?", (poll_id,))
        conn.execute("DELETE FROM polls WHERE id = ?", (poll_id,))
        conn.commit()
        return _respond('投票已删除', 'success')
    except Exception:
        conn.rollback()
        return _respond('删除失败', 'error')
    finally:
        conn.close()


@community_bp.route('/poll/<int:poll_id>/toggle', methods=['POST'])
@login_required
def toggle_poll(poll_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        poll = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
        if not poll:
            conn.close()
            abort(404)

        new_status = 0 if poll['is_active'] else 1
        conn.execute("UPDATE polls SET is_active = ? WHERE id = ?", (new_status, poll_id))
        conn.commit()
        return _respond('投票状态已更新', 'success')
    except Exception:
        conn.rollback()
        return _respond('操作失败', 'error')
    finally:
        conn.close()
