"""征集路由：创建主题、回复、删除主题/回复（含附件管理）。"""

import json
import os
import secrets
import datetime

from flask import request, abort
from werkzeug.utils import secure_filename

from core.auth import login_required, get_current_user
from core.db import get_db
from config import UPLOAD_DIR
from routes.community import community_bp
from routes.community.helpers import _respond
from services.logger import log


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
        log('Board', '创建征集', user_id=user['id'], username=user['username'], title=title, ip=request.remote_addr)
        return _respond('征集已创建', 'success')
    except Exception:
        conn.rollback()
        log('Board', '创建征集失败', user_id=user['id'], username=user['username'], title=title, ip=request.remote_addr)
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
    attachment_names = []
    try:
        topic = conn.execute("SELECT id, is_active FROM board_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic or not topic['is_active']:
            return _respond('征集不存在或已关闭', 'error')

        # 处理多附件上传 (恢复旧版简单逻辑)
        attachment_files = request.files.getlist('attachments')
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

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO board_replies (topic_id, user_id, content, attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (topic_id, user['id'], content, attachment_filename, now)
        )
        conn.commit()
        log('Board', '回复征集', user_id=user['id'], username=user['username'], topic_id=topic_id, ip=request.remote_addr)
        return _respond('回复成功', 'success')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # 数据库写入失败时清理已上传的附件
        for fname in attachment_names:
            filepath = os.path.join(UPLOAD_DIR, fname)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        log('Board', '回复征集失败', user_id=user['id'], username=user['username'], topic_id=topic_id, ip=request.remote_addr)
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
        log('Board', '删除征集', user_id=user['id'], username=user['username'], topic_id=topic_id, ip=request.remote_addr)
        return _respond('征集已删除', 'success')
    except Exception:
        conn.rollback()
        log('Board', '删除征集失败', user_id=user['id'], username=user['username'], topic_id=topic_id, ip=request.remote_addr)
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
            abort(404)

        if not user['is_admin'] and reply['user_id'] != user['id']:
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
        log('Board', '删除回复', user_id=user['id'], username=user['username'], reply_id=reply_id, topic_id=reply['topic_id'], ip=request.remote_addr)
        return _respond('回复已删除', 'success')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log('Board', '删除回复失败', user_id=user['id'], username=user['username'], reply_id=reply_id, ip=request.remote_addr)
        return _respond('删除失败', 'error')
    finally:
        conn.close()
