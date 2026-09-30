// 滨海小镇 - 全站统一搜索入口（SiteSearch）
//
// 交互约定（重写后）：
//   - 页面上的「搜索框」不再是就地展开/置顶的输入框；
//   - 点击搜索框（或导航栏搜索入口）→ 直接跳转到独立搜索页 /search；
//   - 搜索页内含输入框、分类切换与「返回」按钮，点击返回回到原页面。
//
// 用法：给任意元素加 data-search-open="<类别>"：
//   - 类别可省略或为 all，表示打开全站搜索（默认）；
//   - 也可为 buildings / guides / music / topics，仅作为搜索页初始分类。
//   例：<div class="search-entry" data-search-open="buildings">…</div>
var SiteSearch = (function () {
    var SEARCH_PAGE = '/search';

    function open(kind) {
        var url = SEARCH_PAGE;
        if (kind && kind !== 'all') {
            url += '?type=' + encodeURIComponent(kind);
        }
        window.location.href = url;
    }

    function bind(root) {
        (root || document).querySelectorAll('[data-search-open]').forEach(function (el) {
            if (el.dataset.searchBound === '1') return;
            el.dataset.searchBound = '1';
            el.addEventListener('click', function (e) {
                e.preventDefault();
                open(el.getAttribute('data-search-open'));
            });
            // 键盘可达：Enter / 空格等同点击
            el.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    open(el.getAttribute('data-search-open'));
                }
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { bind(); });
    } else {
        bind();
    }

    return { open: open, bind: bind };
})();
