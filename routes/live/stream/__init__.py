"""音频直播流媒体路由：HLS 播放列表 / 分片 / MP3 实时流。

播放地址：
- m3u8：/live/stream/<直播ID>.m3u8
- mp3 ：/live/stream/<直播ID>.mp3
"""

import os
import queue

from flask import Response, abort, send_file, stream_with_context

from routes.live import live_bp
from services.live import manager


def _live_channel(channel_id):
    channel = manager.get(channel_id)
    if channel is None or not channel.is_live():
        abort(404)
    return channel


@live_bp.route('/live/stream/<int:channel_id>.m3u8')
def live_hls_playlist(channel_id):
    """HLS 播放列表：把分片相对路径改写为本站绝对路径。

    实时录音刚开播、主播还没推上音频时，ffmpeg 尚未产出分片。此时返回一个
    合法的空播放列表（不含 ENDLIST），播放器会持续轮询，而不是直接 404。
    """
    channel = _live_channel(channel_id)
    playlist_path = os.path.join(channel.hls_dir, 'index.m3u8')
    if not os.path.isfile(playlist_path):
        resp = Response(
            '#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n'
            '#EXT-X-MEDIA-SEQUENCE:0\n',
            mimetype='application/vnd.apple.mpegurl')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp

    with open(playlist_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.read().splitlines()

    out = []
    for line in lines:
        if line and not line.startswith('#') and not line.startswith('http'):
            name = os.path.basename(line)
            out.append(f'/live/stream/{channel_id}/{name}')
        else:
            out.append(line)

    resp = Response('\n'.join(out) + '\n',
                    mimetype='application/vnd.apple.mpegurl')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


@live_bp.route('/live/stream/<int:channel_id>.mp3')
def live_mp3_stream(channel_id):
    """MP3 实时流：从 ffmpeg stdout 分发给所有听众（长连接）。"""
    channel = _live_channel(channel_id)
    client_queue, snapshot = channel.subscribe()

    def generate():
        try:
            if snapshot:
                yield snapshot
            while True:
                try:
                    chunk = client_queue.get(timeout=10)
                except queue.Empty:
                    if not channel.is_live():
                        break
                    continue
                if chunk is None:
                    break
                yield chunk
        finally:
            channel.unsubscribe(client_queue)

    resp = Response(stream_with_context(generate()), mimetype='audio/mpeg')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.headers['Accept-Ranges'] = 'none'
    return resp


@live_bp.route('/live/stream/<int:channel_id>/<path:filename>')
def live_hls_segment(channel_id, filename):
    """HLS 分片文件（路径穿越校验后直接返回磁盘文件）。"""
    channel = _live_channel(channel_id)

    base_dir = os.path.abspath(channel.hls_dir)
    safe = os.path.normpath(filename).replace('\\', '/')
    if not safe or safe.startswith('/') or '..' in safe.split('/'):
        abort(404)

    target = os.path.abspath(os.path.join(base_dir, safe))
    if not (target == base_dir or target.startswith(base_dir + os.sep)):
        abort(404)
    if not os.path.isfile(target):
        abort(404)

    resp = send_file(target, mimetype='video/mp2t')
    resp.headers['Cache-Control'] = 'public, max-age=30'
    return resp
