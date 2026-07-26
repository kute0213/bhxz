"""管理员专用 API。"""

from flask import Blueprint, request, jsonify, abort
from core.auth import login_required, get_current_user
from core.db import get_db

admin_api_bp = Blueprint('api_admin', __name__, url_prefix='/api/admin')


@admin_api_bp.route('/logs/refresh')
@login_required
def api_logs_refresh():
    """刷新访问日志（仅管理员）"""
    user = get_current_user()
    if not user or not user['is_admin']:
        abort(403)

    conn = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    total = conn.execute("SELECT COUNT(*) AS c FROM access_logs").fetchone()['c']
    total_pages = (total + per_page - 1) // per_page

    logs = conn.execute("""
        SELECT * FROM access_logs
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset)).fetchall()
    logs = [dict(log) for log in logs]
    conn.close()

    return jsonify({
        'logs': logs,
        'page': page,
        'total_pages': total_pages,
        'total': total
    })
