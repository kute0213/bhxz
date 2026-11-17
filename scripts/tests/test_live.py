"""音频直播服务测试：参数规范化、ffmpeg 命令、频道与封禁存储、音源分页。"""

import struct

import pytest

import core.db.connection as connection
from services.live import store
from services.live.constants import (
    MODE_LOOP,
    MODE_REC,
    OPUS_MAX_BATCH_PACKETS,
    OPUS_MAX_PACKET_BYTES,
    OPUS_RING_MAX_PACKETS,
    STATUS_LIVE,
    STATUS_STOPPED,
    normalize_speed,
    normalize_title,
    normalize_volume,
)
from services.live.ffmpeg import build_filter_chain, build_loop_cmd, build_rec_cmd
from services.live.constants import MP3_RING_MAX_BYTES, PCM_MAX_CHUNK_BYTES
from services.live.ingest import validate_opus_batch, validate_pcm_chunk
from services.live.mp3 import trim_to_frame
from services.live.runtime import LiveChannel
from services.music.queries import get_user_musics_page


# ---------------------------------------------------------------------------
# 参数规范化
# ---------------------------------------------------------------------------

def test_normalize_volume():
    assert normalize_volume(None) == 1.0
    assert normalize_volume('abc') == 1.0
    assert normalize_volume(-1) == 0.0
    assert normalize_volume(9) == 2.0
    assert normalize_volume('0.5') == 0.5


def test_normalize_speed():
    assert normalize_speed(None) == 1.0
    assert normalize_speed(0.1) == 0.5
    assert normalize_speed(9) == 2.0
    assert normalize_speed('1.5') == 1.5


def test_normalize_title():
    assert normalize_title('  深夜   电台  ') == '深夜 电台'
    assert len(normalize_title('x' * 200)) == 60
    assert normalize_title(None) == ''


# ---------------------------------------------------------------------------
# ffmpeg 命令
# ---------------------------------------------------------------------------

def test_filter_chain_default():
    assert build_filter_chain(1.0, 1.0) == '[0:a]asplit=2[hls][mp3]'


def test_filter_chain_volume_and_speed():
    chain = build_filter_chain(0.6, 1.25)
    assert 'volume=0.600' in chain
    assert 'atempo=1.250' in chain
    assert chain.endswith('asplit=2[hls][mp3]')


def test_build_rec_cmd(tmp_path):
    hls_dir = str(tmp_path / 'live' / '2')
    cmd = build_rec_cmd(hls_dir)
    joined = ' '.join(cmd)

    assert '-f' in cmd and 's16le' in cmd
    assert 'pipe:0' in cmd
    assert '48000' in cmd
    assert 'pipe:1' in cmd
    assert 'libmp3lame' in cmd
    assert str(tmp_path / 'live' / '2' / 'index.m3u8') in cmd
    assert '-stream_loop' not in cmd
    assert 'atempo=' not in joined
    # 部分 ffmpeg 构建把 -thread_queue_size 当作输出选项，加在 pipe:0 前会启动失败
    assert '-thread_queue_size' not in cmd
    # MP3 必须逐帧刷出，否则 muxer 会攒 32KB（约 1.3 秒）才写 stdout
    assert '-flush_packets' in cmd
    assert cmd[cmd.index('-flush_packets') + 1] == '1'
    # 关闭输入探测，否则 ffmpeg 会先攒约 1 秒 PCM 才编码
    assert cmd[cmd.index('-probesize') + 1] == '32'
    assert cmd[cmd.index('-analyzeduration') + 1] == '0'


def test_trim_to_frame():
    """快照起点要前移到完整 MP3 帧头，避免听众接入时先听到一帧噪声。"""
    frame = b'\xff\xfb\x90\x64' + b'x' * 100  # MPEG1 Layer III 192kbps 44.1kHz
    data = b'\x00\x01\x02' + frame + b'y' * 50
    assert trim_to_frame(data) == frame + b'y' * 50

    # 没有合法帧头时原样返回
    assert trim_to_frame(b'\x00\x01\x02') == b'\x00\x01\x02'

    # 指向帧头起点时不做裁剪
    assert trim_to_frame(frame) == frame


def test_mp3_ring_snapshot_is_short():
    """开场快照直接决定听众的固定延迟，必须保持在 0.5 秒量级。"""
    assert MP3_RING_MAX_BYTES <= 16 * 1024


def test_validate_pcm_chunk():
    """PCM 上传校验：空数据 / 长度错位 / 超大分片都要被拒绝。"""
    assert validate_pcm_chunk(b'') == (False, '音频数据为空', 400)

    ok, message, status = validate_pcm_chunk(b'\x00' * 38400)
    assert ok is True and message is None and status is None

    ok, _, status = validate_pcm_chunk(b'\x00' * 3)
    assert ok is False and status == 400

    ok, _, status = validate_pcm_chunk(b'\x00' * (PCM_MAX_CHUNK_BYTES + 4))
    assert ok is False and status == 413


# ---------------------------------------------------------------------------
# Opus 低延迟通道
# ---------------------------------------------------------------------------

def _opus_batch(*packets):
    """按上传格式拼装 Opus 批次：[2 字节大端长度][包]。"""
    return b''.join(struct.pack('>H', len(p)) + p for p in packets)


def test_validate_opus_batch_ok():
    batch = _opus_batch(b'a' * 40, b'b' * 60)
    ok, packets, status = validate_opus_batch(batch)
    assert ok is True and status is None
    assert packets == [b'a' * 40, b'b' * 60]


def test_validate_opus_batch_rejects_bad_input():
    assert validate_opus_batch(b'')[0] is False
    # 长度前缀不完整
    assert validate_opus_batch(b'\x00')[0] is False
    # 声明长度超过剩余数据
    assert validate_opus_batch(b'\x00\x10abc')[0] is False
    # 空包
    assert validate_opus_batch(b'\x00\x00')[0] is False
    # 单包超过 Opus 上限
    too_big = struct.pack('>H', OPUS_MAX_PACKET_BYTES + 1) + b'x' * (OPUS_MAX_PACKET_BYTES + 1)
    ok, _, status = validate_opus_batch(too_big)
    assert ok is False and status == 400
    # 单批帧数过多
    many = _opus_batch(*([b'x' * 10] * (OPUS_MAX_BATCH_PACKETS + 1)))
    ok, _, status = validate_opus_batch(many)
    assert ok is False and status == 400


def _make_channel():
    return LiveChannel({
        'id': 1, 'user_id': 1, 'username': 'alice',
        'title': '测试', 'mode': MODE_REC,
    })


def test_publish_opus_fans_out_and_snapshots():
    channel = _make_channel()
    q, snapshot = channel.subscribe_opus()
    assert snapshot == []

    channel.publish_opus([b'p1', b'p2'])
    assert q.get_nowait() == b'p1'
    assert q.get_nowait() == b'p2'

    # 新听众拿到最近若干包的快照
    _, snapshot = channel.subscribe_opus()
    assert snapshot == [b'p1', b'p2']


def test_opus_ring_is_bounded():
    channel = _make_channel()
    channel.publish_opus([bytes([i]) for i in range(OPUS_RING_MAX_PACKETS + 4)])
    _, snapshot = channel.subscribe_opus()
    assert len(snapshot) == OPUS_RING_MAX_PACKETS
    assert snapshot[-1] == bytes([OPUS_RING_MAX_PACKETS + 3])


def test_opus_stop_notifies_listeners():
    channel = _make_channel()
    q, _ = channel.subscribe_opus()
    channel.publish_opus([b'p1'])
    assert q.get_nowait() == b'p1'

    channel._notify_stop()
    assert q.get_nowait() is None
    # 停止后快照清空，重复订阅不会再收到旧音频
    _, snapshot = channel.subscribe_opus()
    assert snapshot == []


def test_build_loop_cmd(tmp_path):
    hls_dir = str(tmp_path / 'live' / '1')
    cmd = build_loop_cmd('/tmp/song.mp3', hls_dir, 0.8, 1.2)
    joined = ' '.join(cmd)

    assert '-stream_loop' in cmd and '-1' in cmd
    assert '-re' in cmd
    assert '/tmp/song.mp3' in cmd
    assert 'volume=0.800' in joined
    assert 'atempo=1.200' in joined
    assert str(tmp_path / 'live' / '1' / 'index.m3u8') in cmd
    assert 'pipe:1' in cmd
    assert 'libmp3lame' in cmd
    assert 'delete_segments' in joined


# ---------------------------------------------------------------------------
# 存储层（临时 SQLite 库）
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);
CREATE TABLE music (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    username TEXT DEFAULT '',
    title TEXT NOT NULL,
    status INTEGER DEFAULT 0,
    tags TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE live_channels (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    username TEXT DEFAULT '',
    title TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'loop',
    music_id INTEGER DEFAULT NULL,
    volume REAL NOT NULL DEFAULT 1.0,
    speed REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stopped_at TEXT DEFAULT NULL,
    stop_reason TEXT DEFAULT ''
);
CREATE TABLE live_bans (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    banned_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
INSERT INTO users (id, username) VALUES (1, 'alice');
INSERT INTO users (id, username) VALUES (2, 'bob');
INSERT INTO users (id, username) VALUES (3, 'deleted_user');
UPDATE users SET is_deleted = 1 WHERE id = 3;
INSERT INTO music (id, user_id, username, title, status, tags, created_at)
    VALUES (101, 1, 'alice', '公开音频', 2, '轻音乐', '2026-01-01 00:00:00');
INSERT INTO music (id, user_id, username, title, status, tags, created_at)
    VALUES (102, 1, 'alice', '私有音频', 0, '', '2026-01-01 00:00:00');
INSERT INTO music (id, user_id, username, title, status, tags, created_at)
    VALUES (103, 2, 'bob', '别人的音频', 2, '', '2026-01-01 00:00:00');
INSERT INTO music (id, user_id, username, title, status, tags, created_at)
    VALUES (104, 1, 'alice', '被驳回音频', 3, '', '2026-01-01 00:00:00');
"""


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'live-test.db'
    monkeypatch.setattr(connection, 'DB_PATH', str(db_path))
    conn = connection.get_db()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    yield db_path


def test_create_channel_and_loop_limit(temp_db, monkeypatch):
    monkeypatch.setattr(store, 'get_live_max_loop_per_user', lambda: 2)

    ok, ch = store.create_channel(
        1, 'alice', '我的直播', music_id=101, volume=0.8, speed=1.5)
    assert ok is True, ch
    assert ch['mode'] == MODE_LOOP
    assert ch['volume'] == 0.8
    assert ch['speed'] == 1.5
    assert ch['status'] == STATUS_LIVE

    ok2, ch2 = store.create_channel(1, 'alice', '第二个直播', music_id=101)
    assert ok2 is True, ch2

    # 达到上限后不允许继续开播
    ok3, err = store.create_channel(1, 'alice', '第三个直播', music_id=101)
    assert ok3 is False
    assert '最多同时开启 2 个循环播放直播' in err

    # 停止后可重新开播
    store.mark_stopped(ch['id'], '测试停止')
    assert store.get_channel(ch['id'])['status'] == STATUS_STOPPED
    ok4, ch4 = store.create_channel(1, 'alice', '重新开播', music_id=102)
    assert ok4 is True
    assert ch4['music_id'] == 102


def test_channel_id_is_snowflake(temp_db, monkeypatch):
    """直播台 ID 必须是雪花 ID（时间戳量级），不能退回自增小整数。"""
    monkeypatch.setattr(store, 'get_live_max_loop_per_user', lambda: 5)
    ok, ch = store.create_channel(1, 'alice', '雪花 ID', music_id=101)
    assert ok is True, ch
    assert isinstance(ch['id'], int)
    assert ch['id'] > 10 ** 12


def test_rec_channel_limit_independent_from_loop(temp_db):
    """实时录音固定每人 1 个，且不占用循环播放的数量额度。"""
    ok, loop_ch = store.create_channel(1, 'alice', '循环直播', music_id=101)
    assert ok is True

    ok, rec_ch = store.create_channel(1, 'alice', '录音直播', mode=MODE_REC)
    assert ok is True, rec_ch
    assert rec_ch['mode'] == MODE_REC
    assert rec_ch['music_id'] is None

    ok, err = store.create_channel(1, 'alice', '第二个录音', mode=MODE_REC)
    assert ok is False
    assert '1 个实时录音直播' in err

    # 循环直播不受录音限制影响
    ok, err = store.create_channel(1, 'alice', '第二个循环', music_id=101)
    assert ok is True, err

    active = store.get_user_active_channels(1)
    assert {c['mode'] for c in active} == {MODE_LOOP, MODE_REC}


def test_rec_channel_from_other_user_isolation(temp_db):
    ok, _ = store.create_channel(1, 'alice', '录音直播', mode=MODE_REC)
    assert ok is True
    ok, _ = store.create_channel(2, 'bob', 'bob 录音', mode=MODE_REC)
    assert ok is True
    assert len(store.get_user_active_channels(1)) == 1
    assert len(store.get_user_active_channels(2)) == 1


def test_channel_music_ownership_and_status(temp_db):
    # 不能使用别人上传的音频
    ok, err = store.create_channel(1, 'alice', '用别人的音频', music_id=103)
    assert ok is False
    assert '自己上传' in err

    # 支持自己的私有音频
    ok, ch = store.create_channel(1, 'alice', '用私有音频', music_id=102)
    assert ok is True
    store.mark_stopped(ch['id'])

    # 被驳回的音频不可用于直播
    ok, err = store.create_channel(1, 'alice', '用驳回音频', music_id=104)
    assert ok is False
    assert '驳回' in err

    # 不存在的音频
    ok, err = store.create_channel(1, 'alice', '不存在', music_id=999)
    assert ok is False
    assert '不存在' in err


def test_ban_and_unban(temp_db):
    assert store.is_banned(1) is False
    ok, _ = store.ban_user(1, 'alice', '违规直播', banned_by=99)
    assert ok is True
    assert store.is_banned(1) is True

    ok, err = store.create_channel(1, 'alice', '开播', music_id=101)
    assert ok is False
    assert '禁止开播' in err

    bans = store.list_bans()
    assert len(bans) == 1
    assert bans[0]['user_id'] == 1

    ok, _ = store.unban_user(1)
    assert ok is True
    assert store.is_banned(1) is False

    ok, err = store.unban_user(1)
    assert ok is False


def test_find_user_by_username(temp_db):
    assert store.find_user_by_username('ALICE')['id'] == 1
    assert store.find_user_by_username('deleted_user') is None
    assert store.find_user_by_username('') is None


def test_user_musics_page_search_and_private(temp_db):
    items, has_more = get_user_musics_page(1, keyword='', page=1, page_size=20)
    ids = [m['id'] for m in items]
    # 自己的公开 + 私有，排除被驳回音频
    assert ids == [102, 101]
    assert has_more is False

    items, _ = get_user_musics_page(1, keyword='轻音乐', page=1, page_size=20)
    assert [m['id'] for m in items] == [101]

    # 分页：每页 1 条
    page1, more1 = get_user_musics_page(1, page=1, page_size=1)
    page2, more2 = get_user_musics_page(1, page=2, page_size=1)
    assert len(page1) == 1 and more1 is True
    assert len(page2) == 1 and more2 is False
