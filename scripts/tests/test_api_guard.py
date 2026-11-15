"""API 防火墙限流测试：实时录音 PCM 上传使用独立配额，不占用普通 API 额度。"""

import pytest

import services.firewall.api_guard as guard


@pytest.fixture(autouse=True)
def clean_counters():
    guard._counters.clear()
    yield
    guard._counters.clear()


def test_default_limit(monkeypatch):
    monkeypatch.setattr(guard, '_get_limit', lambda: (True, 3, 60))

    for _ in range(3):
        allowed, remaining, _ = guard.check_api_rate_limit('1.1.1.1')
        assert allowed is True
    assert remaining == 0

    allowed, remaining, retry_after = guard.check_api_rate_limit('1.1.1.1')
    assert allowed is False and remaining == 0 and retry_after >= 1


def test_pcm_bucket_is_independent(monkeypatch):
    """普通 API 配额耗尽不影响 PCM 上传，反之亦然。"""
    monkeypatch.setattr(guard, '_get_limit', lambda: (True, 3, 60))

    for _ in range(3):
        assert guard.check_api_rate_limit('2.2.2.2')[0] is True
    assert guard.check_api_rate_limit('2.2.2.2')[0] is False

    # 同一 IP 的 PCM 独立桶不受普通 API 封禁影响
    for _ in range(5):
        allowed, _, _ = guard.check_api_rate_limit(
            '2.2.2.2', 'live_pcm', guard.PCM_UPLOAD_LIMIT, guard.PCM_UPLOAD_WINDOW)
        assert allowed is True


def test_pcm_sustained_upload_not_blocked(monkeypatch):
    """按 5 次/秒持续 1 分钟（300 次）不应被 60 次/分钟的普通配额误封。"""
    monkeypatch.setattr(guard, '_get_limit', lambda: (True, 60, 60))

    for _ in range(300):
        allowed, _, _ = guard.check_api_rate_limit(
            '3.3.3.3', 'live_pcm', guard.PCM_UPLOAD_LIMIT, guard.PCM_UPLOAD_WINDOW)
        assert allowed is True

    # 超过独立配额后仍会被限制
    for _ in range(guard.PCM_UPLOAD_LIMIT - 300):
        assert guard.check_api_rate_limit(
            '3.3.3.3', 'live_pcm', guard.PCM_UPLOAD_LIMIT,
            guard.PCM_UPLOAD_WINDOW)[0] is True
    assert guard.check_api_rate_limit(
        '3.3.3.3', 'live_pcm', guard.PCM_UPLOAD_LIMIT,
        guard.PCM_UPLOAD_WINDOW)[0] is False


def test_disabled_global_switch(monkeypatch):
    import config
    monkeypatch.setattr(
        config, 'get_config_value',
        lambda key, default=None: (
            False if key == 'API_RATE_LIMIT_ENABLED' else default))

    for _ in range(100):
        assert guard.check_api_rate_limit('4.4.4.4')[0] is True


def test_reset_clears_all_buckets(monkeypatch):
    monkeypatch.setattr(guard, '_get_limit', lambda: (True, 1, 60))

    assert guard.check_api_rate_limit('5.5.5.5')[0] is True
    assert guard.check_api_rate_limit('5.5.5.5')[0] is False
    assert guard.check_api_rate_limit('5.5.5.5', 'live_pcm', 1, 60)[0] is True
    assert guard.check_api_rate_limit('5.5.5.5', 'live_pcm', 1, 60)[0] is False

    guard.reset_api_limit('5.5.5.5')

    assert guard.check_api_rate_limit('5.5.5.5')[0] is True
    assert guard.check_api_rate_limit('5.5.5.5', 'live_pcm', 1, 60)[0] is True


def test_get_api_stats_dedupes_buckets(monkeypatch):
    monkeypatch.setattr(guard, '_get_limit', lambda: (True, 10, 60))

    guard.check_api_rate_limit('6.6.6.6')
    guard.check_api_rate_limit('6.6.6.6', 'live_pcm', 10, 60)

    assert guard.get_api_stats()['tracked_ips'] == 1


# ---------------------------------------------------------------------------
# 请求桶判定：只有已登录用户上传的 PCM 才使用独立配额
# ---------------------------------------------------------------------------

def _bucket(path, method='POST', user_id=None):
    flask = pytest.importorskip('flask')
    app = flask.Flask(__name__)
    app.secret_key = 'test-secret'
    with app.test_request_context(path, method=method):
        if user_id is not None:
            flask.session['user_id'] = user_id
        return guard._request_bucket(flask.request)[0]


def test_pcm_bucket_requires_login():
    assert _bucket('/api/live/123/pcm', user_id=1) == 'live_pcm'
    assert _bucket('/api/live/123/pcm') == 'default'


def test_pcm_bucket_only_matches_post_pcm():
    assert _bucket('/api/live/123/pcm', method='GET', user_id=1) == 'default'
    assert _bucket('/api/live/123/status', user_id=1) == 'default'
    assert _bucket('/api/live/abc/pcm', user_id=1) == 'default'
