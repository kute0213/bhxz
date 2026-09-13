"""背景图片页面路由：上传页、列表页。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from io import BytesIO

from flask import request, jsonify, send_file, abort

from core.auth import get_current_user, login_required
from core.helpers import render_page
from routes.backgrounds import backgrounds_bp
from services import background_service
from services.ip import get_client_ip


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
    return render_page(
        'backgrounds/list.html',
        active_bgs=active_bgs,
        my_bgs=my_bgs,
    )


@backgrounds_bp.route('/backgrounds/upload')
@login_required
def upload_background_page():
    """背景图片上传页。"""
    return render_page(
        'backgrounds/upload.html',
    )


@backgrounds_bp.route('/backgrounds/upload', methods=['POST'])
@login_required
def upload_background():
    """开始异步上传背景图片任务（AJAX）。支持一次提交多个文件。

    返回 {task_ids: [...]}（每个文件一个独立任务）或 {error}。
    """
    user = get_current_user()
    files = request.files.getlist('background_image')
    if not files:
        return jsonify({'error': '请选择图片'}), 400

    task_ids = []
    for upload_file in files:
        success, result = background_service.start_upload(
            user_id=user['id'],
            username=user['username'],
            upload_file=upload_file,
            ip_address=get_client_ip(),
        )
        if success:
            task_ids.append(result['task_id'])

    if not task_ids:
        return jsonify({'error': '所有文件上传均失败，请检查图片格式与大小'}), 400
    return jsonify({'task_ids': task_ids})


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
        ip_address=get_client_ip(),
    )
    return jsonify({'success': success, 'message': message})


@backgrounds_bp.route('/backgrounds/serve/<int:bg_id>')
def serve_background(bg_id):
    """提供背景图片访问。

    支持 ?size= 参数：前端按设备屏幕尺寸请求最合适的档位（768 / 1280 / 1920），
    服务端就近返回对应变体；支持 ?ratio= 参数：前端携带屏幕宽高比（宽/高），
    服务端将所选档位中心裁剪到该比例后返回（结果缓存），实现按屏幕比例最适配取图。
    已通过的图片公开可访问；待审核/已驳回图片仅管理员与上传者可预览。
    """
    bg = background_service.get_background(bg_id)
    if not bg or not bg['file_path']:
        abort(404)

    if bg['status'] != 1:
        # 未通过的图片仅允许管理员与上传者预览（管理后台审核、用户查看状态）
        user = get_current_user()
        if not user or (not user.get('is_admin') and user['id'] != bg['user_id']):
            abort(404)

    size = request.args.get('size', type=int)
    if size is not None:
        size = max(1, min(size, 1920))

    ratio = request.args.get('ratio', type=float)
    if ratio is not None:
        ratio = max(
            background_service.RATIO_MIN,
            min(ratio, background_service.RATIO_MAX),
        )

    try:
        data = background_service.read_background_data(bg, size=size, ratio=ratio)
    except Exception:
        data = None
    if not data:
        abort(404)

    response = send_file(
        BytesIO(data),
        mimetype='image/webp',
        max_age=86400,
    )
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response
