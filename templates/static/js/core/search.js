// 滨海小镇 - 页面内就地搜索（SiteSearch v7 · 就地过滤列表）
//
// 交互约定：
//   - 每个页面的搜索框（.site-search，由 macros/search.html 的 inline_search 渲染）
//     都是独立的就地展开/收起组件；导航栏不放置搜索框。
//   - 折叠态：只显示「搜索」胶囊按钮；点击后按钮收起、输入框平滑展开（双向动画）。
//   - 输入框内有文字 或 光标在输入框内 → 保持展开；
//     无文字 且 失焦（点击外部）→ 平滑收起。
//   - 输入防抖 / 回车 / 点击箭头 / 清空 → 在组件上派发 `site-search` 事件，
//     detail.query 为当前关键词；由各页面自己的列表脚本监听，
//     直接把结果渲染到当前列表，不再弹出下拉窗口（不使用聚合搜索接口）。

(function () {
    'use strict';

    // ---------- 常量 ----------
    var MAX_KEYWORD_LEN = 60;
    var DEBOUNCE_MS = 220;   // 输入防抖
    var CLOSE_MS = 150;      // 失焦后延迟收起（ms）
    var FOCUS_DELAY = 140;   // 展开动画起步后再聚焦，避免抢焦点导致动画卡顿

    var roots = document.querySelectorAll('.site-search');
    if (!roots.length) return;

    // 所有实例，供全局「点击外部收起」统一处理
    var instances = [];

    Array.prototype.forEach.call(roots, init);

    function init(root) {
        var trigger = root.querySelector('.site-search-trigger');
        var input = root.querySelector('.site-search-input');
        var clearBtn = root.querySelector('.site-search-clear');
        var submitBtn = root.querySelector('.site-search-submit');
        if (!trigger || !input) return;

        var st = {
            expanded: false,
            focused: false,
            timerClose: null,
            timerSearch: null,
            last: null            // 上次派发的关键词，避免重复触发列表刷新
        };

        instances.push({ root: root, state: st, input: input, collapse: collapse });

        // ---------- 派发搜索事件（各页面列表脚本监听） ----------
        function emit(q) {
            q = (q || '').trim().slice(0, MAX_KEYWORD_LEN);
            if (q === st.last) return;
            st.last = q;
            root.dispatchEvent(new CustomEvent('site-search', {
                detail: { query: q },
                bubbles: true
            }));
        }

        // ---------- 展开 / 收起 ----------
        function expand() {
            clearTimeout(st.timerClose);
            if (!st.expanded) {
                st.expanded = true;
                root.classList.add('is-open');
            }
            setTimeout(function () {
                try { input.focus(); } catch (_) {}
            }, FOCUS_DELAY);
        }

        function collapse(force) {
            if (!st.expanded) return;
            // 未强制时，只要输入框还有文字就保持展开
            if (!force && input.value.trim()) return;
            clearTimeout(st.timerClose);
            clearTimeout(st.timerSearch);
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
            if (clearBtn) clearBtn.classList.toggle('visible', !!input.value.trim());
        }

        // ---------- 事件绑定 ----------
        // 点击整个组件（胶囊按钮 / 输入框区域）→ 展开
        root.addEventListener('click', function () {
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
            st.timerSearch = setTimeout(function () { emit(q); }, DEBOUNCE_MS);
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                clearTimeout(st.timerSearch);
                emit(input.value.trim());
            } else if (e.key === 'Escape') {
                e.preventDefault();
                input.value = '';
                refreshClear();
                emit('');
                input.blur();
                collapse(true);
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                input.value = '';
                clearTimeout(st.timerSearch);
                refreshClear();
                emit('');
                input.focus();
            });
        }

        if (submitBtn) {
            submitBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                var q = input.value.trim();
                if (q) {
                    clearTimeout(st.timerSearch);
                    emit(q);
                }
            });
        }

        // ---------- 初始化 ----------
        refreshClear();
        var prefill = (root.getAttribute('data-search-value') || '').trim().slice(0, MAX_KEYWORD_LEN);
        if (prefill) {
            input.value = prefill;
            st.last = prefill;      // 首屏已由服务端按该关键词渲染，避免重复请求
            refreshClear();
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
