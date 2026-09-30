"""全站搜索页面：独立搜索页 /search。"""

from flask import request

from core.helpers import render_page
from routes.search import search_bp
import services.search as search_service


@search_bp.route('/search')
def search_page():
    """独立搜索页（输入即搜，结果由 /api/search 无刷新返回）。

    参数：
        q     可选，初始关键词
        type  可选，初始类别（buildings / guides / music / topics），默认 all
    """
    keyword = (request.args.get('q') or '').strip()[:search_service.MAX_KEYWORD_LEN]
    kind = search_service.normalize_kind(request.args.get('type'))
    return render_page('search/index.html', keyword=keyword, kind=kind)
