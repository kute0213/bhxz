"""音频直播业务服务 - 常量与参数规范化。

纯 Python，不依赖 Flask。
"""

# 直播模式
MODE_LOOP = 'loop'      # 循环播放音频库中的音频
MODE_REC = 'rec'        # WebRTC 实时录音

MODE_LABELS = {
    MODE_LOOP: '循环播放',
    MODE_REC: '实时录音',
}

# 每个账号最多同时开启的实时录音直播数量（固定 1 路，不可配置）
MAX_REC_PER_USER = 1

# 直播状态
STATUS_LIVE = 'live'
STATUS_STOPPED = 'stopped'

STATUS_LABELS = {
    STATUS_LIVE: '直播中',
    STATUS_STOPPED: '已停止',
}

# 音量（0 = 静音，1 = 原始音量，2 = 200%）
VOLUME_MIN = 0.0
VOLUME_MAX = 2.0
VOLUME_DEFAULT = 1.0

# 播放速度（倍速，受 ffmpeg atempo 限制为 0.5~2.0）
SPEED_MIN = 0.5
SPEED_MAX = 2.0
SPEED_DEFAULT = 1.0

# 标题最大长度
TITLE_MAX_LENGTH = 60

# 直播 HLS 分片时长（秒）与播放列表保留分片数
HLS_SEGMENT_SECONDS = 2
HLS_LIST_SIZE = 6

# 输出编码参数
HLS_AUDIO_BITRATE = '128k'
MP3_AUDIO_BITRATE = '192k'
OUTPUT_SAMPLE_RATE = 44100

# WebRTC 录音输入参数（浏览器 Opus 解码后的 PCM）
PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 2

# 播放地址格式（相对站点根路径）
M3U8_PATH = '/live/stream/{channel_id}.m3u8'
MP3_PATH = '/live/stream/{channel_id}.mp3'
PLAY_PAGE_PATH = '/live/play.html?channelId={channel_id}'

# MP3 客户端最多积压的分片数（慢客户端丢弃旧数据，保证低延迟）
MP3_QUEUE_MAXSIZE = 64

# 新听众接入时预置的最近音频字节数（约 1 秒，帮助快速出声）
MP3_RING_MAX_BYTES = 192 * 1024


def normalize_volume(value, default=VOLUME_DEFAULT):
    """将音量限制在 [VOLUME_MIN, VOLUME_MAX]，非法输入返回 default。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return max(VOLUME_MIN, min(VOLUME_MAX, value))


def normalize_speed(value, default=SPEED_DEFAULT):
    """将播放速度限制在 [SPEED_MIN, SPEED_MAX]，非法输入返回 default。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return max(SPEED_MIN, min(SPEED_MAX, value))


def normalize_title(value):
    """清洗直播标题：去首尾空白、折叠内部空白、限制长度。"""
    title = ' '.join(str(value or '').split())
    return title[:TITLE_MAX_LENGTH]


def is_valid_mode(mode):
    return mode in (MODE_LOOP, MODE_REC)
