"""讨论页面路由：帖子列表、详情、创建、编辑。"""

import json
import datetime
import os
import secrets

from flask import render_template, request, redirect, url_for, flash, abort
from werkzeug.utils import secure_filename

from core.auth import login_required, get_current_user
from core.db import get_db
from config import UPLOAD_DIR, get_config_value
from routes.discussion import discussion_bp
from services.logger import log

PAGE_SIZE = 20


def _get_categories():
    """获取所有分类，按 sort_order 排序。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM discussion_categories ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_category_dict():
    """获取分类 {id: name} 映射。"""
    cats = _get_categories()
    return {c['id']: c['name'] for c in cats}


def _get_topic_count(category_id=None):
    """获取帖子总数（可选按分类筛选）。"""
    conn = get_db()
    try:
        if category_id:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM discussion_topics WHERE category_id = ?",
                (category_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM discussion_topics").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


@discussion_bp.route('/discussion')
def list():
    """帖子列表页，支持分类筛选、置顶优先、分页。"""
    user = get_current_user()
    categories = _get_categories()

    category_id = request.args.get('category', type=int)
    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1

    total = _get_topic_count(category_id)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PAGE_SIZE

    conn = get_db()
    try:
        if category_id:
            rows = conn.execute(
                """
                SELECT t.*, u.username, c.name AS category_name,
                       (SELECT COUNT(*) FROM discussion_replies r WHERE r.topic_id = t.id) AS reply_count
                FROM discussion_topics t
                JOIN users u ON t.user_id = u.id
                LEFT JOIN discussion_categories c ON t.category_id = c.id
                WHERE t.category_id = ?
                ORDER BY t.is_pinned DESC, t.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (category_id, PAGE_SIZE, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT t.*, u.username, c.name AS category_name,
                       (SELECT COUNT(*) FROM discussion_replies r WHERE r.topic_id = t.id) AS reply_count
                FROM discussion_topics t
                JOIN users u ON t.user_id = u.id
                LEFT JOIN discussion_categories c ON t.category_id = c.id
                ORDER BY t.is_pinned DESC, t.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (PAGE_SIZE, offset)
            ).fetchall()
        topics = [dict(r) for r in rows]
    finally:
        conn.close()

    cat_dict = _get_category_dict()
    current_category_name = cat_dict.get(category_id, '') if category_id else ''

    return render_template(
        'discussion/list.html',
        user=user,
        topics=topics,
        categories=categories,
        category_id=category_id,
        current_category_name=current_category_name,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@discussion_bp.route('/discussion/create', methods=['GET', 'POST'])
@login_required
def create():
    """发帖页面。"""
    user = get_current_user()
    categories = _get_categories()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category_id = request.form.get('category_id', type=int)
        tags = request.form.get('tags', '').strip()

        if not title or len(title) > 200:
            flash('标题长度应为 1-200 字符', 'error')
            return render_template('discussion/create.html', user=user, categories=categories,
                                   title=title, content=content, category_id=category_id, tags=tags)
        if not content:
            flash('请输入内容', 'error')
            return render_template('discussion/create.html', user=user, categories=categories,
                                   title=title, content=content, category_id=category_id, tags=tags)

        # 处理附件上传
        attachment_names = []
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
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT INTO discussion_topics
                (user_id, category_id, title, content, tags, attachment, is_pinned, is_locked, view_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                """,
                (user['id'], category_id, title, content, tags, attachment_json, now, now)
            )
            conn.commit()
            log('Discussion', '发帖成功', user_id=user['id'], username=user['username'],
                title=title, category_id=category_id, ip=request.remote_addr)
        except Exception:
            conn.rollback()
            # 清理已上传的附件
            for fname in attachment_names:
                filepath = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
            log('Discussion', '发帖失败', user_id=user['id'], username=user['username'],
                title=title, ip=request.remote_addr)
            flash('发帖失败，请稍后重试', 'error')
            return render_template('discussion/create.html', user=user, categories=categories,
                                   title=title, content=content, category_id=category_id, tags=tags)
        finally:
            conn.close()

        return redirect(url_for('discussion.list'))

    return render_template('discussion/create.html', user=user, categories=categories)


@discussion_bp.route('/discussion/<int:topic_id>')
def detail(topic_id):
    """帖子详情页。"""
    user = get_current_user()

    conn = get_db()
    try:
        topic = conn.execute(
            """
            SELECT t.*, u.username
            FROM discussion_topics t
            JOIN users u ON t.user_id = u.id
            WHERE t.id = ?
            """,
            (topic_id,)
        ).fetchone()

        if not topic:
            abort(404)

        topic = dict(topic)

        # 解析附件
        if topic.get('attachment'):
            try:
                parsed = json.loads(topic['attachment'])
                topic['attachment'] = [parsed] if isinstance(parsed, str) else parsed
            except (json.JSONDecodeError, TypeError):
                topic['attachment'] = [topic['attachment']]
        else:
            topic['attachment'] = []

        # 增加浏览量
        conn.execute("UPDATE discussion_topics SET view_count = view_count + 1 WHERE id = ?", (topic_id,))
        conn.commit()

        # 获取回复总数和最后一条回复ID（用于实时刷新）
        total_replies = conn.execute(
            "SELECT COUNT(*) AS c FROM discussion_replies WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()['c']

        last_reply_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM discussion_replies WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()['max_id']

        cat_dict = _get_category_dict()
        topic['category_name'] = cat_dict.get(topic.get('category_id'), '')
    finally:
        conn.close()

    return render_template(
        'discussion/detail.html',
        user=user,
        topic=topic,
        total_replies=total_replies,
        last_reply_id=last_reply_id,
        discussion_refresh_interval=get_config_value('DISCUSSION_REFRESH_INTERVAL', 5),
        replies_per_page=get_config_value('REPLIES_PER_PAGE', 10),
    )


@discussion_bp.route('/discussion/<int:topic_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(topic_id):
    """编辑帖子。"""
    user = get_current_user()
    categories = _get_categories()

    conn = get_db()
    try:
        topic = conn.execute(
            "SELECT * FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()

    if not topic:
        abort(404)

    # 权限检查：仅作者或管理员可编辑
    if topic['user_id'] != user['id'] and not user.get('is_admin'):
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category_id = request.form.get('category_id', type=int)
        tags = request.form.get('tags', '').strip()

        if not title or len(title) > 200:
            flash('标题长度应为 1-200 字符', 'error')
            return render_template('discussion/create.html', user=user, categories=categories,
                                   topic=topic, title=title, content=content,
                                   category_id=category_id, tags=tags, editing=True)
        if not content:
            flash('请输入内容', 'error')
            return render_template('discussion/create.html', user=user, categories=categories,
                                   topic=topic, title=title, content=content,
                                   category_id=category_id, tags=tags, editing=True)

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = get_db()
        try:
            conn.execute(
                "UPDATE discussion_topics SET title=?, content=?, category_id=?, tags=?, updated_at=? WHERE id=?",
                (title, content, category_id, tags, now, topic_id)
            )
            conn.commit()
            log('Discussion', '编辑帖子成功', user_id=user['id'], username=user['username'],
                topic_id=topic_id, ip=request.remote_addr)
        except Exception:
            conn.rollback()
            log('Discussion', '编辑帖子失败', user_id=user['id'], username=user['username'],
                topic_id=topic_id, ip=request.remote_addr)
            flash('编辑失败，请稍后重试', 'error')
            return render_template('discussion/create.html', user=user, categories=categories,
                                   topic=topic, title=title, content=content,
                                   category_id=category_id, tags=tags, editing=True)
        finally:
            conn.close()

        return redirect(url_for('discussion.detail', topic_id=topic_id))

    return render_template('discussion/create.html', user=user, categories=categories,
                           topic=topic, title=topic['title'], content=topic['content'],
                           category_id=topic['category_id'], tags=topic['tags'], editing=True)