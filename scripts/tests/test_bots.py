"""假人（BOT）申请测试：坐标解析、申请校验、审批 RCON、到期自动下线、待审核上限。"""

import pytest

import core.db.connection as connection
import services.bot_applications as bot_app
import services.content_limits as limits
from routes.bots import parse_pos_response

SCHEMA = """
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    username VARCHAR
);
INSERT INTO users (id, username) VALUES (1, 'alice');
INSERT INTO users (id, username) VALUES (9, 'admin');

CREATE TABLE bot_applications (
    id BIGINT PRIMARY KEY,
    applicant_id BIGINT NOT NULL,
    bot_name VARCHAR NOT NULL,
    pos_x DOUBLE NOT NULL DEFAULT 0,
    pos_y DOUBLE NOT NULL DEFAULT 0,
    pos_z DOUBLE NOT NULL DEFAULT 0,
    offline_at VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'pending',
    reject_reason VARCHAR DEFAULT '',
    reviewed_by BIGINT DEFAULT NULL,
    reviewed_at VARCHAR DEFAULT NULL,
    executed_at VARCHAR DEFAULT NULL,
    killed_at VARCHAR DEFAULT NULL,
    last_error VARCHAR DEFAULT '',
    created_at VARCHAR NOT NULL
);
"""


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'bot-test.db'
    monkeypatch.setattr(connection, 'DB_PATH', str(db_path))
    conn = connection.get_db()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    yield db_path


# ---------------------------------------------------------------------------
# 坐标解析
# ---------------------------------------------------------------------------

def test_parse_pos_response_sample():
    raw = 'XCZSS has the following entity data: [50000.39276052492d, 61.0d, -49794.751065425844d]'
    x, y, z = parse_pos_response(raw)
    assert x == pytest.approx(50000.39276052492)
    assert y == pytest.approx(61.0)
    assert z == pytest.approx(-49794.751065425844)


def test_parse_pos_response_invalid():
    assert parse_pos_response('No entity was found') is None
    assert parse_pos_response('RCON 连接失败') is None
    assert parse_pos_response('') is None


# ---------------------------------------------------------------------------
# 申请
# ---------------------------------------------------------------------------

def test_create_application_and_duplicate(temp_db):
    ok, msg = bot_app.create_application(
        1, 'kute_bot', 1.5, 64, -2.25, '2099-01-01 00:00:00')
    assert ok is True, msg

    # 同名仍有待审核记录时拒绝重复提交
    ok2, msg2 = bot_app.create_application(
        1, 'kute_bot', 0, 0, 0, '2099-01-01 00:00:00')
    assert ok2 is False
    assert '已有待审核' in msg2


def test_create_application_validates_input(temp_db):
    ok, msg = bot_app.create_application(
        1, 'ab', 0, 0, 0, '2099-01-01 00:00:00')
    assert ok is False and msg

    ok, msg = bot_app.create_application(
        1, 'kute_bot', 'x', 0, 0, '2099-01-01 00:00:00')
    assert ok is False and '坐标' in msg

    ok, msg = bot_app.create_application(
        1, 'kute_bot', 0, 0, 0, '2000-01-01 00:00:00')
    assert ok is False and '晚于当前时间' in msg


def test_reject_application(temp_db):
    ok, _ = bot_app.create_application(
        1, 'kute_bot', 0, 64, 0, '2099-01-01 00:00:00')
    assert ok
    app_id = bot_app.get_pending_applications()[0]['id']

    ok, msg = bot_app.reject_application(app_id, 9, '信息不完整')
    assert ok is True, msg
    row = bot_app.get_application_by_id(app_id)
    assert row['status'] == 'rejected'
    assert row['reject_reason'] == '信息不完整'


# ---------------------------------------------------------------------------
# 审批生成 / 到期下线（RCON 以 mock 替代）
# ---------------------------------------------------------------------------

def test_approve_executes_spawn_command(temp_db, monkeypatch):
    calls = []
    monkeypatch.setattr(bot_app, 'execute_command', lambda cmd, **kw: calls.append(cmd) or 'ok')
    monkeypatch.setattr(bot_app, 'get_config_value',
                        lambda key, default=None: default)

    ok, _ = bot_app.create_application(
        1, 'kute_bot', 1.5, 64, -2.25, '2099-01-01 00:00:00')
    assert ok
    app_id = bot_app.get_pending_applications()[0]['id']

    ok, msg = bot_app.approve_application(app_id, 9)
    assert ok is True, msg
    assert calls == ['player kute_bot spawn at 1.500 64.000 -2.250']
    assert bot_app.get_application_by_id(app_id)['status'] == 'approved'


def test_process_expired_bots_kills(temp_db, monkeypatch):
    calls = []
    monkeypatch.setattr(bot_app, 'execute_command', lambda cmd, **kw: calls.append(cmd) or 'ok')
    monkeypatch.setattr(bot_app, 'get_config_value',
                        lambda key, default=None: default)

    ok, _ = bot_app.create_application(
        1, 'kute_bot', 0, 64, 0, '2099-01-01 00:00:00')
    assert ok
    app_id = bot_app.get_pending_applications()[0]['id']
    ok, _ = bot_app.approve_application(app_id, 9)
    assert ok

    # 把下线时间改到过去，模拟到期
    conn = connection.get_db()
    try:
        conn.execute(
            "UPDATE bot_applications SET offline_at = '2000-01-01 00:00:00' WHERE id = ?",
            (app_id,),
        )
        conn.commit()
    finally:
        conn.close()

    assert bot_app.process_expired_bots() == 1
    assert calls[-1] == 'kill kute_bot'
    row = bot_app.get_application_by_id(app_id)
    assert row['status'] == 'killed'
    assert row['killed_at']


def test_rcon_failure_keeps_approved(temp_db, monkeypatch):
    monkeypatch.setattr(bot_app, 'execute_command',
                        lambda cmd, **kw: 'RCON 连接失败')
    monkeypatch.setattr(bot_app, 'get_config_value',
                        lambda key, default=None: default)

    ok, _ = bot_app.create_application(
        1, 'kute_bot', 0, 64, 0, '2099-01-01 00:00:00')
    assert ok
    app_id = bot_app.get_pending_applications()[0]['id']
    ok, _ = bot_app.approve_application(app_id, 9)
    assert ok is False
    assert bot_app.get_application_by_id(app_id)['status'] == 'pending'


# ---------------------------------------------------------------------------
# 待审核上限
# ---------------------------------------------------------------------------

def test_bot_pending_limit(temp_db, monkeypatch):
    def fake_get(key, default=None):
        return {'MAX_PENDING_CONTENT': 5, 'BOT_PENDING_LIMIT': 2}.get(key, default)

    monkeypatch.setattr(limits, 'get_config_value', fake_get)
    # 只保留假人类型，避免依赖其它内容表
    monkeypatch.setattr(limits, '_PENDING_TYPES', {
        'bot': ('bot_applications', 'applicant_id', "status = 'pending'",
                'BOT_PENDING_LIMIT', '假人'),
    })
    user = {'id': 1, 'is_admin': False}

    for name in ('bot_one', 'bot_two'):
        ok, _ = bot_app.create_application(
            1, name, 0, 64, 0, '2099-01-01 00:00:00')
        assert ok

    allowed, msg = limits.check_pending_limit(user, 'bot')
    assert allowed is False
    assert '假人' in msg

    # 管理员豁免
    assert limits.check_pending_limit({'id': 1, 'is_admin': True}, 'bot')[0] is True
