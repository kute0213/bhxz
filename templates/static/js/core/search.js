// 滨海小镇 - 页面内就地搜索（SiteSearch v6 · 每页自带输入框）
//
// 交互约定：
//   - 每个页面的搜索框（.site-search，由 macros/search.html 的 inline_search 渲染）
//     都是独立的就地展开/收起组件；导航栏不再放置搜索输入框。
//   - 折叠态：只显示「搜索」胶囊按钮；点击后按钮收起、输入框平滑展开（双向动画）。
//   - 输入框内有文字 或 光标在输入框内 → 保持展开；
//     无文字 且 失焦（点击外部）→ 平滑收起。
//   - 输入防抖 / 回车 / 点击箭头 → 调用 /api/search，结果渲染到组件下方下拉面板；
//     无任何命中时面板显示「没有找到相关内容」。
//
// 不修改任何路由；旧的 /search 独立页面仍可继续访问。

(function () {
    'use strict';

    // ---------- 常量 ----------
    var API = '/api/search';
    var MAX_KEYWORD_LEN = 60;
    var DEBOUNCE_MS = 220;
    var CLOSE_MS = 150;   // 失焦后延迟收起（ms），给结果面板点击留时间
    var FOCUS_DELAY = 120; // 展开动画开始后再聚焦

    // 分类 tab（与后端 /api/search 对齐）
    var KINDS = [
        { key: 'all',       label: '全部',      icon: 'grid-3x3' },
        { key: 'buildings', label: '公共建筑',  icon: 'building-2' },
        { key: 'guides',    label: '服务器指南', icon: 'book-open' },
        { key: 'music',     label: '大喇叭音频', icon: 'music' },
        { key: 'topics',    label: '讨论帖子',  icon: 'message-square' }
    ];

    var roots = document.querySelectorAll('.site-search');
    if (!roots.length) return;

    function esc(t) {
        var d = document.createElement('div');
        d.textContent = t == null ? '' : String(t);
        return d.innerHTML;
    }

    function refreshIcons() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons(); } catch (_) {}
        }
    }

    function normalizeKind(k) {
        for (var i = 0; i < KINDS.length; i++) {
            if (KINDS[i].key === k) return k;
        }
        return 'all';
    }

    // 所有实例，供全局「点击外部收起」统一处理
    var instances = [];

    Array.prototype.forEach.call(roots, init);

    function init(root) {
        var trigger = root.querySelector('.site-search-trigger');
        var field = root.querySelector('.site-search-field');
        var input = root.querySelector('.site-search-input');
        var clearBtn = root.querySelector('.site-search-clear');
        var submitBtn = root.querySelector('.site-search-submit');
        var panel = root.querySelector('.site-search-panel');
        if (!trigger || !field || !input || !panel) return;

        var st = {
            expanded: false,
            focused: false,
            tab: normalizeKind(root.getAttribute('data-search-kind')),
            timerClose: null,
            timerSearch: null,
            seq: 0
        };

        instances.push({ root: root, state: st, input: input, collapse: collapse });

        // ---------- 展开 / 收起 ----------
        function expand(delay) {
            clearTimeout(st.timerClose);
            if (!st.expanded) {
                st.expanded = true;
                root.classList.add('is-open');
            }
            setTimeout(function () {
                try { input.focus(); } catch (_) {}
            }, typeof delay === 'number' ? delay : FOCUS_DELAY);
        }

        function collapse(force) {
            if (!st.expanded) return;
            // 未强制时，只要输入框还有文字就保持展开
            if (!force && input.value.trim()) return;
            clearTimeout(st.timerClose);
            clearTimeout(st.timerSearch);
            hidePanel();
            st.seq++;   // 丢弃在途请求
            st.expanded = false;
            root.classList.remove('is-open');
        }

        function scheduleClose() {
            clearTimeout(st.timerClose);
            st.timerClose = setTimeout(function () {
                if (!st.focused && !input.value.trim()) collapse(true);
            }, CLOSE_MS);
        }

        function refreshClear() {
            clearBtn.classList.toggle('visible', !!input.value.trim());
        }

        // ---------- 面板渲染 ----------
        function showPanel(html) {
            panel.innerHTML = html;
            panel.classList.add('is-visible');
            panel.setAttribute('aria-hidden', 'false');
            refreshIcons();
        }

        function hidePanel() {
            panel.classList.remove('is-visible');
            panel.setAttribute('aria-hidden', 'true');
            panel.innerHTML = '';
        }

        function activeCount(counts) {
            if (st.tab === 'all') {
                return Object.keys(counts).reduce(function (a, b) { return a + (counts[b] || 0); }, 0);
            }
            return counts[st.tab] || 0;
        }

        function tabBarHtml(counts) {
            var total = Object.keys(counts).reduce(function (a, b) { return a + (counts[b] || 0); }, 0);
            var html = '';
            KINDS.forEach(function (k) {
                var n = k.key === 'all' ? total : (counts[k.key] || 0);
                var badge = n > 0 ? '<span class="site-search-tab-badge">' + n + '</span>' : '';
                html += '<button type="button" class="site-search-tab' + (k.key === st.tab ? ' is-active' : '') + '"' +
                    ' data-kind="' + k.key + '">' +
                    '<i data-lucide="' + k.icon + '" class="w-3.5 h-3.5"></i>' +
                    '<span>' + k.label + '</span>' + badge +
                    '</button>';
            });
            return '<div class="site-search-tabs">' + html + '</div>';
        }

        function itemHtml(item, kind) {
            var sub = [];
            if (kind === 'buildings') {
                if (item.warp_name) sub.push('传送：' + item.warp_name);
                if (item.author_name) sub.push(item.author_name);
            }
            if (kind === 'guides' && item.author_name) sub.push(item.author_name);
            if (kind === 'music') {
                if (item.author_name) sub.push(item.author_name);
                if (item.created_at) sub.push((item.created_at + '').slice(0, 10));
            }
            if (kind === 'topics') {
                if (item.category_name) sub.push(item.category_name);
                if (item.author_name) sub.push(item.author_name);
            }
            return '<a href="' + esc(item.url || '') + '" class="site-search-item">' +
                '<i data-lucide="' + (iconMap(kind)) + '" class="w-4 h-4 site-search-item-icon"></i>' +
                '<div class="flex-1 min-w-0">' +
                '<div class="site-search-item-title">' + esc(item.title) + '</div>' +
                (item.desc ? '<p class="site-search-item-desc">' + esc(item.desc) + '</p>' : '') +
                (sub.length ? '<div class="site-search-item-sub">' + esc(sub.join(' · ')) + '</div>' : '') +
                '</div>' +
                '<i data-lucide="chevron-right" class="w-3.5 h-3.5 site-search-item-arrow"></i>' +
                '</a>';
        }

        function iconMap(kind) {
            return { buildings: 'building-2', guides: 'book-open', music: 'music', topics: 'message-square' }[kind] || 'file';
        }

        function renderResults(data) {
            var counts = data.counts || {};
            var results = data.results || {};
            var html = tabBarHtml(counts);

            if (!activeCount(counts)) {
                html += '<div class="site-search-empty">' +
                    '<i data-lucide="search" class="w-8 h-8 text-cream/30 mx-auto mb-2"></i>' +
                    '<p>没有找到与「' + esc(data.keyword || input.value.trim()) + '」相关的内容</p>' +
                    '</div>';
            } else if (st.tab === 'all') {
                KINDS.forEach(function (k) {
                    if (k.key === 'all') return;
                    var items = results[k.key] || [];
                    if (!items.length) return;
                    html += '<div class="site-search-group">' +
                        '<div class="site-search-group-title">' +
                        '<i data-lucide="' + k.icon + '" class="w-3.5 h-3.5"></i>' +
                        '<span>' + k.label + '</span>' +
                        '<span class="site-search-group-count">' + (counts[k.key] || 0) + '</span>' +
                        '</div>' +
                        items.map(function (it) { return itemHtml(it, k.key); }).join('') +
                        '</div>';
                });
            } else {
                html += (results[st.tab] || []).map(function (it) { return itemHtml(it, st.tab); }).join('');
            }

            showPanel(html);

            panel.querySelectorAll('.site-search-tab').forEach(function (b) {
                b.addEventListener('click', function () {
                    st.tab = b.getAttribute('data-kind');
                    renderResults(data);
                });
            });
        }

        function doSearch(q) {
            q = (q || '').trim().slice(0, MAX_KEYWORD_LEN);
            if (!q) { hidePanel(); scheduleClose(); return; }
            showPanel('<div class="site-search-empty"><i data-lucide="loader-2" class="w-6 h-6 animate-spin mx-auto"></i></div>');
            var seq = ++st.seq;
            fetch(API + '?q=' + encodeURIComponent(q), {
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
            })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (seq !== st.seq) return;          // 过期请求丢弃
                    if (!d || !d.success) { hidePanel(); return; }
                    renderResults(d);
                })
                .catch(function () { if (seq === st.seq) hidePanel(); });
        }

        // ---------- 事件绑定 ----------
        // 点击整个组件（胶囊按钮 / 输入框区域）→ 展开
        root.addEventListener('mousedown', function (e) {
            if (e.target.closest('.site-search-panel')) return;   // 面板内点击不抢焦点
            if (!st.expanded) e.preventDefault();                 // 避免只读瞬间的失焦闪烁
        });
        root.addEventListener('click', function (e) {
            if (e.target.closest('.site-search-panel')) return;
            if (!st.expanded) expand();
        });

        input.addEventListener('focus', function () {
            st.focused = true;
            clearTimeout(st.timerClose);
            if (!st.expanded) expand();
        });
        input.addEventListener('blur', function () {
            st.focused = false;
            scheduleClose();
        });

        input.addEventListener('input', function () {
            clearTimeout(st.timerSearch);
            clearTimeout(st.timerClose);
            refreshClear();
            var q = input.value.trim();
            if (!q) {
                hidePanel();
                scheduleClose();
                return;
            }
            st.timerSearch = setTimeout(function () { doSearch(q); }, DEBOUNCE_MS);
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                clearTimeout(st.timerSearch);
                doSearch(input.value.trim());
            } else if (e.key === 'Escape') {
                e.preventDefault();
                input.value = '';
                refreshClear();
                hidePanel();
                input.blur();
                collapse(true);
            }
        });

        clearBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            input.value = '';
            clearTimeout(st.timerSearch);
            hidePanel();
            refreshClear();
            input.focus();
        });

        submitBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            var q = input.value.trim();
            if (q) {
                clearTimeout(st.timerSearch);
                doSearch(q);
            }
        });

        // 面板内点击不应触发收起
        panel.addEventListener('mousedown', function (e) { e.stopPropagation(); });

        // ---------- 初始化 ----------
        refreshClear();
        var prefill = (root.getAttribute('data-search-value') || '').trim();
        if (prefill) {
            input.value = prefill.slice(0, MAX_KEYWORD_LEN);
            refreshClear();
            // 有初始关键词 → 默认展开（但不抢焦点、不自动搜索）
            st.expanded = true;
            root.classList.add('is-open');
        }
    }

    // 点击组件外部：所有「输入框为空且未聚焦」的实例平滑收起
    document.addEventListener('mousedown', function (e) {
        instances.forEach(function (inst) {
            if (inst.root.contains(e.target)) return;
            if (!inst.state.focused && !inst.input.value.trim()) inst.collapse(true);
        });
    });
})();
