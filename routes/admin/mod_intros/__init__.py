"""模组介绍管理路由：列表、增、改、删。"""

import datetime

from flask import redirect, url_for, flash, abort, request

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.db import get_db
from routes.admin import admin_bp


def _normalize_link(raw: str) -> str:
    """规范化模组链接：去空白，无协议时自动补 https://，空值返回空串。"""
    link = (raw or '').strip()
    if not link:
        return ''
    if not link.startswith(('http://', 'https://')):
        link = 'https://' + link
    return link


@admin_bp.route('/admin/mod-intros')
@admin_required
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

    return render_page('admin/admin_mod_intros.html', mod_intros=intros)


@admin_bp.route('/admin/mod-intros/add', methods=['POST'])
@admin_required
def add_mod_intro():
    user = get_current_user()

    icon = request.form.get('icon', 'box').strip()
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    link = _normalize_link(request.form.get('link', ''))

    if title and content:
        conn = get_db()
        try:
            try:
                now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                conn.execute(
                    "INSERT INTO mod_intros (icon, title, content, link, created_at) VALUES (?, ?, ?, ?, ?)",
                    (icon, title, content, link, now)
                )
                conn.commit()
            except:
                conn.rollback()
        finally:
            conn.close()
        flash('模组介绍已添加', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


@admin_bp.route('/admin/mod-intros/<int:intro_id>/edit', methods=['POST'])
@admin_required
def edit_mod_intro(intro_id):
    user = get_current_user()

    icon = request.form.get('icon', 'box').strip()
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    link = _normalize_link(request.form.get('link', ''))

    if title and content:
        conn = get_db()
        try:
            try:
                conn.execute(
                    "UPDATE mod_intros SET icon = ?, title = ?, content = ?, link = ? WHERE id = ?",
                    (icon, title, content, link, intro_id)
                )
                conn.commit()
            except:
                conn.rollback()
        finally:
            conn.close()
        flash('模组介绍已更新', 'success')

    return redirect(url_for('admin.manage_mod_intros'))


@admin_bp.route('/admin/mod-intros/<int:intro_id>/delete', methods=['POST'])
@admin_required
def delete_mod_intro(intro_id):
    user = get_current_user()

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
