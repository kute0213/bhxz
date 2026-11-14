"""音频直播蓝图：直播台、播放页、流媒体与 JSON API。"""

from flask import Blueprint

live_bp = Blueprint('live', __name__)

import routes.live.pages   # noqa: E402,F401
import routes.live.api     # noqa: E402,F401
import routes.live.stream  # noqa: E402,F401
