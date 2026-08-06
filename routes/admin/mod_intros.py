"""模组介绍管理路由：列表、增、改、删。"""

import datetime

from flask import render_template, redirect, url_for, flash, abort, request

from core.auth import login_required, get_current_user
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin/mod-intros')
@login_required
def manage_mod_intros():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        intros = conn.execute("SELECT * FROM mod_intros ORDER BY id ASC").fetchall()
        intros = [dict(r) for r in intros]
    finally:
        conn.close()

    return render_template('admin/admin_mod_intros.html', user=user, mod_intros=intros)


@admin_bp.route('/admin/mod-intros/add', methods=['POST'])
@login_required
def add_mod_intro():
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    icon = request.form.get('icon', 'box').strip()
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if title and content:
        conn = get_db()
        try:
            try:
                now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                conn.execute(
                    "INSERT INTO mod_intros (icon, title, content, created_at) VALUES (?, ?, ?, ?)",
                    (icon, title, content, now)
                )
                conn.commit()
            except:
                conn.rollback()
        finally:
            conn.close()
        flash('模组介绍已添加', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


@admin_bp.route('/admin/mod-intros/<int:intro_id>/edit', methods=['POST'])
@login_required
def edit_mod_intro(intro_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    icon = request.form.get('icon', 'box').strip()
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if title and content:
        conn = get_db()
        try:
            try:
                conn.execute(
                    "UPDATE mod_intros SET icon = ?, title = ?, content = ? WHERE id = ?",
                    (icon, title, content, intro_id)
                )
                conn.commit()
            except:
                conn.rollback()
        finally:
            conn.close()
        flash('模组介绍已更新', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


@admin_bp.route('/admin/mod-intros/<int:intro_id>/delete', methods=['POST'])
@login_required
def delete_mod_intro(intro_id):
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    try:
        try:
            conn.execute("DELETE FROM mod_intros WHERE id = ?", (intro_id,))
            conn.commit()
        except:
            conn.rollback()
    finally:
        conn.close()
    flash('模组介绍已删除', 'success')

    return redirect(url_for('admin.manage_mod_intros'))
