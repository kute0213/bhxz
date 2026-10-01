// 滨海小镇 - 全站统一搜索入口（SiteSearch v4 · 就地展开版）
//
// 交互约定：
//   - 导航栏搜索区域是一个可原地展开/收起的容器
//   - 点击图标或触发器 → 平滑展开输入框（宽度过渡），自动聚焦
//   - 输入框内有文字 OR 当前有焦点 → 保持展开
//   - 无文字 AND 失焦 AND 点击了外部 → 平滑收起
//   - 回车 / 点击放大镜 → 调用 /api/search → 下拉面板渲染结果
//   - 下拉面板点结果直接跳转，关闭按钮关闭结果面板
//
// 不修改任何路由；旧的 /search 独立页面可继续访问但导航入口不再跳转过去。

(function () {
    'use strict';

    // ---------- 常量 ----------
    var API = '/api/search';
    var MAX_KEYWORD_LEN = 60;
    var DEBOUNCE_MS = 220;
    var CLOSE_MS = 150; // 失焦延迟关闭（ms），给结果面板点击留时间

    // 分类 tab（与后端 /api/search 对齐）
    var KINDS = [
        { key: 'all',      label: '全部',       icon: 'grid-3x3' },
        { key: 'buildings',label: '公共建筑',    icon: 'building-2' },
        { key: 'guides',   label: '服务器指南',  icon: 'book-open' },
        { key: 'music',    label: '大喇叭音频',  icon: 'music' },
        { key: 'topics',   label: '讨论帖子',    icon: 'message-square' },
    ];

    // ---------- DOM ----------
    var root = document.getElementById('nav-search');
    if (!root) {
        // 没有 .nav-search 容器的页面直接跳过（例如旧的 /search 页面自身）
        return;
    }
    var btn = root.querySelector('.nav-search-btn');
    var inputWrap = root.querySelector('.nav-search-input-wrap');
    var input = root.querySelector('.nav-search-input');
    var clearBtn = root.querySelector('.nav-search-clear');
    var submitBtn = root.querySelector('.nav-search-submit');
    var panel = root.querySelector('.nav-search-panel');

    if (!btn || !inputWrap || !input || !panel) return;

    // ---------- 状态 ----------
    var state = {
        expanded: false,      // 搜索框当前是否展开
        focused: false,       // 输入框是否有焦点
        timerClose: null,     // 延迟关闭计时器
        timerSearch: null,    // 防抖搜索计时器
        seq: 0,               // 请求序列号，只渲染最后一次请求
        currentTab: 'all',    // 当前分类 tab
    };

    // ---------- 工具 ----------
    function esc(t) { var d = document.createElement('div'); d.textContent = t == null ? '' : String(t); return d.innerHTML; }
    function refreshIcons() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons(); } catch (_) {}
        }
    }

    // ---------- 展开 / 收起 ----------
    function expand() {
        if (state.expanded) return;
        clearTimeout(state.timerClose);
        state.expanded = true;
        root.classList.add('is-open');
        // 过渡结束后自动聚焦（让输入框获得光标）
        // 但 transition 时长是 280ms，稍微延迟
        setTimeout(function () {
            input.focus();
            input.select();
        }, 120);
    }

    function collapse(force) {
        if (!state.expanded) return;
        clearTimeout(state.timerClose);
        // 如果没强制，还要满足「没有文字」
        if (!force && input.value.trim()) return;
        // 关闭结果面板
        panel.classList.remove('is-visible');
        panel.innerHTML = '';
        state.expanded = false;
        root.classList.remove('is-open');
    }

    function scheduleClose() {
        clearTimeout(state.timerClose);
        state.timerClose = setTimeout(function () {
            if (!state.focused && !input.value.trim()) collapse(true);
        }, CLOSE_MS);
    }

    // ---------- 事件绑定 ----------

    // 1) 点击按钮：展开
    btn.addEventListener('click', function () {
        expand();
    });
    btn.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            expand();
        }
    });

    // 2) 输入框焦点
    input.addEventListener('focus', function () {
        state.focused = true;
        clearTimeout(state.timerClose);
        // 如果没展开就展开（聚焦总是展开）
        if (!state.expanded) expand();
    });
    input.addEventListener('blur', function () {
        state.focused = false;
        scheduleClose();
    });

    // 3) 输入：防抖搜索
    input.addEventListener('input', function () {
        var q = input.value.trim();
        clearTimeout(state.timerSearch);
        clearTimeout(state.timerClose);
        if (!q) {
            // 清空时立即隐藏面板
            panel.classList.remove('is-visible');
            panel.innerHTML = '';
            refreshClear();
            scheduleClose();
            return;
        }
        refreshClear();
        state.timerSearch = setTimeout(function () { doSearch(q); }, DEBOUNCE_MS);
    });

    // 4) 回车立即搜索
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            clearTimeout(state.timerSearch);
            doSearch(input.value.trim());
        } else if (e.key === 'Escape') {
            e.preventDefault();
            input.value = '';
            panel.classList.remove('is-visible');
            refreshClear();
            input.blur();
            collapse(true);
        }
    });

    // 5) 清空按钮
    clearBtn.addEventListener('click', function () {
        input.value = '';
        clearTimeout(state.timerSearch);
        panel.classList.remove('is-visible');
        panel.innerHTML = '';
        refreshClear();
        input.focus();
    });

    // 6) 放大镜按钮点击 = 立即搜索
    submitBtn.addEventListener('click', function () {
        if (!state.expanded) { expand(); return; }
        var q = input.value.trim();
        if (q) {
            clearTimeout(state.timerSearch);
            doSearch(q);
        }
    });

    // 7) 点击面板外 → 可能触发收起（由 blur 处理）
    //    但面板内点击不应触发关闭：在面板上阻止冒泡
    panel.addEventListener('mousedown', function (e) { e.stopPropagation(); });

    // ---------- 渲染 ----------
    function refreshClear() {
        clearBtn.classList.toggle('visible', !!input.value.trim());
    }

    function renderTabBar(data) {
        var counts = data && data.counts ? data.counts : {};
        var active = state.currentTab;
        var activeCount = active === 'all'
            ? Object.values(counts).reduce(function (a, b) { return a + (b || 0); }, 0)
            : (counts[active] || 0);

        var html = '';
        KINDS.forEach(function (k) {
            var badge = '';
            if (k.key === 'all') {
                var total = Object.values(counts).reduce(function (a, b) { return a + (b || 0); }, 0);
                if (total > 0) badge = '<span class="nav-search-tab-badge">' + total + '</span>';
            } else {
                var c = counts[k.key] || 0;
                if (c > 0) badge = '<span class="nav-search-tab-badge">' + c + '</span>';
            }
            html += '<button type="button" class="nav-search-tab' + (k.key === active ? ' is-active' : '') + '"' +
                ' data-kind="' + k.key + '">' +
                '<i data-lucide="' + k.icon + '" class="w-3.5 h-3.5"></i>' +
                '<span>' + k.label + '</span>' + badge +
                '</button>';
        });
        return '<div class="nav-search-tabs">' + html + '</div>';
    }

    function itemHtml(item, kind) {
        var url = item.url || '';
        var desc = item.desc ? '<p class="nav-search-item-desc">' + esc(item.desc) + '</p>' : '';
        var sub = [];
        if (kind === 'buildings') { if (item.warp_name) sub.push('传送：' + item.warp_name); if (item.author_name) sub.push(item.author_name); }
        if (kind === 'guides')   { if (item.author_name) sub.push(item.author_name); }
        if (kind === 'music')    { if (item.author_name) sub.push(item.author_name); if (item.created_at) sub.push((item.created_at + '').slice(0, 10)); }
        if (kind === 'topics')   { if (item.category_name) sub.push(item.category_name); if (item.author_name) sub.push(item.author_name); }
        var subLine = sub.length ? '<div class="nav-search-item-sub">' + esc(sub.join(' · ')) + '</div>' : '';
        var iconMap = { buildings: 'building-2', guides: 'book-open', music: 'music', topics: 'message-square' };
        return '<a href="' + esc(url) + '" class="nav-search-item">' +
            '<i data-lucide="' + (iconMap[kind] || 'file') + '" class="w-4 h-4 nav-search-item-icon"></i>' +
            '<div class="flex-1 min-w-0">' +
            '<div class="nav-search-item-title">' + esc(item.title) + '</div>' +
            desc + subLine +
            '</div>' +
            '<i data-lucide="chevron-right" class="w-3.5 h-3.5 nav-search-item-arrow"></i>' +
            '</a>';
    }

    function renderResults(data) {
        var counts = data.counts || {};
        var results = data.results || {};
        var active = state.currentTab;
        var activeCount = active === 'all'
            ? Object.values(counts).reduce(function (a, b) { return a + (b || 0); }, 0)
            : (counts[active] || 0);

        var html = renderTabBar(data);

        if (!activeCount) {
            html += '<div class="nav-search-empty">' +
                '<i data-lucide="search" class="w-8 h-8 text-cream/30 mx-auto mb-2"></i>' +
                '<p>没有找到与「' + esc(data.keyword || input.value.trim()) + '」相关的内容</p>' +
                '</div>';
        } else if (active === 'all') {
            KINDS.forEach(function (k) {
                if (k.key === 'all') return;
                var items = results[k.key] || [];
                if (!items.length) return;
                html += '<div class="nav-search-group">' +
                    '<div class="nav-search-group-title">' +
                    '<i data-lucide="' + k.icon + '" class="w-3.5 h-3.5"></i>' +
                    '<span>' + k.label + '</span>' +
                    '<span class="nav-search-group-count">' + counts[k.key] + '</span>' +
                    '</div>' +
                    items.map(function (it) { return itemHtml(it, k.key); }).join('') +
                    '</div>';
            });
        } else {
            var its = results[active] || [];
            html += its.map(function (it) { return itemHtml(it, active); }).join('');
        }

        panel.innerHTML = html;
        panel.classList.add('is-visible');

        // 绑定 tab 点击
        panel.querySelectorAll('.nav-search-tab').forEach(function (b) {
            b.addEventListener('click', function () {
                state.currentTab = b.getAttribute('data-kind');
                renderResults(data);
                refreshIcons();
            });
        });
        refreshIcons();
    }

    function renderLoading() {
        panel.innerHTML = '<div class="nav-search-empty"><i data-lucide="loader-2" class="w-6 h-6 animate-spin mx-auto"></i></div>';
        panel.classList.add('is-visible');
        refreshIcons();
    }

    function renderEmpty() {
        panel.classList.remove('is-visible');
        panel.innerHTML = '';
    }

    // ---------- 搜索 ----------
    function doSearch(q) {
        q = (q || '').trim().slice(0, MAX_KEYWORD_LEN);
        if (!q) { renderEmpty(); scheduleClose(); return; }
        renderLoading();
        var seq = ++state.seq;
        fetch(API + '?q=' + encodeURIComponent(q), {
            headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (seq !== state.seq) return;       // 过期请求丢弃
            if (!d || !d.success) { renderEmpty(); return; }
            renderResults(d);
        })
        .catch(function () { if (seq === state.seq) renderEmpty(); });
    }

    // ---------- 初始化 ----------
    refreshClear();
})();
