"""讨论管理路由：帖子列表、编辑、删除、置顶、锁定、分类管理。"""

import datetime
import json
import os

from flask import render_template, request, redirect, url_for, flash, abort

from core.auth import login_required, get_current_user
from core.db import get_db
from config import UPLOAD_DIR
from routes.admin import admin_bp
from services.logger import log


@admin_bp.route('/admin/discussion')
@login_required
def admin_discussion():
    """讨论管理列表。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT t.*, u.username,
                   (SELECT COUNT(*) FROM discussion_replies r WHERE r.topic_id = t.id) AS reply_count
            FROM discussion_topics t
            JOIN users u ON t.user_id = u.id
            ORDER BY t.id DESC
            """
        ).fetchall()
        topics = [dict(r) for r in rows]

        # 获取分类映射
        cats = conn.execute("SELECT id, name FROM discussion_categories ORDER BY sort_order").fetchall()
        cat_dict = {c['id']: c['name'] for c in cats}
    finally:
        conn.close()

    return render_template('admin/admin_discussion.html', user=user, topics=topics, cat_dict=cat_dict)


@admin_bp.route('/admin/discussion/<int:topic_id>/delete', methods=['POST'])
@login_required
def admin_delete_topic(topic_id):
    """管理员删除帖子。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        topic = conn.execute("SELECT * FROM discussion_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic:
            abort(404)

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
        log('Admin', '管理员删除帖子', admin_user=user['username'], topic_id=topic_id, ip=request.remote_addr)
        flash('帖子已删除', 'success')
    except Exception:
        conn.rollback()
        flash('删除失败', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_discussion'))


@admin_bp.route('/admin/discussion/<int:topic_id>/toggle-pin', methods=['POST'])
@login_required
def admin_toggle_pin(topic_id):
    """管理员置顶/取消置顶。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        topic = conn.execute("SELECT is_pinned FROM discussion_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic:
            abort(404)
        new_status = 0 if topic['is_pinned'] else 1
        conn.execute("UPDATE discussion_topics SET is_pinned = ? WHERE id = ?", (new_status, topic_id))
        conn.commit()
        log('Admin', '管理员切换置顶', admin_user=user['username'], topic_id=topic_id, is_pinned=new_status, ip=request.remote_addr)
        flash('置顶状态已更新', 'success')
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_discussion'))


@admin_bp.route('/admin/discussion/<int:topic_id>/toggle-lock', methods=['POST'])
@login_required
def admin_toggle_lock(topic_id):
    """管理员锁定/解锁。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        topic = conn.execute("SELECT is_locked FROM discussion_topics WHERE id = ?", (topic_id,)).fetchone()
        if not topic:
            abort(404)
        new_status = 0 if topic['is_locked'] else 1
        conn.execute("UPDATE discussion_topics SET is_locked = ? WHERE id = ?", (new_status, topic_id))
        conn.commit()
        log('Admin', '管理员切换锁定', admin_user=user['username'], topic_id=topic_id, is_locked=new_status, ip=request.remote_addr)
        flash('锁定状态已更新', 'success')
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_discussion'))


@admin_bp.route('/admin/discussion/categories', methods=['GET', 'POST'])
@login_required
def admin_categories():
    """分类管理。"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'create':
            name = request.form.get('name', '').strip()
            slug = request.form.get('slug', '').strip()
            if not name or not slug:
                flash('请填写分类名称和别名', 'error')
            else:
                conn = get_db()
                try:
                    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    conn.execute(
                        "INSERT INTO discussion_categories (name, slug, created_at) VALUES (?, ?, ?)",
                        (name, slug, now)
                    )
                    conn.commit()
                    log('Admin', '创建讨论分类', admin_user=user['username'], name=name, slug=slug, ip=request.remote_addr)
                    flash('分类已创建', 'success')
                except Exception:
                    conn.rollback()
                    flash('创建失败，别名可能已存在', 'error')
                finally:
                    conn.close()
        elif action == 'delete':
            cat_id = request.form.get('category_id', type=int)
            if cat_id:
                conn = get_db()
                try:
                    conn.execute("DELETE FROM discussion_categories WHERE id = ?", (cat_id,))
                    conn.commit()
                    log('Admin', '删除讨论分类', admin_user=user['username'], category_id=cat_id, ip=request.remote_addr)
                    flash('分类已删除', 'success')
                except Exception:
                    conn.rollback()
                    flash('删除失败', 'error')
                finally:
                    conn.close()

    conn = get_db()
    try:
        categories = conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM discussion_topics t WHERE t.category_id = c.id) AS topic_count "
            "FROM discussion_categories c ORDER BY c.sort_order ASC, c.id ASC"
        ).fetchall()
        categories = [dict(c) for c in categories]
    finally:
        conn.close()

    return render_template('admin/admin_discussion_categories.html', user=user, categories=categories)