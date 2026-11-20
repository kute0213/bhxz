"""IndexNow Key 文件路由 —— 供搜索引擎校验站点所有权。

访问 `/<key>.txt` 时返回当前配置的 key。按 IndexNow 协议，只有放在根目录
的 Key 文件才能覆盖整站 URL；放在子目录时仅能提交该子目录下的 URL。

key 不匹配或未配置时统一返回 404，避免泄露任何额外信息。
"""

import secrets

from flask import Blueprint, Response, abort

from services.indexnow import get_key

indexnow_bp = Blueprint('indexnow', __name__)


@indexnow_bp.route('/<key>.txt')
def indexnow_key_file(key):
    """返回 Key 文件内容（必须与提交给 IndexNow 的 key 完全一致）。"""
    expected = get_key()
    if not expected or not key.isascii() or not secrets.compare_digest(key, expected):
        abort(404)
    return Response(
        expected,
        mimetype='text/plain; charset=utf-8',
        headers={'Cache-Control': 'public, max-age=86400'},
    )
