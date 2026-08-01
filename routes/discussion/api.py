"""讨论 API 路由：回复、删除、置顶、锁定等操作。"""

import json
import datetime
import os
import secrets

from flask import request, abort, url_for, jsonify
from werkzeug.utils import secure_filename

from core.auth import login_required, get_current_user
from core.db import get_db
from config import UPLOAD_DIR, get_config_value
from routes.discussion import discussion_bp
from routes.community.helpers import _respond
from services.logger import log


@discussion_bp.route('/discussion/<int:topic_id>/reply', methods=['POST'])
@login_required
def reply(topic_id):
    """回复帖子。"""
    user = get_current_user()
    content = request.form.get('content', '').strip()

    if not content or len(content) > 10000:
        return _respond('内容长度应为 1-10000 字符', 'error', redirect_to=url_for('discussion.detail', topic_id=topic_id))

    conn = get_db()
    attachment_names = []
    try:
        topic = conn.execute(
            "SELECT id, is_locked FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            return _respond('帖子不存在', 'error', redirect_to=url_for('discussion.list'))
        if topic['is_locked']:
            return _respond('帖子已锁定，无法回复', 'error', redirect_to=url_for('discussion.detail', topic_id=topic_id))

        # 处理附件上传
        attachment_files = request.files.getlist('attachments')
        for file in attachment_files:
            if file and file.filename:
                safe_prefix = secrets.token_hex(8)
                clean_name = secure_filename(file.filename) or 'file'
                safe_name = safe_prefix + '_' + clean_name
                save_path = os.path.join(UPLOAD_DIR, safe_name)
                file.save(save_path)
                attachment_names.append(safe_name)

        attachment_json = json.dumps(attachment_names) if attachment_names else None

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO discussion_replies (topic_id, user_id, content, attachment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, user['id'], content, attachment_json, now, now)
        )
        # 更新帖子 updated_at
        conn.execute("UPDATE discussion_topics SET updated_at = ? WHERE id = ?", (now, topic_id))
        conn.commit()
        log('Discussion', '回复帖子', user_id=user['id'], username=user['username'],
            topic_id=topic_id, ip=request.remote_addr)
        return _respond('回复成功', 'success', redirect_to=url_for('discussion.detail', topic_id=topic_id))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # 清理附件
        for fname in attachment_names:
            filepath = os.path.join(UPLOAD_DIR, fname)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        log('Discussion', '回复帖子失败', user_id=user['id'], username=user['username'],
            topic_id=topic_id, ip=request.remote_addr)
        return _respond('回复失败，请稍后重试', 'error', redirect_to=url_for('discussion.detail', topic_id=topic_id))
    finally:
        conn.close()


@discussion_bp.route('/discussion/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_reply(reply_id):
    """删除回复。"""
    user = get_current_user()

    conn = get_db()
    try:
        reply = conn.execute("SELECT * FROM discussion_replies WHERE id = ?", (reply_id,)).fetchone()
        if not reply:
            abort(404)

        topic = conn.execute("SELECT user_id FROM discussion_topics WHERE id = ?", (reply['topic_id'],)).fetchone()

        # 作者、帖子作者、管理员可删除
        if reply['user_id'] != user['id'] and not user.get('is_admin') and (not topic or topic['user_id'] != user['id']):
            abort(403)

        # 清理附件
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

        conn.execute("DELETE FROM discussion_replies WHERE id = ?", (reply_id,))
        # 更新帖子 updated_at
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("UPDATE discussion_topics SET updated_at = ? WHERE id = ?", (now, reply['topic_id']))
        conn.commit()
        log('Discussion', '删除回复', user_id=user['id'], username=user['username'],
            reply_id=reply_id, topic_id=reply['topic_id'], ip=request.remote_addr)
        return _respond('回复已删除', 'success', redirect_to=url_for('discussion.detail', topic_id=reply['topic_id']))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('Discussion', '删除回复失败', user_id=user['id'], username=user['username'],
            reply_id=reply_id, ip=request.remote_addr)
        return _respond('删除失败', 'error')
    finally:
        conn.close()


@discussion_bp.route('/discussion/<int:topic_id>/pin', methods=['POST'])
@login_required
def toggle_pin(topic_id):
    """置顶/取消置顶帖子。"""
    user = get_current_user()
    if not user.get('is_admin'):
        abort(403)

    conn = get_db()
    try:
        topic = conn.execute("SELECT id, is_pinned FROM discussion_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic:
            abort(404)

        new_status = 0 if topic['is_pinned'] else 1
        conn.execute("UPDATE discussion_topics SET is_pinned = ? WHERE id = ?", (new_status, topic_id))
        conn.commit()
        log('Discussion', '切换置顶', user_id=user['id'], username=user['username'],
            topic_id=topic_id, is_pinned=new_status, ip=request.remote_addr)
        return _respond('置顶状态已更新', 'success', redirect_to=url_for('discussion.detail', topic_id=topic_id))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return _respond('操作失败', 'error')
    finally:
        conn.close()


@discussion_bp.route('/discussion/<int:topic_id>/lock', methods=['POST'])
@login_required
def toggle_lock(topic_id):
    """锁定/解锁帖子。"""
    user = get_current_user()
    if not user.get('is_admin'):
        abort(403)

    conn = get_db()
    try:
        topic = conn.execute("SELECT id, is_locked FROM discussion_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic:
            abort(404)

        new_status = 0 if topic['is_locked'] else 1
        conn.execute("UPDATE discussion_topics SET is_locked = ? WHERE id = ?", (new_status, topic_id))
        conn.commit()
        log('Discussion', '切换锁定', user_id=user['id'], username=user['username'],
            topic_id=topic_id, is_locked=new_status, ip=request.remote_addr)
        return _respond('锁定状态已更新', 'success', redirect_to=url_for('discussion.detail', topic_id=topic_id))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return _respond('操作失败', 'error')
    finally:
        conn.close()


@discussion_bp.route('/discussion/<int:topic_id>/delete', methods=['POST'])
@login_required
def delete_topic(topic_id):
    """删除帖子。"""
    user = get_current_user()

    conn = get_db()
    try:
        topic = conn.execute("SELECT * FROM discussion_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic:
            abort(404)

        if topic['user_id'] != user['id'] and not user.get('is_admin'):
            abort(403)

        # 清理帖子附件
        if topic['attachment']:
            try:
                parsed = json.loads(topic['attachment'])
                filenames = [parsed] if isinstance(parsed, str) else parsed
            except (json.JSONDecodeError, TypeError):
                filenames = [topic['attachment']]
            for fname in filenames:
                filepath = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

        # 清理所有回复的附件
        replies = conn.execute("SELECT attachment FROM discussion_replies WHERE topic_id = ?", (topic_id,)).fetchall()
        for r in replies:
            if r['attachment']:
                try:
                    parsed = json.loads(r['attachment'])
                    fnames = [parsed] if isinstance(parsed, str) else parsed
                except (json.JSONDecodeError, TypeError):
                    fnames = [r['attachment']]
                for fn in fnames:
                    fp = os.path.join(UPLOAD_DIR, fn)
                    if os.path.exists(fp):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass

        conn.execute("DELETE FROM discussion_replies WHERE topic_id = ?", (topic_id,))
        conn.execute("DELETE FROM discussion_topics WHERE id = ?", (topic_id,))
        conn.commit()
        log('Discussion', '删除帖子', user_id=user['id'], username=user['username'],
            topic_id=topic_id, ip=request.remote_addr)
        return _respond('帖子已删除', 'success', redirect_to=url_for('discussion.list'))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('Discussion', '删除帖子失败', user_id=user['id'], username=user['username'],
            topic_id=topic_id, ip=request.remote_addr)
        return _respond('删除失败', 'error')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 回复分段加载 & 实时刷新 API
# ---------------------------------------------------------------------------

@discussion_bp.route('/discussion/<int:topic_id>/api/replies')
def api_get_replies(topic_id):
    """API: 分页获取回复（用于前端分段加载）。"""
    page = request.args.get('page', 1, type=int)
    per_page = get_config_value('REPLIES_PER_PAGE', 10)

    if page < 1:
        page = 1

    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM discussion_replies WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()['c']

        offset = (page - 1) * per_page
        rows = conn.execute(
            """
            SELECT r.id, r.content, r.attachment, r.created_at, r.user_id, u.username
            FROM discussion_replies r
            JOIN users u ON r.user_id = u.id
            WHERE r.topic_id = ?
            ORDER BY r.id ASC
            LIMIT ? OFFSET ?
            """,
            (topic_id, per_page, offset)
        ).fetchall()

        replies_list = []
        for r in rows:
            rd = dict(r)
            # 解析附件
            if rd.get('attachment'):
                try:
                    parsed = json.loads(rd['attachment'])
                    rd['attachment'] = [parsed] if isinstance(parsed, str) else parsed
                except (json.JSONDecodeError, TypeError):
                    rd['attachment'] = [rd['attachment']]
            else:
                rd['attachment'] = []
            replies_list.append(rd)

        return jsonify({
            'success': True,
            'replies': replies_list,
            'has_more': (page * per_page) < total,
            'total': total,
        })
    finally:
        conn.close()


@discussion_bp.route('/discussion/<int:topic_id>/api/new-replies')
def api_get_new_replies(topic_id):
    """API: 获取最新回复（仅返回比 last_id 大的回复，用于实时刷新）。"""
    last_id = request.args.get('last_id', 0, type=int)

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.content, r.attachment, r.created_at, r.user_id, u.username
            FROM discussion_replies r
            JOIN users u ON r.user_id = u.id
            WHERE r.topic_id = ? AND r.id > ?
            ORDER BY r.id ASC
            """,
            (topic_id, last_id)
        ).fetchall()

        replies_list = []
        for r in rows:
            rd = dict(r)
            if rd.get('attachment'):
                try:
                    parsed = json.loads(rd['attachment'])
                    rd['attachment'] = [parsed] if isinstance(parsed, str) else parsed
                except (json.JSONDecodeError, TypeError):
                    rd['attachment'] = [rd['attachment']]
            else:
                rd['attachment'] = []
            replies_list.append(rd)

        return jsonify({
            'success': True,
            'replies': replies_list,
        })
    finally:
        conn.close()