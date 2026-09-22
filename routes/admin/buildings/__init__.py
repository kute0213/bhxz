"""管理员后台公共建筑管理：查看、审核、管理删除、处理举报。"""

from datetime import datetime

from flask import redirect, url_for, flash

from core.auth import admin_required
from utils.helpers import render_page
from core.db import get_db
from routes.admin import admin_bp


@admin_bp.route('/admin/buildings')
@admin_required
def admin_buildings():
    """管理后台：公共建筑列表（含审核和举报）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT b.*, u.username as author_name
            FROM public_buildings b
            LEFT JOIN users u ON b.author_id = u.id
            ORDER BY b.status = 'pending' DESC, b.id DESC
            """
        ).fetchall()
        buildings = [dict(r) for r in rows]

        # 获取每个建筑的举报数（待处理）
        for b in buildings:
            r = conn.execute(
                "SELECT COUNT(*) AS c FROM building_reports WHERE building_id = ? AND status = 'pending'",
                (b['id'],),
            ).fetchone()
            b['pending_report_count'] = r['c'] if r else 0

        # 获取所有待处理举报
        reports = conn.execute(
            """
            SELECT br.*, b.title as building_title, u.username as reporter_name
            FROM building_reports br
            LEFT JOIN public_buildings b ON br.building_id = b.id
            LEFT JOIN users u ON br.reporter_id = u.id
            WHERE br.status = 'pending'
            ORDER BY br.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    return render_page('admin/admin_buildings.html', buildings=buildings, reports=[dict(r) for r in reports])


@admin_bp.route('/admin/buildings/<int:building_id>/approve', methods=['POST'])
@admin_required
def admin_building_approve(building_id):
    """管理后台：通过建筑审核。"""
    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """
            UPDATE public_buildings
            SET status = 'approved', published_at = ?, rejected_reason = '', updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, now, building_id),
        )
        conn.commit()
        flash('建筑已通过审核', 'success')
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_buildings'))


@admin_bp.route('/admin/buildings/<int:building_id>/reject', methods=['POST'])
@admin_required
def admin_building_reject(building_id):
    """管理后台：拒绝建筑审核。"""
    from flask import request
    reason = (request.form.get('reason') or '').strip()

    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """
            UPDATE public_buildings
            SET status = 'rejected', rejected_reason = ?, updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (reason, now, building_id),
        )
        conn.commit()
        flash('建筑已拒绝', 'success')
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_buildings'))


@admin_bp.route('/admin/buildings/<int:building_id>/delete', methods=['POST'])
@admin_required
def admin_building_delete(building_id):
    """删除公共建筑及关联评论/举报。"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM building_comments WHERE building_id = ?", (building_id,))
        conn.execute("DELETE FROM building_reports WHERE building_id = ?", (building_id,))
        conn.execute("DELETE FROM public_buildings WHERE id = ?", (building_id,))
        conn.commit()
        flash('建筑已删除', 'success')
    except Exception:
        conn.rollback()
        flash('删除失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_buildings'))


@admin_bp.route('/admin/buildings/report/<int:report_id>/dismiss', methods=['POST'])
@admin_required
def admin_building_report_dismiss(report_id):
    """驳回举报（标记为已处理但不删除建筑）。"""
    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE building_reports SET status = 'dismissed', resolved_at = ? WHERE id = ?",
            (now, report_id),
        )
        conn.commit()
        flash('举报已驳回', 'success')
    except Exception:
        conn.rollback()
        flash('操作失败', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin.admin_buildings'))