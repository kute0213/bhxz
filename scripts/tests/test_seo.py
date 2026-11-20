"""SEO / GEO 回归测试：公开页元数据、结构化数据、私有页 noindex、sitemap。"""

import re

import pytest

import app as app_module

# 可被搜索引擎收录的公开页面
INDEXABLE_PAGES = [
    '/', '/server-status', '/backgrounds', '/music', '/docs',
    '/buildings', '/guides', '/live',
]

# 需要登录或没有可索引内容的页面
NOINDEX_PAGES = ['/login', '/register', '/forgot-password', '/map']


@pytest.fixture(scope='module')
def client():
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


def _extract(html: str):
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    desc = re.search(r'<meta name="description" content="(.*?)">', html, re.S)
    clean = lambda m: re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''
    return clean(title), clean(desc)


@pytest.mark.parametrize('path', INDEXABLE_PAGES)
def test_public_page_meta(client, path):
    resp = client.get(path, follow_redirects=True)
    assert resp.status_code == 200
    title, desc = _extract(resp.get_data(as_text=True))
    assert len(title) >= 28, f'{path} 标题过短: {title}'
    assert len(desc) >= 70, f'{path} 描述过短: {desc}'


@pytest.mark.parametrize('path', NOINDEX_PAGES)
def test_noindex_page_meta(client, path):
    """登录类页面与无可索引内容的页面必须 noindex，且不输出 canonical。"""
    resp = client.get(path, follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    title, desc = _extract(html)
    assert len(title) >= 28
    assert len(desc) >= 70
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert 'rel="canonical"' not in html
    assert resp.headers.get('X-Robots-Tag') == 'noindex, nofollow'


def test_public_page_structured_data(client):
    html = client.get('/').get_data(as_text=True)
    assert '<meta name="robots" content="index, follow">' in html
    assert 'application/ld+json' in html
    assert '"@type": "WebSite"' in html
    assert '"@type": "Organization"' in html
    assert 'static/img/og-cover.png' in html
    assert 'summary_large_image' in html


def test_breadcrumb_structured_data(client):
    html = client.get('/music').get_data(as_text=True)
    assert '"@type": "BreadcrumbList"' in html


def test_bing_verification_meta(client, monkeypatch):
    import core.template_context as context

    original = context.get_config_value

    def fake_get(key, default=None):
        if key == 'BING_SITE_VERIFICATION':
            return 'ABC123456789'
        return original(key, default)

    monkeypatch.setattr(context, 'get_config_value', fake_get)
    html = client.get('/').get_data(as_text=True)
    assert '<meta name="msvalidate.01" content="ABC123456789">' in html


def test_sitemap_only_public_urls(client):
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    xml = resp.get_data(as_text=True)
    assert '/live</loc>' in xml
    for path in ('/login', '/register', '/forgot-password', '/settings',
                 '/music/upload', '/admin', '/game-accounts'):
        assert f'{path}</loc>' not in xml
    assert '/uploads/' not in xml


def test_sitemap_supports_etag(client):
    first = client.get('/sitemap.xml')
    etag = first.headers.get('ETag')
    assert etag
    second = client.get('/sitemap.xml', headers={'If-None-Match': etag})
    assert second.status_code == 304


def test_robots_allows_public_assets(client, monkeypatch):
    import routes.sitemap as sitemap_route

    original = sitemap_route.get_config_value

    def fake_get(key, default=None):
        if key == 'ROBOTS_POLICY':
            return 'all'
        return original(key, default)

    monkeypatch.setattr(sitemap_route, 'get_config_value', fake_get)
    content = client.get('/robots.txt').get_data(as_text=True)
    assert 'Allow: /' in content
    assert 'Allow: /uploads/backgrounds/' in content
    assert 'Disallow: /uploads/' in content
    assert 'Crawl-delay: 1' in content
    assert 'Sitemap: ' in content


def test_trailing_slash_redirects(client):
    resp = client.get('/music/?from=seo')
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/music?from=seo')


def test_static_asset_not_redirected(client):
    resp = client.get('/static/css/base.css')
    assert resp.status_code == 200
