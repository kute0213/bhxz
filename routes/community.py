import datetime
import json
import os
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, abort
from werkzeug.utils import secure_filename
from core.auth import login_required, get_current_user
from core.database import get_db
from config import REGISTER_VERIFY_CODE, UPLOAD_DIR

community_bp = Blueprint('community', __name__)


# ---------------------------------------------------------------------------
# 辅助函数：统一处理 AJAX / 表单响应
# ---------------------------------------------------------------------------

def _is_ajax():
    """检测是否为 AJAX 或 JSON 请求"""
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.is_json
            or 'application/json' in request.headers.get('Accept', ''))


def _respond(message, category='success'):
    """统一响应：AJAX 返回 JSON，否则 flash + redirect"""
    redirect_url = url_for('community.community_page')
    if _is_ajax():
        response = jsonify({
            'success': category == 'success',
            'message': message,
            'redirect': redirect_url
        })
        response.headers['X-Redirect'] = redirect_url
        return response
    flash(message, category)
    return redirect(redirect_url)


# ---------------------------------------------------------------------------
# 页面渲染
# ---------------------------------------------------------------------------

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
# 投票管理
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 留言板管理
# ---------------------------------------------------------------------------

@community_bp.route('/board/create', methods=['POST'])
@login_required
def create_board_topic():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()

    if not title or len(title) > 100:
        return _respond('标题长度应为1-100字符', 'error')
    if len(description) > 500:
        return _respond('描述长度不能超过500字符', 'error')

    conn = get_db()
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO board_topics (user_id, title, description, created_at) VALUES (?, ?, ?, ?)",
            (user['id'], title, description, now)
        )
        conn.commit()
        return _respond('留言板已创建', 'success')
    except Exception:
        conn.rollback()
        return _respond('创建失败，请重试', 'error')
    finally:
        conn.close()


@community_bp.route('/board/<int:topic_id>/reply', methods=['POST'])
@login_required
def reply_board(topic_id):
    user = get_current_user()
    content = request.form.get('content', '').strip()

    if not content or len(content) > 2000:
        return _respond('内容长度应为1-2000字符', 'error')

    conn = get_db()
    topic = conn.execute("SELECT id, is_active FROM board_topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic or not topic['is_active']:
        conn.close()
        return _respond('留言板不存在或已关闭', 'error')

    # 处理多附件上传
    attachment_files = request.files.getlist('attachments')
    attachment_names = []
    for file in attachment_files:
        if file and file.filename:
            safe_prefix = secrets.token_hex(8)
            clean_name = secure_filename(file.filename) or 'file'
            safe_name = safe_prefix + '_' + clean_name
            save_path = os.path.join(UPLOAD_DIR, safe_name)
            file.save(save_path)
            attachment_names.append(safe_name)

    # 存储为JSON数组
    attachment_filename = json.dumps(attachment_names) if attachment_names else None

    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO board_replies (topic_id, user_id, content, attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (topic_id, user['id'], content, attachment_filename, now)
        )
        conn.commit()
        return _respond('回复成功', 'success')
    except Exception:
        conn.rollback()
        # 数据库写入失败时清理已上传的附件
        for fname in attachment_names:
            filepath = os.path.join(UPLOAD_DIR, fname)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        return _respond('回复失败，请重试', 'error')
    finally:
        conn.close()


@community_bp.route('/board/<int:topic_id>/delete', methods=['POST'])
@login_required
def delete_board_topic(topic_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        # 级联删除前清理附件文件
        replies = conn.execute("SELECT attachment FROM board_replies WHERE topic_id = ?", (topic_id,)).fetchall()
        for r in replies:
            if r['attachment']:
                try:
                    parsed = json.loads(r['attachment'])
                    filenames = [parsed] if isinstance(parsed, str) else parsed
                except (json.JSONDecodeError, TypeError):
                    filenames = [r['attachment']]
                for fname in filenames:
                    filepath = os.path.join(UPLOAD_DIR, fname)
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass

        # 手动级联删除回复（DuckDB 不支持 ON DELETE CASCADE）
        conn.execute("DELETE FROM board_replies WHERE topic_id = ?", (topic_id,))
        conn.execute("DELETE FROM board_topics WHERE id = ?", (topic_id,))
        conn.commit()
        return _respond('留言板已删除', 'success')
    except Exception:
        conn.rollback()
        return _respond('删除失败', 'error')
    finally:
        conn.close()


@community_bp.route('/board/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_board_reply(reply_id):
    user = get_current_user()

    conn = get_db()
    try:
        reply = conn.execute("SELECT * FROM board_replies WHERE id = ?", (reply_id,)).fetchone()
        if not reply:
            conn.close()
            abort(404)

        if not user['is_admin'] and reply['user_id'] != user['id']:
            conn.close()
            abort(403)

        # 删除附件文件（兼容JSON数组和单个字符串）
        if reply['attachment']:
            try:
                parsed = json.loads(reply['attachment'])
                filenames = [parsed] if isinstance(parsed, str) else parsed
            except (json.JSONDecodeError, TypeError):
                filenames = [reply['attachment']]

            for fname in filenames:
                filepath = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

        conn.execute("DELETE FROM board_replies WHERE id = ?", (reply_id,))
        conn.commit()
        return _respond('回复已删除', 'success')
    except Exception:
        conn.rollback()
        return _respond('删除失败', 'error')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 文件下载
# ---------------------------------------------------------------------------

@community_bp.route('/uploads/<path:filename>')
def download_attachment(filename):
    if '..' in filename or filename.startswith('/'):
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)
