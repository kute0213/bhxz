"""管理后台 - IndexNow 推送。

独立配置页面：启停开关、自动推送时间、Key 管理、立即提交与结果查看。
"""

from flask import jsonify, request

from core.auth import admin_required
from core.helpers import render_page
from routes.admin import admin_bp
from services import indexnow


@admin_bp.route('/admin/indexnow')
@admin_required
def admin_indexnow_page():
    """IndexNow 配置页面。"""
    return render_page('admin/indexnow.html', status=indexnow.get_status())


@admin_bp.route('/admin/api/indexnow')
@admin_required
def api_indexnow_status():
    """读取当前配置与最近一次提交结果。"""
    return jsonify({'success': True, **indexnow.get_status()})


@admin_bp.route('/admin/api/indexnow/save', methods=['POST'])
@admin_required
def api_indexnow_save():
    """保存启用状态、自动推送开关与推送时间。"""
    data = request.get_json(silent=True) or {}
    ok, result = indexnow.save_config(
        enabled=data.get('enabled'),
        auto_submit=data.get('auto_submit'),
        submit_time=data.get('submit_time'),
    )
    if not ok:
        return jsonify({'success': False, 'message': result}), 400
    return jsonify({'success': True, 'message': result, **indexnow.get_status()})


@admin_bp.route('/admin/api/indexnow/regenerate-key', methods=['POST'])
@admin_required
def api_indexnow_regenerate_key():
    """重新生成 Key（旧 Key 文件立即失效）。"""
    indexnow.regenerate_key()
    return jsonify({'success': True, 'message': '已重新生成 Key', **indexnow.get_status()})


@admin_bp.route('/admin/api/indexnow/submit', methods=['POST'])
@admin_required
def api_indexnow_submit():
    """立即向 IndexNow 提交全部公开 URL。"""
    result = indexnow.submit_all(trigger='manual')
    return jsonify(result), (200 if result.get('success') else 400)
