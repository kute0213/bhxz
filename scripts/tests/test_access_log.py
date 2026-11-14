"""访问日志抓取服务测试 —— 生命周期、落库、过滤与 SSE 订阅。"""

import os
import queue
import time

import pytest

import services.access_log as access_log
from services.access_log import store


@pytest.fixture(autouse=True)
def _clean_capture():
    """每个用例前后都确保抓取已停止、数据库已删除。"""
    access_log.stop_capture()
    yield
    access_log.stop_capture()


def test_should_capture_request():
    assert access_log.should_capture_request('/guides', 'GET') is True
    assert access_log.should_capture_request('/admin/access-log', 'GET') is True
    assert access_log.should_capture_request('/static/css/base.css', 'GET') is False
    assert access_log.should_capture_request('/admin/api/access-log/stream', 'GET') is False
    assert access_log.should_capture_request('/guides', 'OPTIONS') is False
    assert access_log.should_capture_request('/guides', 'HEAD') is False


def test_start_record_query_stop_deletes_db():
    ok, _ = access_log.start_capture()
    assert ok is True
    assert access_log.is_capturing() is True
    assert os.path.exists(store.DB_PATH)

    access_log.record_access(
        ip='198.51.100.10', method='GET', path='/hello', query_string='a=1',
        status=200, duration_ms=7, user_id=1, username='admin',
    )
    time.sleep(0.8)

    status = access_log.get_status()
    assert status['running'] is True
    assert status['count'] == 1

    rows = access_log.query_recent(10)
    assert len(rows) == 1
    assert rows[0]['path'] == '/hello'
    assert rows[0]['query_string'] == 'a=1'
    assert rows[0]['status'] == 200
    assert rows[0]['username'] == 'admin'

    ok, message = access_log.stop_capture()
    assert ok is True
    assert access_log.is_capturing() is False
    assert '删除' in message
    assert not os.path.exists(store.DB_PATH)


def test_record_ignored_when_not_capturing():
    access_log.record_access(path='/ignored')
    assert access_log.get_status()['count'] == 0
    assert access_log.query_recent(10) == []


def test_start_stop_idempotent():
    assert access_log.start_capture()[0] is True
    assert access_log.start_capture()[0] is True
    assert access_log.get_status()['count'] == 0

    assert access_log.stop_capture()[0] is True
    assert access_log.stop_capture()[0] is True


def test_sse_subscriber_receives_record_and_stopped():
    client_queue = queue.Queue()
    assert access_log.start_capture()[0] is True
    access_log.subscribe(client_queue)
    try:
        access_log.record_access(path='/sse', method='GET', status=200)
        entry = client_queue.get(timeout=3)
        assert entry['path'] == '/sse'
    finally:
        access_log.unsubscribe(client_queue)
        access_log.stop_capture()


def test_stale_database_removed_on_start():
    """模拟异常退出残留的数据库文件，新会话开启时应被清空重建。"""
    store.delete_store()
    os.makedirs(store.DB_DIR, exist_ok=True)
    with open(store.DB_PATH, 'wb') as f:
        f.write(b'stale duckdb file')
    assert os.path.exists(store.DB_PATH)

    assert access_log.start_capture()[0] is True
    assert access_log.get_status()['count'] == 0
    assert access_log.query_recent(10) == []


def test_sse_live_record_uses_default_message_event(monkeypatch):
    """实时记录必须走默认 message 事件，否则前端 onmessage 收不到。"""
    from flask import Flask
    import core.auth as auth_module
    from routes.admin import admin_bp

    monkeypatch.setattr(
        auth_module, 'get_current_user',
        lambda: {'id': 1, 'username': 'admin', 'is_admin': True},
    )
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.register_blueprint(admin_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1

    assert access_log.start_capture()[0] is True
    response = client.get('/admin/api/access-log/stream?tail=5', buffered=False)
    frames = iter(response.response)
    assert next(frames).startswith(b'event: history')

    access_log.record_access(path='/live-check')
    frame = next(frames)
    try:
        assert frame.startswith(b'data: ')
        assert not frame.startswith(b'event: data')
        assert b'/live-check' in frame
    finally:
        response.close()
