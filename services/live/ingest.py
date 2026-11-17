"""实时录音上传数据校验（纯函数，不依赖 Flask）。

两条上传通道：
- PCM：浏览器把麦克风音频转成 48kHz / 双声道 / s16le 小端 PCM，每 50ms 上传一批
  （约 9.6KB），服务端交给 ffmpeg 编码为 HLS + MP3，作为兼容兜底；
- Opus：浏览器用 WebCodecs 编码成 20ms/帧的 Opus 包，每 2 帧上传一批，服务端
  只转发不解码，是低延迟主路径。

这里只做边界校验，真正的写入 / 分发由运行时完成。
"""

import struct

from services.live.constants import (
    OPUS_MAX_BATCH_BYTES,
    OPUS_MAX_BATCH_PACKETS,
    OPUS_MAX_PACKET_BYTES,
    PCM_FRAME_BYTES,
    PCM_MAX_CHUNK_BYTES,
)


def validate_pcm_chunk(data):
    """校验一批 PCM 数据。

    Returns:
        (ok, error_message, http_status)
    """
    if not data:
        return False, '音频数据为空', 400
    if len(data) > PCM_MAX_CHUNK_BYTES:
        return False, '音频分片过大', 413
    if len(data) % PCM_FRAME_BYTES:
        # s16le 双声道每采样帧 4 字节，长度不是 4 的倍数说明数据错位
        return False, '音频数据格式不正确', 400
    return True, None, None


def validate_opus_batch(data):
    """校验并拆分一批 Opus 包。

    上传格式：``[2 字节大端长度][Opus 包]`` 重复。服务端不需要时间戳与解码，
    只按顺序转发，因此长度前缀是唯一需要的元数据。

    Returns:
        (ok, packets_or_error, http_status)
        - ok 为 True 时第二项是 ``list[bytes]``（1~10 个 Opus 包）
        - ok 为 False 时第二项是错误信息
    """
    if not data:
        return False, '音频数据为空', 400
    if len(data) > OPUS_MAX_BATCH_BYTES:
        return False, '音频分片过大', 413

    packets = []
    pos = 0
    total = len(data)
    while pos < total:
        if total - pos < 2:
            return False, '音频数据格式不正确', 400
        size = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if size == 0 or size > OPUS_MAX_PACKET_BYTES:
            return False, '音频数据格式不正确', 400
        if total - pos < size:
            return False, '音频数据格式不正确', 400
        packets.append(bytes(data[pos:pos + size]))
        pos += size
        if len(packets) > OPUS_MAX_BATCH_PACKETS:
            return False, '音频分片包含过多帧', 400

    if not packets:
        return False, '音频数据为空', 400
    return True, packets, None
