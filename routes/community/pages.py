"""社区页面路由：附件下载。"""

from flask import send_from_directory, abort

from config import UPLOAD_ATTACHMENTS_DIR
from routes.community import community_bp


@community_bp.route('/uploads/<path:filename>')
def download_attachment(filename):
    if '..' in filename or filename.startswith('/'):
        abort(404)
    return send_from_directory(UPLOAD_ATTACHMENTS_DIR, filename, as_attachment=True)