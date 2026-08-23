"""直播台服务测试：多路并发开播/推流权限/结束/清理。

真实启动 ffmpeg 进程验证直播生命周期；推流数据使用 ffmpeg 生成的合法音频分片，
避免无效字节导致 ffmpeg 提前退出带来的不确定性。
"""

import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from config import FFMPEG_BIN
from services.live_service import LiveBroadcastService


def _valid_audio_chunk():
    """生成一个约 0.5 秒的合法 Opus/Ogg 音频分片（供推流测试）。"""
    fd, path = tempfile.mkstemp(suffix='.ogg')
    os.close(fd)
    try:
        proc = subprocess.run(
            [FFMPEG_BIN, '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.5',
             '-c:a', 'libopus', '-f', 'ogg', path],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) == 0:
            return None
        with open(path, 'rb') as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_live_start_requires_title():
    """空标题无法开播。"""
    svc = LiveBroadcastService()
    ok, msg, bid = svc.start({'id': 1, 'username': 'a'}, '   ')
    assert ok is False
    assert '标题' in msg
    assert bid is None


def test_live_start_stop_flow():
    """开播→状态查询→仅本人可拿令牌→结束。"""
    svc = LiveBroadcastService()
    ok, msg, bid = svc.start({'id': 1, 'username': 'tester'}, '开服公告')
    assert ok is True, msg
    assert bid
    try:
        status = svc.get_status()
        assert status['is_live'] is True
        assert len(status['broadcasts']) == 1
        b = status['broadcasts'][0]
        assert b['id'] == bid
        assert b['title'] == '开服公告'
        assert b['username'] == 'tester'
        assert b['started_at_text']

        # 仅主播本人可取到该路推流令牌
        mine = svc.get_user_broadcast({'id': 1})
        assert mine and mine['id'] == bid and mine['push_token']
        assert svc.get_user_broadcast({'id': 999}) is None
        assert svc.get_live_m3u8_path(bid)
        assert svc.get_live_dir(bid)
    finally:
        svc.stop(bid, {'id': 1, 'username': 'tester'})
    assert svc.get_status()['is_live'] is False
    assert svc.get_live_m3u8_path(bid) is None


def test_live_multiple_concurrent_broadcasts():
    """多路并发：不同用户可同时开播，各自独立目录/播放列表，互不冲突。"""
    svc = LiveBroadcastService()
    ok1, msg1, bid1 = svc.start({'id': 1, 'username': 'A'}, 'A 的直播')
    ok2, msg2, bid2 = svc.start({'id': 2, 'username': 'B'}, 'B 的直播')
    assert ok1 is True, msg1
    assert ok2 is True, msg2
    assert bid1 != bid2
    try:
        status = svc.get_status()
        assert status['is_live'] is True
        assert len(status['broadcasts']) == 2
        ids = {b['id'] for b in status['broadcasts']}
        assert ids == {bid1, bid2}

        # 各路的播放列表路径相互独立
        assert svc.get_live_m3u8_path(bid1) != svc.get_live_m3u8_path(bid2)
        assert svc.get_live_dir(bid1) != svc.get_live_dir(bid2)

        # 各自只能推流到自己的那一路（令牌互不通用 / 非本人一律拒绝）
        tok1 = svc.get_user_broadcast({'id': 1})['push_token']
        tok2 = svc.get_user_broadcast({'id': 2})['push_token']
        assert tok1 != tok2
        assert svc.push(1, tok2, b'x') is False
        assert svc.push(2, tok1, b'x') is False
    finally:
        svc.stop(bid1, {'id': 1, 'username': 'A'})
        svc.stop(bid2, {'id': 2, 'username': 'B'})
    assert svc.get_status()['is_live'] is False


def test_live_one_broadcast_per_user():
    """同一用户同时只允许一路直播。"""
    svc = LiveBroadcastService()
    ok1, msg1, bid1 = svc.start({'id': 9, 'username': 'u'}, '第一路')
    assert ok1 is True
    ok2, msg2, _ = svc.start({'id': 9, 'username': 'u'}, '第二路')
    assert ok2 is False
    assert '已在直播' in msg2
    svc.stop(bid1, {'id': 9, 'username': 'u'})
    # 结束后可再次开播
    ok3, msg3, bid3 = svc.start({'id': 9, 'username': 'u'}, '第三路')
    assert ok3 is True, msg3
    svc.stop(bid3, {'id': 9, 'username': 'u'})


def test_live_push_ownership():
    """推流权限：非主播/错误令牌/空数据拒绝，主播本人可推流。"""
    chunk = _valid_audio_chunk()
    svc = LiveBroadcastService()
    ok, _, bid = svc.start({'id': 7, 'username': 'owner'}, '测试')
    assert ok is True
    try:
        token = svc.get_user_broadcast({'id': 7})['push_token']
        assert token
        assert svc.push(999, token, b'x') is False       # 非主播
        assert svc.push(7, 'bad-token', b'x') is False   # 错误令牌
        assert svc.push(7, token, b'') is False          # 空数据
        if chunk:
            assert svc.push(7, token, chunk) is True     # 主播本人合法推流
            assert svc.push(7, token, chunk) is True     # 连续推流正常
    finally:
        svc.stop(bid, {'id': 7, 'username': 'owner'})
    assert svc.get_status()['is_live'] is False


def test_live_stop_permission():
    """结束直播权限：非主播不可结束，主播本人可结束。"""
    svc = LiveBroadcastService()
    ok, _, bid = svc.start({'id': 3, 'username': 'host'}, '标题')
    assert ok is True
    try:
        assert svc.stop(bid, {'id': 4, 'username': 'x'}) is False
        assert svc.get_status()['is_live'] is True
        assert svc.stop(bid, {'id': 3, 'username': 'host'}) is True
        assert svc.get_status()['is_live'] is False
    finally:
        svc.stop(bid, {'id': 3, 'username': 'host'})


def test_live_admin_force_stop():
    """管理员可强制结束他人直播。"""
    svc = LiveBroadcastService()
    ok, _, bid = svc.start({'id': 5, 'username': 'user5'}, 'x')
    assert ok is True
    try:
        assert svc.stop(bid, {'id': 99, 'username': 'admin'}, admin=True) is True
        assert svc.get_status()['is_live'] is False
    finally:
        svc.stop(bid, {'id': 99, 'username': 'admin'}, admin=True)


def test_live_cleanup():
    """应用关闭时清理全部直播。"""
    svc = LiveBroadcastService()
    ok1, _, bid1 = svc.start({'id': 6, 'username': 'c'}, 'y')
    ok2, _, bid2 = svc.start({'id': 8, 'username': 'd'}, 'z')
    assert ok1 is True and ok2 is True
    svc.cleanup()
    assert svc.get_status()['is_live'] is False
