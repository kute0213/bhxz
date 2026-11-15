"""音频直播服务测试：参数规范化、ffmpeg 命令、频道与封禁存储、音源分页。"""

import pytest

import core.db.connection as connection
from services.live import store
from services.live.constants import (
    MODE_LOOP,
    MODE_REC,
    STATUS_LIVE,
    STATUS_STOPPED,
    normalize_speed,
    normalize_title,
    normalize_volume,
)
from services.live.ffmpeg import build_filter_chain, build_loop_cmd, build_rec_cmd
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
