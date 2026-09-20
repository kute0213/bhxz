"""Sitemap 与 robots.txt 路由 —— 根据请求域名返回对应的站点地图 XML。

可直接访问 /sitemap.xml 获取 XML 格式的站点地图。
每日凌晨由 services/sitemap_cache.py 后台线程自动刷新，
为每个配置的域名生成独立的 XML 文件存入 /uploads/sitemap/ 目录。
/robots.txt 按管理面板配置的爬虫策略返回，自动添加 Crawl‑delay 与防火墙防误判规则，
防止爬虫被 DDoS 防护误封。
"""

from flask import Blueprint, Response, request
from config import get_config_value
from services.sitemap_cache import sitemap_cache

sitemap_bp = Blueprint('sitemap', __name__)

# 所有爬虫都不得访问的内部路径（避免触发防火墙可疑访问规则）
_DISALLOWED_PATHS = """
Disallow: /admin/
Disallow: /api/
Disallow: /uploads/
Disallow: /_debug/
"""

# 爬虫请求间隔（秒），防止触发 DDoS 防护阈值（中等强度 150 次/10秒）
_CRAWL_DELAY = "Crawl-delay: 5\n"


def _robots_base_url() -> str:
    """robots.txt 中 Sitemap 引用地址：优先站点域名配置，其次取当前请求根地址。"""
    site_url = get_config_value('SITE_URL', '').strip().rstrip('/')
    if site_url:
        return site_url
    return request.url_root.rstrip('/')


def _generate_robots(policy: str, base: str) -> str:
    """根据策略和基础 URL 生成完整的 robots.txt 内容。

    策略：
      - all:   允许抓取公开页面，但限制内管理后台等路径
      - home:  仅允许抓取主页
      - none:  禁止所有爬虫

    所有策略都附加 Crawl‑delay 和防火墙防误判路径白名单，
    防止合法爬虫被 DDoS 防护模块误封。
    """
    if policy == 'none':
        return (
            "User-agent: *\n"
            "Disallow: /\n"
        )

    if policy == 'home':
        return (
            "User-agent: *\n"
            "Allow: /$\n"
            f"{_DISALLOWED_PATHS}"
            f"{_CRAWL_DELAY}"
            "\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )

    # 'all' 策略 —— 允许公开页面，限制敏感路径
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"{_DISALLOWED_PATHS}"
        f"{_CRAWL_DELAY}"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


@sitemap_bp.route('/robots.txt')
def robots():
    """按管理面板配置的爬虫策略返回 robots.txt。

    自动添加：
      - Crawl‑delay：防止爬虫触发 DDoS 防护阈值
      - Disallow /admin/、/api/ 等敏感路径：防止防火墙误判爬虫请求为恶意探测
    """
    policy = get_config_value('ROBOTS_POLICY', 'all')
    base = _robots_base_url()
    content = _generate_robots(policy, base)
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