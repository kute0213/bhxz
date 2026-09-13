"""Sitemap 与 robots.txt 路由 —— 根据请求域名返回对应的站点地图 XML。

可直接访问 /sitemap.xml 获取 XML 格式的站点地图。
每日凌晨由 services/sitemap_cache.py 后台线程自动刷新，
为每个配置的域名生成独立的 XML 文件存入 /uploads/sitemap/ 目录。
/robots.txt 按管理面板配置的爬虫策略返回，并引用 Sitemap。
"""

from flask import Blueprint, Response, request
from config import get_config_value
from services.sitemap_cache import sitemap_cache

sitemap_bp = Blueprint('sitemap', __name__)


# 三种爬虫策略对应的 robots.txt 模板（{base} 会被替换为站点根地址）
_ROBOTS_TEMPLATES = {
    # 允许所有爬虫抓取全部页面
    'all': "User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n",
    # 仅允许爬虫抓取主页（/$ 为 Google 等主流爬虫支持的锚定语法）
    'home': "User-agent: *\nAllow: /$\nDisallow: /\n\nSitemap: {base}/sitemap.xml\n",
    # 禁止所有爬虫
    'none': "User-agent: *\nDisallow: /\n",
}


def _robots_base_url() -> str:
    """robots.txt 中 Sitemap 引用地址：优先站点域名配置，其次取当前请求根地址。"""
    site_url = get_config_value('SITE_URL', '').strip().rstrip('/')
    if site_url:
        return site_url
    return request.url_root.rstrip('/')


@sitemap_bp.route('/robots.txt')
def robots():
    """按管理面板配置的爬虫策略返回 robots.txt。"""
    policy = get_config_value('ROBOTS_POLICY', 'all')
    template = _ROBOTS_TEMPLATES.get(policy, _ROBOTS_TEMPLATES['all'])
    content = template.format(base=_robots_base_url())
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={'Cache-Control': 'public, max-age=3600'},
    )


@sitemap_bp.route('/sitemap.xml')
def sitemap():
    """返回缓存的站点地图 XML。

    根据请求的 Host 头匹配对应的域名文件，
    未匹配到特定域名时尝试使用默认域名。
    """
    host = request.host.split(':')[0]  # 去除端口号

    # 尝试获取该域名专属的 sitemap
    xml_content = sitemap_cache.get_xml_for_domain(host)

    # 未匹配到特定域名时，使用默认域名
    if not xml_content:
        xml_content = sitemap_cache.get_xml()

    return Response(
        xml_content,
        mimetype='application/xml; charset=utf-8',
        headers={
            'Cache-Control': 'public, max-age=3600',
        },
    )