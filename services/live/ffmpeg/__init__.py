"""音频直播 ffmpeg 命令构造（纯函数，便于测试）。

每个直播频道运行一个 ffmpeg 子进程，同时产出两路输出：
1. HLS（AAC）写入 uploads/live/<直播ID>/index.m3u8，供 m3u8 播放；
2. MP3 写入 stdout（pipe:1），由运行时读取并分发给所有 MP3 听众。
"""

import os

from config import FFMPEG_BIN
from services.live.constants import (
    HLS_AUDIO_BITRATE,
    HLS_LIST_SIZE,
    HLS_SEGMENT_SECONDS,
    MP3_AUDIO_BITRATE,
    OUTPUT_SAMPLE_RATE,
    PCM_CHANNELS,
    PCM_SAMPLE_RATE,
    SPEED_DEFAULT,
    VOLUME_DEFAULT,
)


def build_filter_chain(volume=VOLUME_DEFAULT, speed=SPEED_DEFAULT):
    """构造 [0:a] 音频滤镜链：音量 → 倍速 → 二路分流。

    音量为 1 且速度为 1 时只做分流，避免无意义的重采样开销。
    """
    parts = []
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = VOLUME_DEFAULT
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        speed = SPEED_DEFAULT

    if abs(volume - 1.0) > 0.001:
        parts.append(f'volume={volume:.3f}')
    if abs(speed - 1.0) > 0.001:
        parts.append(f'atempo={speed:.3f}')
    parts.append('asplit=2[hls][mp3]')
    return '[0:a]' + ','.join(parts)


def build_output_args(hls_dir):
    """构造 HLS + MP3 两路输出的 ffmpeg 参数（输入参数由调用方补充）。"""
    playlist_path = os.path.join(hls_dir, 'index.m3u8')
    seg_pattern = os.path.join(hls_dir, 'seg_%05d.ts')
    return [
        # 输出 1：HLS（AAC）
        '-map', '[hls]',
        '-c:a', 'aac', '-b:a', HLS_AUDIO_BITRATE,
        '-ar', str(OUTPUT_SAMPLE_RATE), '-ac', '2',
        '-f', 'hls',
        '-hls_time', str(HLS_SEGMENT_SECONDS),
        '-hls_list_size', str(HLS_LIST_SIZE),
        '-hls_flags', 'delete_segments+omit_endlist+independent_segments',
        '-hls_segment_filename', seg_pattern,
        playlist_path,
        # 输出 2：MP3 → stdout（供 /live/stream/<id>.mp3 分发给听众）
        '-map', '[mp3]',
        '-c:a', 'libmp3lame', '-b:a', MP3_AUDIO_BITRATE,
        '-ar', str(OUTPUT_SAMPLE_RATE), '-ac', '2',
        '-f', 'mp3',
        # 每帧立即刷出：muxer 默认攒满约 32KB（192kbps 下约 1.3 秒）才写 stdout，
        # 会直接叠加到听众延迟上；不要移除
        '-flush_packets', '1',
        'pipe:1',
    ]


def build_loop_cmd(src_path, hls_dir, volume=VOLUME_DEFAULT, speed=SPEED_DEFAULT):
    """循环播放本地音频：-stream_loop -1 + -re 按实时速度无限循环。"""
    cmd = [
        FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-re', '-stream_loop', '-1',
        '-i', src_path,
        '-filter_complex', build_filter_chain(volume, speed),
    ]
    cmd.extend(build_output_args(hls_dir))
    return cmd


def build_rec_cmd(hls_dir):
    """接收 WebRTC 解码后的 PCM：从 stdin 读 s16le 原始音频。

    注意：**不要**给 ``pipe:0`` 添加 ``-thread_queue_size``。部分 ffmpeg 构建把它
    当作输出（muxer）选项，会直接报错
    ``Option thread_queue_size ... cannot be applied to input url pipe:0``，
    导致实时录音直播无法启动。
    """
    cmd = [
        FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', '-nostdin',
        # 原始 PCM 参数已知，关闭输入探测：否则 ffmpeg 会先攒约 1 秒音频做
        # find_stream_info，直接把延迟叠加到直播上；不要移除
        '-probesize', '32', '-analyzeduration', '0',
        '-f', 's16le',
        '-ar', str(PCM_SAMPLE_RATE),
        '-ac', str(PCM_CHANNELS),
        '-i', 'pipe:0',
        '-filter_complex', build_filter_chain(1.0, 1.0),
    ]
    cmd.extend(build_output_args(hls_dir))
    return cmd


def hls_playlist_path(hls_dir):
    return os.path.join(hls_dir, 'index.m3u8')
