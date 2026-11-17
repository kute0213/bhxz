"""MP3 流辅助函数（纯 Python，便于测试）。

听众接入时服务端会把最近一小段音频作为「开场快照」先发出去。
快照的起点通常落在某个 MP3 帧中间，直接解码会先输出一帧噪声，
因此需要前移到第一个完整帧头。
"""

# 帧头第 2、3 字节中的版本 / 层 / 码率 / 采样率字段
_VERSION_RESERVED = 1   # 00=MPEG2.5, 01=保留, 10=MPEG2, 11=MPEG1
_LAYER_RESERVED = 0     # 00=保留, 01=Layer III, 10=Layer II, 11=Layer I


def trim_to_frame(data):
    """返回从第一个完整 MP3 帧头开始的数据；找不到时原样返回。

    帧头校验：11 位同步字 + 非保留的版本 / 层 / 码率 / 采样率字段，
    避免把数据中偶然出现的 0xFF 误判为帧起点。
    """
    for i in range(len(data) - 3):
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            continue
        version = (data[i + 1] >> 3) & 0x03
        layer = (data[i + 1] >> 1) & 0x03
        bitrate_index = (data[i + 2] >> 4) & 0x0F
        sample_rate_index = (data[i + 2] >> 2) & 0x03
        if version == _VERSION_RESERVED or layer == _LAYER_RESERVED:
            continue
        if bitrate_index in (0, 15) or sample_rate_index == 3:
            continue
        return data[i:]
    return data
