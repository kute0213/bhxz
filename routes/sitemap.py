"""Sitemap 路由 —— 根据请求域名返回对应的站点地图 XML。

可直接访问 /sitemap.xml 获取 XML 格式的站点地图。
每日凌晨由 services/sitemap_cache.py 后台线程自动刷新，
为每个配置的域名生成独立的 XML 文件存入 /uploads/sitemap/ 目录。
"""

from flask import Blueprint, Response, request
from services.sitemap_cache import sitemap_cache

sitemap_bp = Blueprint('sitemap', __name__)


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