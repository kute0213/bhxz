"""Sitemap 路由 —— 自动生成站点地图供搜索引擎爬虫使用。

可直接访问 /sitemap.xml 获取 XML 格式的站点地图。
XML 内容由 services/sitemap_cache.py 后台线程每日自动刷新，
刷新时间可在管理面板（/admin/settings）中配置。
"""

from flask import Blueprint, Response
from services.sitemap_cache import sitemap_cache

sitemap_bp = Blueprint('sitemap', __name__)


@sitemap_bp.route('/sitemap.xml')
def sitemap():
    """返回缓存的站点地图 XML。"""
    xml_content = sitemap_cache.get_xml()

    return Response(
        xml_content,
        mimetype='application/xml; charset=utf-8',
        headers={
            'Cache-Control': 'public, max-age=3600',
        },
    )