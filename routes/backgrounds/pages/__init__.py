"""背景图片页面路由：上传页、列表页。

薄层：仅负责 HTTP 请求解析/响应构造，业务逻辑委托给 services。
"""

from io import BytesIO

from flask import request, jsonify, send_file, abort, Response

from core.auth import get_current_user, login_required
from core.helpers import render_page
from routes.backgrounds import backgrounds_bp
from services import background_service
from core.shared.ip import get_client_ip


@backgrounds_bp.route('/backgrounds')
def background_list_page():
    """背景图片列表页：列表数据由前端调用 /api/backgrounds/list 无刷新获取。"""
    return render_page('backgrounds/index.html')


@backgrounds_bp.route('/api/backgrounds/list')
def api_backgrounds_list():
    """背景图片列表 API（JSON，供 /backgrounds 页面前端无刷新获取）。

    返回当前启用（已通过且活跃）的背景图片，以及登录用户自己上传的全部背景图片。
    """
    user = get_current_user()
    active_bgs = background_service.get_active_backgrounds()
    my_bgs = background_service.get_backgrounds(user_id=user['id']) if user else []

    def _public(bg):
        return {
            'id': bg['id'],
            'filename': bg['filename'],
            'username': bg.get('username', ''),
            'status': bg['status'],
            'created_at': bg.get('created_at', ''),
        }

    return jsonify({
        'success': True,
        'logged_in': bool(user),
        'active': [_public(b) for b in active_bgs],
        'my': [_public(b) for b in my_bgs],
    })


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

    # 待审核数量上限（背景图片上传后进入待审核，总量 + 背景单类）
    from services.content_limits import check_pending_limit
    allowed, msg = check_pending_limit(user, 'background')
    if not allowed:
        return jsonify({'error': msg}), 400

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


@backgrounds_bp.route('/backgrounds/serve')
def serve_active_background():
    """全站背景图片入口（**不带 ID**）：按屏幕宽高比返回最合适的启用背景。

    URL 形如 `/backgrounds/serve?ratio=1.78`：
      * `ratio` —— 访问者屏幕的宽高比（宽/高）。服务端**只做查询与挑选**：
                 从已启用的背景中返回宽高比最接近的一张主图字节，
                 **不缩放、不裁剪**；裁剪与铺满由浏览器按 `background-size` 完成。
                 `ratio` 缺省时退回最新启用的一张。

    未启用任何背景时返回 404（前端回退到渐变色背景）。
    """
    bg = background_service.get_background_for_ratio(_resolve_ratio())
    if not bg:
        abort(404)
    return _send_background(bg, long_cache=False)


@backgrounds_bp.route('/backgrounds/serve/<int:bg_id>')
def serve_background(bg_id):
    """按 ID 提供背景图片（后台缩略图、审核预览、用户查看自己上传的图片）。

    已通过的图片公开可访问；待审核/已驳回图片仅管理员与上传者可预览。
    原样返回主图（不缩放、不裁剪），缩略图由浏览器按 CSS 尺寸缩放。
    """
    bg = background_service.get_background(bg_id)
    if not bg or not bg['file_path']:
        abort(404)

    if bg['status'] != 1:
        # 未通过的图片仅允许管理员与上传者预览（管理后台审核、用户查看状态）
        user = get_current_user()
        if not user or (not user.get('is_admin') and user['id'] != bg['user_id']):
            abort(404)

    return _send_background(bg, long_cache=True)


def _resolve_ratio():
    """解析 ?ratio= 宽高比参数，收敛到 [RATIO_MIN, RATIO_MAX]；非法时返回 None。"""
    ratio = request.args.get('ratio', type=float)
    if ratio is None or ratio <= 0:
        return None
    return max(background_service.RATIO_MIN, min(ratio, background_service.RATIO_MAX))


def _send_background(bg, long_cache):
    """返回背景图片响应（主图原样返回，不做任何缩放 / 裁切）。

    只有「查询 + 返回」：服务端不处理像素，裁切与最终缩放全部由浏览器完成。

    long_cache=True（按 ID 取图，URL 稳定且内容不变）→ 浏览器可长期缓存；
    long_cache=False（全站背景 URL 固定但内容会随启用池变化）→ 强制重新校验
    （ETag），避免切换背景后浏览器仍展示旧图。
    """
    try:
        data = background_service.read_background_data(bg)
    except Exception:
        data = None
    if not data:
        abort(404)

    etag = background_service.background_etag(bg)
    if not long_cache and request.if_none_match.contains(etag):
        response = Response(status=304)
    else:
        response = send_file(BytesIO(data), mimetype='image/webp')
    response.set_etag(etag)
    if long_cache:
        response.headers['Cache-Control'] = 'public, max-age=86400'
    else:
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response
