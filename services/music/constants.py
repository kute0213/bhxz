"""大喇叭音频业务服务 - 常量定义。"""

# HLS 分片时长（秒）
HLS_SEGMENT_SECONDS = 10

# 音频状态：0=私有 1=待审核 2=已公开（3=已驳回 仅遗留老数据，新驳回直接转为私有）
STATUS_PRIVATE = 0
STATUS_PENDING = 1
STATUS_PUBLIC = 2
STATUS_REJECTED = 3

# 状态显示文案
STATUS_LABELS = {
    STATUS_PRIVATE: '私有',
    STATUS_PENDING: '待审核',
    STATUS_PUBLIC: '已公开',
    STATUS_REJECTED: '已驳回',
}

# 上传任务在内存中的保留时间（秒），超过后自动清理
UPLOAD_TASK_TTL = 3600