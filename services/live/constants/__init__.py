"""音频直播业务服务 - 常量与参数规范化。

纯 Python，不依赖 Flask。
"""

# 直播模式
MODE_LOOP = 'loop'      # 循环播放音频库中的音频
MODE_REC = 'rec'        # 实时录音（浏览器采集 PCM 上传）

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

# 实时录音输入参数（浏览器采集的 PCM，s16le 双声道）
PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 2
PCM_FRAME_BYTES = PCM_CHANNELS * 2  # 每采样帧 4 字节
# 单次上传的 PCM 上限（约 2.5 秒），用于拒绝异常请求
PCM_MAX_CHUNK_BYTES = PCM_SAMPLE_RATE * PCM_FRAME_BYTES * 5 // 2

# ---- Opus 低延迟旁路（与 MP3 并存，MP3 仍是兼容兜底） ----
# 浏览器 WebCodecs AudioEncoder 每帧 20ms（48kHz 960 采样），前端每 2 帧
# （约 40ms）上传一批。服务端只做转发，不解码、不落盘，避免额外转码延迟。
OPUS_SAMPLE_RATE = 48000
OPUS_CHANNELS = 2
OPUS_FRAME_SAMPLES = OPUS_SAMPLE_RATE // 50          # 20ms = 960 采样
OPUS_FRAME_MS = 20
OPUS_MAX_PACKET_BYTES = 1275                         # RFC 6716 单个 Opus 包上限
OPUS_MAX_BATCH_PACKETS = 10                          # 单次上传最多 10 帧（200ms）
OPUS_MAX_BATCH_BYTES = OPUS_MAX_PACKET_BYTES * OPUS_MAX_BATCH_PACKETS + 2 * OPUS_MAX_BATCH_PACKETS
OPUS_QUEUE_MAXSIZE = 64                              # 每听众最多积压 64 包（约 1.28 秒）
OPUS_RING_MAX_PACKETS = 6                            # 新听众预置最近 6 包（约 120ms）

# 播放地址格式（相对站点根路径）
M3U8_PATH = '/live/stream/{channel_id}.m3u8'
MP3_PATH = '/live/stream/{channel_id}.mp3'
OPUS_PATH = '/live/stream/{channel_id}.opus'
PLAY_PAGE_PATH = '/live/play.html?channelId={channel_id}'

# MP3 客户端最多积压的分片数（慢客户端丢弃旧数据，保证低延迟）
MP3_QUEUE_MAXSIZE = 64

# 新听众接入时预置的最近音频字节数（192kbps 下约 0.34 秒）。
# 仅用于帮助浏览器快速出声，**不可调大**：这是听众听到的固定延迟。
MP3_RING_MAX_BYTES = 8 * 1024


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
