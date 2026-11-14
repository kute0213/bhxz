"""WebRTC 实时录音接收（aiortc）。

浏览器通过 HTTP POST 提交 SDP offer，服务端在独立 asyncio 线程中完成
SDP/ICE 协商并返回 answer；收到音频帧后解码为 PCM 写入直播 ffmpeg 管线。
不使用 WebSocket，避免与 Waitress 的多线程 WSGI 模型冲突。

注意：
- 浏览器麦克风要求 HTTPS（或 localhost）安全上下文；
- 服务端需可被浏览器通过 UDP 直连（公网 IP + 开放 UDP），
  否则需配置 TURN 中继（LIVE_TURN_URL / LIVE_TURN_USERNAME / LIVE_TURN_PASSWORD）。
"""

import asyncio
import threading

from core.system.logger import log_module, register_module_log
from services.live.constants import PCM_CHANNELS

register_module_log('live')

_loop = None
_loop_lock = threading.Lock()
_aiortc = None


def _load_aiortc():
    """延迟导入 aiortc，未安装时给出明确提示而不是让整个站点导入失败。"""
    global _aiortc
    if _aiortc is not None:
        return _aiortc
    import aiortc  # noqa: F401  (ImportError 交由调用方处理)
    _aiortc = aiortc
    return _aiortc


def _ensure_loop():
    """获取（必要时创建）后台 asyncio 事件循环线程。"""
    global _loop
    if _loop is not None and _loop.is_running():
        return _loop
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever, name='live-webrtc', daemon=True)
        thread.start()
        _loop = loop
    return _loop


def _ice_servers(aiortc):
    from config import (
        LIVE_STUN_SERVERS,
        LIVE_TURN_PASSWORD,
        LIVE_TURN_URL,
        LIVE_TURN_USERNAME,
    )

    servers = []
    for url in LIVE_STUN_SERVERS:
        servers.append(aiortc.RTCIceServer(urls=url))
    if LIVE_TURN_URL:
        servers.append(aiortc.RTCIceServer(
            urls=LIVE_TURN_URL,
            username=LIVE_TURN_USERNAME or None,
            credential=LIVE_TURN_PASSWORD or None,
        ))
    return servers


async def _wait_ice_complete(pc, timeout=10.0):
    """等待 ICE 候选收集完成，返回包含候选的完整 SDP。

    使用短轮询而不是只监听事件，避免「事件在注册前已触发」导致空等超时。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while pc.iceGatheringState != 'complete' and loop.time() < deadline:
        await asyncio.sleep(0.05)
    if pc.iceGatheringState != 'complete':
        log_module('live', 'WARNING', 'LiveWebRTC', 'ICE 候选收集超时')


def _frame_to_pcm(frame):
    """把 aiortc 解码出的音频帧转为 s16le 交错 PCM（双声道）。"""
    try:
        raw = bytes(frame.planes[0])
    except Exception:
        raw = frame.to_ndarray().tobytes()

    layout = getattr(getattr(frame, 'layout', None), 'name', 'stereo')
    if layout == 'mono' and PCM_CHANNELS == 2:
        import array
        samples = array.array('h')
        samples.frombytes(raw[:len(raw) - (len(raw) % 2)])
        stereo = array.array('h')
        for sample in samples:
            stereo.append(sample)
            stereo.append(sample)
        return stereo.tobytes()
    return raw


async def _consume_track(channel, track):
    """持续接收音频帧并写入 ffmpeg stdin。"""
    try:
        while channel.is_live():
            frame = await track.recv()
            pcm = _frame_to_pcm(frame)
            if pcm and not channel.write_pcm(pcm):
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log_module('live', 'WARNING', 'LiveWebRTC', '录音帧接收中断',
                   channel_id=channel.id, error=str(exc))
    finally:
        try:
            track.stop()
        except Exception:
            pass


async def _negotiate(channel, sdp, offer_type):
    aiortc = _load_aiortc()
    pc = aiortc.RTCPeerConnection(
        configuration=aiortc.RTCConfiguration(iceServers=_ice_servers(aiortc)))

    # 同一频道只保留最新的一条推流连接（主播刷新页面后自动替换旧连接）
    old = getattr(channel, '_peer', None)
    channel._peer = pc
    if old is not None and old is not pc:
        try:
            await old.close()
        except Exception:
            pass

    @pc.on('track')
    def _on_track(track):
        if track.kind == 'audio':
            asyncio.ensure_future(_consume_track(channel, track))

    @pc.on('connectionstatechange')
    async def _on_state():
        state = pc.connectionState
        if state in ('failed', 'closed'):
            if getattr(channel, '_peer', None) is pc:
                channel._peer = None
            log_module('live', 'INFO', 'LiveWebRTC', '推流连接状态变化',
                       channel_id=channel.id, state=state)

    try:
        await pc.setRemoteDescription(
            aiortc.RTCSessionDescription(sdp=sdp, type=offer_type))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await _wait_ice_complete(pc)
    except Exception:
        if getattr(channel, '_peer', None) is pc:
            channel._peer = None
        await _safe_close(pc)
        raise

    return {
        'sdp': pc.localDescription.sdp,
        'type': pc.localDescription.type,
    }


def submit_offer(channel, sdp, offer_type):
    """同步提交 SDP offer，返回 (success, answer_or_error)。

    由 HTTP 线程调用；协商在后台 asyncio 线程完成。
    """
    if not sdp or not offer_type:
        return False, 'SDP offer 不能为空'
    try:
        _load_aiortc()
    except Exception:
        return False, '服务器未安装 WebRTC 组件 aiortc，请先安装依赖'
    if not channel.is_live():
        return False, '直播已结束'

    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(
        _negotiate(channel, sdp, offer_type), loop)
    try:
        answer = future.result(timeout=20)
    except Exception as exc:
        log_module('live', 'ERROR', 'LiveWebRTC', 'WebRTC 协商失败',
                   channel_id=channel.id, error=str(exc))
        return False, f'建立 WebRTC 连接失败：{exc}'
    return True, answer


async def _safe_close(pc):
    try:
        await pc.close()
    except Exception:
        pass


def close_channel(channel):
    """关闭频道当前的 WebRTC 连接（直播停止时调用）。"""
    pc = getattr(channel, '_peer', None)
    if pc is None:
        return
    channel._peer = None
    loop = _loop
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(_safe_close(pc), loop)
    except Exception:
        pass
