"""音频直播业务服务包。

分层：
- constants：模式 / 状态 / 参数规范化
- ffmpeg：纯函数构造 ffmpeg 命令（HLS + MP3 双输出）
- store：数据库读写（频道、封禁）
- runtime：ffmpeg 进程与 MP3 听众分发
- webrtc：aiortc 实时录音接收

所有函数为 Flask 无关的纯业务逻辑，返回 (success, data_or_error) 元组。
"""

from services.live.constants import (
    MODE_LOOP,
    MODE_REC,
    MODE_LABELS,
    STATUS_LIVE,
    STATUS_STOPPED,
    STATUS_LABELS,
    VOLUME_DEFAULT,
    VOLUME_MAX,
    VOLUME_MIN,
    SPEED_DEFAULT,
    SPEED_MAX,
    SPEED_MIN,
    M3U8_PATH,
    MP3_PATH,
    PLAY_PAGE_PATH,
    normalize_speed,
    normalize_title,
    normalize_volume,
    is_valid_mode,
)
from services.live.runtime import LiveChannel, LiveManager, manager
from services.live import store, webrtc

__all__ = [
    'MODE_LOOP', 'MODE_REC', 'MODE_LABELS',
    'STATUS_LIVE', 'STATUS_STOPPED', 'STATUS_LABELS',
    'VOLUME_DEFAULT', 'VOLUME_MAX', 'VOLUME_MIN',
    'SPEED_DEFAULT', 'SPEED_MAX', 'SPEED_MIN',
    'M3U8_PATH', 'MP3_PATH', 'PLAY_PAGE_PATH',
    'normalize_speed', 'normalize_title', 'normalize_volume', 'is_valid_mode',
    'LiveChannel', 'LiveManager', 'manager',
    'store', 'webrtc',
]
