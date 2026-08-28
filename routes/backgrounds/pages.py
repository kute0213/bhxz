"""背景图片页面路由：上传页、列表页。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from flask import render_template, request, jsonify

from core.auth import get_current_user, login_required
from routes.backgrounds import backgrounds_bp
from services import background_service


@backgrounds_bp.route('/backgrounds')
def background_list_page():
    """背景图片列表页：展示所有已通过且活跃的背景图片。"""
    user = get_current_user()
    # 已通过、活跃的背景图片
    active_bgs = background_service.get_active_backgrounds()
    # 如果用户已登录，显示该用户上传的所有背景
    my_bgs = []
    if user:
        my_bgs = background_service.get_backgrounds(user_id=user['id'])
    return render_template(
        'backgrounds/list.html',
        user=user,
        active_bgs=active_bgs,
        my_bgs=my_bgs,
    )


@backgrounds_bp.route('/backgrounds/upload')
@login_required
def upload_background_page():
    """背景图片上传页。"""
    user = get_current_user()
    return render_template(
        'backgrounds/upload.html',
        user=user,
    )


@backgrounds_bp.route('/backgrounds/upload', methods=['POST'])
@login_required
def upload_background():
    """开始异步上传背景图片任务（AJAX）。返回 {task_id} 或 {error}。"""
    user = get_current_user()
    upload_file = request.files.get('background_image')

    success, result = background_service.start_upload(
        user_id=user['id'],
        username=user['username'],
        upload_file=upload_file,
        ip_address=request.remote_addr,
    )
    if success:
        return jsonify({'task_id': result['task_id']})
    return jsonify({'error': result}), 400


@backgrounds_bp.route('/backgrounds/upload/progress/<task_id>')
@login_required
def upload_background_progress(task_id):
    """查询上传任务进度（AJAX 轮询）。返回 JSON。"""
    task = background_service.get_upload_progress(task_id)
    if not task:
        return jsonify({'status': 'error', 'message': '任务不存在或已过期'}), 404
    return jsonify(task)


@backgrounds_bp.route('/backgrounds/<int:bg_id>/delete', methods=['POST'])
@login_required
def delete_background(bg_id):
    """删除背景图片（AJAX）。返回 JSON。"""
    user = get_current_user()
    success, message = background_service.delete_background(
        bg_id=bg_id,
        user_id=user['id'],
        is_admin=bool(user.get('is_admin')),
        ip_address=request.remote_addr,
    )
    return jsonify({'success': success, 'message': message})


@backgrounds_bp.route('/backgrounds/serve/<int:bg_id>')
def serve_background(bg_id):
    """提供背景图片访问。"""
    from flask import send_file, abort
    bg = background_service.get_background(bg_id)
    if not bg or bg['status'] != 1 or not bg['file_path']:
        abort(404)
    return send_file(
        bg['file_path'],
        mimetype='image/webp',
        max_age=3600,
    )