"""全站搜索 API：一次返回各类别命中结果（供搜索页无刷新渲染）。"""

from flask import request, jsonify, url_for

from routes.search import search_bp
import services.search as search_service


def _build_urls(results):
    """为各类型结果补充前端跳转链接与统一展示字段。"""
    for b in results['buildings']:
        b['url'] = url_for('buildings.building_detail', building_id=b['id'])
        b['meta'] = b.get('author_name') or '未知'
        b['sub'] = f"/res tp {b['warp_name']}" if b.get('warp_name') else ''
    for g in results['guides']:
        g['url'] = url_for('guides.guide_detail', guide_id=g['id'])
        g['meta'] = g.get('author_name') or '未知'
    for m in results['music']:
        m['url'] = url_for('main.music_page') + f"#music-{m['id']}"
        m['meta'] = m.get('author_name') or '未知'
    for t in results['topics']:
        t['url'] = url_for('discussion.detail', topic_id=t['id'])
        t['meta'] = t.get('author_name') or '未知'
        t['sub'] = t.get('category_name') or ''


@search_bp.route('/api/search')
def api_search():
    """全站搜索 API。

    参数：
        q  关键词
    每类结果条数由系统设置 SEARCH_PER_PAGE 控制，请求参数无法覆盖。
    """
    keyword = request.args.get('q') or ''
    kw, results, counts = search_service.search(keyword)
    _build_urls(results)
    return jsonify({
        'success': True,
        'keyword': kw,
        'page_size': search_service.search_limit(),
        'counts': counts,
        'results': results,
    })
