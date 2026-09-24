"""模组介绍管理路由：列表、增、改、删。

增/改/删统一返回 JSON，前端无刷新。
"""

import datetime

from flask import request, jsonify, abort

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


def _payload():
    """读取请求体（兼容 JSON 与表单）。"""
    data = request.get_json(silent=True) or {}
    return {
        'icon': (data.get('icon') or request.form.get('icon') or 'box').strip(),
        'title': (data.get('title') or request.form.get('title') or '').strip(),
        'content': (data.get('content') or request.form.get('content') or '').strip(),
        'link': _normalize_link(data.get('link') or request.form.get('link') or ''),
    }


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

    return render_page('admin/mod_intros.html', mod_intros=intros)


@admin_bp.route('/admin/mod-intros/add', methods=['POST'])
@admin_required
def add_mod_intro():
    """新增模组介绍（JSON API，前端无刷新）。"""
    fields = _payload()
    if not fields['title'] or not fields['content']:
        return jsonify({'success': False, 'message': '标题与内容不能为空'}), 400

    conn = get_db()
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute(
            "INSERT INTO mod_intros (icon, title, content, link, created_at) VALUES (?, ?, ?, ?, ?)",
            (fields['icon'], fields['title'], fields['content'], fields['link'], now)
        )
        conn.commit()
        return jsonify({
            'success': True,
            'message': '模组介绍已添加',
            'intro': {
                'id': cur.lastrowid,
                'icon': fields['icon'],
                'title': fields['title'],
                'content': fields['content'],
                'link': fields['link'],
                'created_at': now,
            },
        })
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '添加失败'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/mod-intros/<int:intro_id>/edit', methods=['POST'])
@admin_required
def edit_mod_intro(intro_id):
    """更新模组介绍（JSON API，前端无刷新）。"""
    fields = _payload()
    if not fields['title'] or not fields['content']:
        return jsonify({'success': False, 'message': '标题与内容不能为空'}), 400

    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE mod_intros SET icon = ?, title = ?, content = ?, link = ? WHERE id = ?",
            (fields['icon'], fields['title'], fields['content'], fields['link'], intro_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'success': False, 'message': '模组介绍不存在'}), 404
        return jsonify({'success': True, 'message': '模组介绍已更新', 'intro': fields})
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '更新失败'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/mod-intros/<int:intro_id>/delete', methods=['POST'])
@admin_required
def delete_mod_intro(intro_id):
    """删除模组介绍（JSON API，前端无刷新）。"""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM mod_intros WHERE id = ?", (intro_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'success': False, 'message': '模组介绍不存在'}), 404
        return jsonify({'success': True, 'message': '模组介绍已删除'})
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '删除失败'}), 500
    finally:
        conn.close()
