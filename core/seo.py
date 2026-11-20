"""SEO / GEO 公共规则 —— 私有页面判定与站点级结构化数据。

Bing 指南要求：可索引页面与登录后 / 内部页面要明确区分；公开页输出
canonical、结构化数据与描述，私有页用 noindex 告知搜索引擎不要收录。
"""

import re

from config import get_config_value

SITE_NAME = '滨海小镇'
SITE_ALTERNATE_NAME = '滨海小镇 Minecraft 服务器社区'
SITE_DESCRIPTION = (
    '滨海小镇是一个面向 Minecraft 玩家的服务器社区，提供服务器实时状态与在线玩家查询、'
    '模组介绍、玩家公共建筑、服务器指南、大喇叭音频和网页地图，欢迎加入小镇与玩家一起创造和分享。'
)

# 不应被搜索引擎收录的路径前缀（登录后 / 操作 / 上传 / 管理后台）
_PRIVATE_PREFIXES = (
    '/admin',
    '/api',
    '/settings',
    '/login',
    '/register',
    '/forgot-password',
    '/logout',
    '/music/my',
    '/music/upload',
    '/music/favorites',
    '/guides/my',
    '/guides/favorites',
    '/guides/create',
    '/guides/edit',
    '/buildings/create',
    '/buildings/edit',
    '/buildings/favorites',
    '/backgrounds/upload',
    '/live/start',
    '/live/rec',
    '/live/my',
    '/game-accounts',
    # 仅内嵌外部地图 iframe，本身没有可索引内容
    '/map',
)


def is_private_path(path: str) -> bool:
    """判断路径是否为不应收录的私有页面。"""
    normalized = (path or '/').split('?', 1)[0].rstrip('/') or '/'
    if any(
        normalized == prefix or normalized.startswith(prefix + '/')
        for prefix in _PRIVATE_PREFIXES
    ):
        return True
    # 编辑页形如 /guides/123/edit、/buildings/45/edit
    return bool(re.match(r'^/(?:guides|buildings)/\d+/edit$', normalized))


def build_site_structured_data(base_url: str) -> dict:
    """构建全站 WebSite + Organization 结构化数据（JSON-LD）。

    显式给出站点名称、别名、描述与语言，便于 Bing / Copilot 正确识别实体，
    降低把站点误判为泛泛「Minecraft 网站」的概率。
    """
    base = (base_url or '').rstrip('/')
    org_id = f'{base}/#organization'
    website_id = f'{base}/#website'

    organization = {
        '@type': 'Organization',
        '@id': org_id,
        'name': SITE_NAME,
        'alternateName': SITE_ALTERNATE_NAME,
        'url': f'{base}/',
        'description': SITE_DESCRIPTION,
        'logo': {
            '@type': 'ImageObject',
            'url': f'{base}/static/img/logo.png',
            'width': 512,
            'height': 512,
        },
    }

    # 配置了有效的 QQ 群链接时作为官方外部主页，增强实体可信度
    qq_url = str(get_config_value('QQ_GROUP_URL', '') or '').strip()
    if qq_url.startswith('http') and '...' not in qq_url:
        organization['sameAs'] = [qq_url]

    return {
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'WebSite',
                '@id': website_id,
                'url': f'{base}/',
                'name': SITE_NAME,
                'alternateName': SITE_ALTERNATE_NAME,
                'description': SITE_DESCRIPTION,
                'inLanguage': 'zh-CN',
                'publisher': {'@id': org_id},
            },
            organization,
        ],
    }


def build_breadcrumb_data(items: list) -> dict:
    """把 [(名称, 绝对 URL), ...] 转成 BreadcrumbList JSON-LD。"""
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {
                '@type': 'ListItem',
                'position': index,
                'name': name,
                'item': url,
            }
            for index, (name, url) in enumerate(items, 1)
        ],
    }
