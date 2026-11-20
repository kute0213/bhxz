"""SEO 元数据回归测试：公开页标题/描述长度与尾部斜杠规范化。"""

import re

import pytest

import app as app_module

# 可被搜索引擎收录的公开页面
PUBLIC_PAGES = [
    '/', '/server-status', '/backgrounds', '/music', '/login', '/register',
    '/forgot-password', '/docs', '/map', '/buildings', '/guides', '/live',
]


@pytest.fixture(scope='module')
def client():
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


def _extract(html: str):
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    desc = re.search(r'<meta name="description" content="(.*?)">', html, re.S)
    clean = lambda m: re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''
    return clean(title), clean(desc)


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_public_page_meta(client, path):
    resp = client.get(path, follow_redirects=True)
    assert resp.status_code == 200
    title, desc = _extract(resp.get_data(as_text=True))
    assert len(title) >= 28, f'{path} 标题过短: {title}'
    assert len(desc) >= 70, f'{path} 描述过短: {desc}'


def test_trailing_slash_redirects(client):
    resp = client.get('/music/?from=seo')
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/music?from=seo')


def test_static_asset_not_redirected(client):
    resp = client.get('/static/css/base.css')
    assert resp.status_code == 200
