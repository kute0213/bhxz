"""IndexNow 推送测试 —— 校验公网过滤、Key 生成、URL 构建、提交与 Key 文件路由。"""

import json

import pytest
from flask import Flask

import services.indexnow as indexnow
import routes.indexnow as indexnow_route
from config import SETTINGS_REGISTRY


def test_indexnow_settings_in_registry():
    """IndexNow 配置必须出现在系统设置面板（由 SETTINGS_REGISTRY 自动渲染）。"""
    keys = {item[0] for item in SETTINGS_REGISTRY}
    for key in ('INDEXNOW_ENABLED', 'INDEXNOW_KEY', 'INDEXNOW_AUTO_SUBMIT',
                'INDEXNOW_SUBMIT_TIME'):
        assert key in keys
    assert any(item[0] == 'INDEXNOW_ENABLED' and item[5] == 'IndexNow'
               for item in SETTINGS_REGISTRY)


def test_bot_settings_in_registry():
    """假人上限与指令模板需可在系统设置面板中调整。"""
    keys = {item[0] for item in SETTINGS_REGISTRY}
    for key in ('BOT_PENDING_LIMIT', 'BOT_SPAWN_COMMAND', 'BOT_KILL_COMMAND'):
        assert key in keys


class TestPublicBase:
    """仅公网 http/https 域名可提交。"""

    def test_public_domains(self):
        assert indexnow._is_public_base('https://bhxz.tw.kg') is True
        assert indexnow._is_public_base('http://example.com') is True

    def test_local_and_private_rejected(self):
        for base in ('http://localhost:5000', 'http://127.0.0.1',
                     'http://192.168.1.10', 'http://10.0.0.2',
                     'http://intranet', 'ftp://example.com', ''):
            assert indexnow._is_public_base(base) is False, base


class TestKey:
    """Key 生成与格式。"""

    def test_generated_key_is_valid(self):
        key = indexnow.generate_key()
        assert len(key) == 32
        assert indexnow._KEY_RE.match(key)

    def test_save_config_rejects_bad_time(self):
        ok, message = indexnow.save_config(True, True, '25:99')
        assert ok is False
        assert 'HH:MM' in message

    def test_save_config_normalizes_values(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(indexnow.settings_manager, 'bulk_set', captured.update)
        ok, _ = indexnow.save_config('false', '1', '04:05')
        assert ok is True
        assert captured == {
            'INDEXNOW_ENABLED': False,
            'INDEXNOW_AUTO_SUBMIT': True,
            'INDEXNOW_SUBMIT_TIME': '04:05',
        }


class TestBuildUrls:
    """URL 列表复用 sitemap 条目。"""

    def test_build_urls(self, monkeypatch):
        monkeypatch.setattr(
            'services.sitemap_cache._build_url_entries',
            lambda: [{'path': '/'}, {'path': '/guides/1'}, {'path': '/guides/1'}],
        )
        urls = indexnow.build_urls('https://example.com/')
        assert urls == ['https://example.com/', 'https://example.com/guides/1']


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestSubmit:
    """提交请求构造与状态码处理。"""

    def test_submit_payload(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured['url'] = req.full_url
            captured['body'] = json.loads(req.data.decode('utf-8'))
            return _FakeResponse()

        monkeypatch.setattr(indexnow.urllib.request, 'urlopen', fake_urlopen)
        status, message = indexnow.submit_urls(
            'https://example.com', 'a' * 32, ['https://example.com/']
        )
        assert status == 200 and message == ''
        assert captured['url'] == indexnow.ENDPOINT
        assert captured['body']['host'] == 'example.com'
        assert captured['body']['key'] == 'a' * 32
        assert captured['body']['keyLocation'] == f'https://example.com/{"a" * 32}.txt'

    def test_submit_all_disabled(self, monkeypatch):
        monkeypatch.setattr(indexnow, 'is_enabled', lambda: False)
        result = indexnow.submit_all()
        assert result['success'] is False
        assert '未启用' in result['message']


class TestKeyFileRoute:
    """Key 文件路由：匹配返回内容，不匹配返回 404。"""

    @pytest.fixture
    def client(self):
        app = Flask(__name__)
        app.register_blueprint(indexnow_route.indexnow_bp)
        return app.test_client()

    def test_returns_key(self, client, monkeypatch):
        monkeypatch.setattr(indexnow_route, 'get_key', lambda: 'b' * 32)
        resp = client.get(f'/{"b" * 32}.txt')
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == 'b' * 32

    def test_wrong_key_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(indexnow_route, 'get_key', lambda: 'b' * 32)
        assert client.get('/wrong-key.txt').status_code == 404
        monkeypatch.setattr(indexnow_route, 'get_key', lambda: '')
        assert client.get(f'/{"b" * 32}.txt').status_code == 404
