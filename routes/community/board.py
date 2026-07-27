"""留言板路由：创建主题、回复、删除主题/回复（含附件管理）。"""

import json
import os
import secrets
import datetime

from flask import request, abort
from werkzeug.utils import secure_filename

from core.auth import login_required, get_current_user
from core.db import get_db
from config import UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_CONTENT_LENGTH
from routes.community import community_bp
from routes.community.helpers import _respond


# 附件限制常量
MAX_FILE_COUNT = 5
MAX_FILE_SIZE = MAX_CONTENT_LENGTH  # 100MB


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
    attachment_info = []
    try:
        topic = conn.execute("SELECT id, is_active FROM board_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic or not topic['is_active']:
            return _respond('留言板不存在或已关闭', 'error')

        # 处理多附件上传
        attachment_files = request.files.getlist('attachments')
        if len(attachment_files) > MAX_FILE_COUNT:
            return _respond(f'最多只能上传 {MAX_FILE_COUNT} 个文件', 'error')

        for file in attachment_files:
            if file and file.filename:
                # 检查文件大小（通过读取 seek 到末尾获取准确大小）
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > MAX_FILE_SIZE:
                    return _respond(f'文件 {file.filename} 超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制', 'error')

                # 检查文件类型
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
                if ext not in ALLOWED_EXTENSIONS:
                    return _respond(f'不支持的文件类型: .{ext}，允许: {", ".join(sorted(ALLOWED_EXTENSIONS))}', 'error')

                # 生成安全文件名
                safe_prefix = secrets.token_hex(8)
                clean_name = secure_filename(file.filename) or 'file'
                safe_name = safe_prefix + '_' + clean_name
                save_path = os.path.join(UPLOAD_DIR, safe_name)
                file.save(save_path)

                # 记录文件元信息（类型、大小、原始文件名）
                attachment_info.append({
                    'filename': safe_name,
                    'original_name': clean_name,
                    'file_type': ext,
                    'size_bytes': file_size
                })

        # 存储为JSON数组
        attachment_data = json.dumps(attachment_info) if attachment_info else None

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO board_replies (topic_id, user_id, content, attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (topic_id, user['id'], content, attachment_data, now)
        )
        conn.commit()
        return _respond('回复成功', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        # 数据库写入失败时清理已上传的附件
        for info in attachment_info:
            filepath = os.path.join(UPLOAD_DIR, info['filename'])
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
        # 级联删除前清理附件文件（兼容新旧格式）
        replies = conn.execute("SELECT attachment FROM board_replies WHERE topic_id = ?", (topic_id,)).fetchall()
        for r in replies:
            if r['attachment']:
                try:
                    parsed = json.loads(r['attachment'])
                    if isinstance(parsed, list):
                        # 新格式：字典数组
                        if parsed and isinstance(parsed[0], dict):
                            filenames = [item['filename'] for item in parsed]
                        else:
                            # 旧格式：字符串数组
                            filenames = parsed
                    elif isinstance(parsed, str):
                        filenames = [parsed]
                    else:
                        filenames = []
                except (json.JSONDecodeError, TypeError):
                    filenames = [r['attachment']] if isinstance(r['attachment'], str) else []
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
            abort(404)

        if not user['is_admin'] and reply['user_id'] != user['id']:
            abort(403)

        # 删除附件文件（兼容新旧格式）
        if reply['attachment']:
            try:
                parsed = json.loads(reply['attachment'])
                if isinstance(parsed, list):
                    # 新格式：字典数组
                    if parsed and isinstance(parsed[0], dict):
                        filenames = [item['filename'] for item in parsed]
                    else:
                        # 旧格式：字符串数组
                        filenames = parsed
                elif isinstance(parsed, str):
                    filenames = [parsed]
                else:
                    filenames = []
            except (json.JSONDecodeError, TypeError):
                filenames = [reply['attachment']] if isinstance(reply['attachment'], str) else []

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
        try:
            conn.rollback()
        except Exception:
            pass
        return _respond('删除失败', 'error')
    finally:
        conn.close()
