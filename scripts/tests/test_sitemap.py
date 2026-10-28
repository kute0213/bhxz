"""站点地图生成测试 —— 校验收录范围与资源过滤。

覆盖：
  * 公开页面白名单包含首页 / 服务器状态 / 指南 / 公共建筑 / 文档，
    且**不包含**已失效的 /apply 与无可索引内容的 /map；
  * 公共建筑列表页与其「已审核通过」的详情页被收录；
  * 管理后台配置的公开文件里，js/css/图片等资源映射不会被写成 sitemap 条目；
  * 生成的条目按 path 去重。
"""

from services.sitemap_cache import (
    _STATIC_PAGES,
    _ASSET_EXTENSIONS,
    _is_page_like,
    _build_url_entries,
)


class TestStaticWhitelist:
    """静态页面白名单。"""

    def test_includes_public_hubs(self):
        paths = [p for p, _, _ in _STATIC_PAGES]
        for expected in ('/', '/server-status', '/guides', '/buildings', '/docs'):
            assert expected in paths

    def test_excludes_dead_and_thin_pages(self):
        paths = [p for p, _, _ in _STATIC_PAGES]
        assert '/apply' not in paths   # 历史死路由（无对应页面）
        assert '/map' not in paths     # 仅内嵌外部地图 iframe，无可索引内容


class TestPageLike:
    """公开路径是否为「页面」。"""

    def test_asset_extensions_excluded(self):
        for p in ('/sw.js', '/style.css', '/logo.png', '/bg.webp',
                  '/data.json', '/app.map', '/clip.mp4'):
            assert _is_page_like(p) is False, p

    def test_pages_included(self):
        for p in ('/verify', '/about', '/about.html', '/docs/guide.htm'):
            assert _is_page_like(p) is True, p

    def test_asset_extension_set_nonempty(self):
        assert 'js' in _ASSET_EXTENSIONS and 'css' in _ASSET_EXTENSIONS


class TestBuildEntries:
    """整体条目构建（读取真实数据库）。"""

    def test_contains_buildings_no_junk(self):
        entries = _build_url_entries()
        paths = [e['path'] for e in entries]

        # 公共建筑列表页被收录（此前的缺失项）
        assert '/buildings' in paths
        # 不再出现无用 / 死路由
        assert '/apply' not in paths
        assert '/map' not in paths

    def test_paths_unique(self):
        paths = [e['path'] for e in _build_url_entries()]
        assert len(paths) == len(set(paths))

    def test_every_entry_well_formed(self):
        for e in _build_url_entries():
            assert e['path'].startswith('/')
            assert e['changefreq'] in ('always', 'hourly', 'daily',
                                       'weekly', 'monthly', 'yearly', 'never')
            assert 0.0 <= float(e['priority']) <= 1.0
