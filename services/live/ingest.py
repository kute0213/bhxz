"""实时录音 PCM 上传校验（纯函数，不依赖 Flask）。

浏览器把麦克风音频转成 48kHz / 双声道 / s16le 小端 PCM，每 200ms 上传一批
（约 38KB）。这里只做边界校验，真正的写入由运行时 ``LiveChannel.write_pcm`` 完成。
"""

from services.live.constants import PCM_FRAME_BYTES, PCM_MAX_CHUNK_BYTES


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
