// 滨海小镇 · 页面内就地搜索（SiteSearch v8 · 单容器重写）
//
// 核心交互：
//   - 每个列表页独立的胶囊搜索框（.site-search），单容器承载两种形态：
//     折叠态只显示「搜索」按钮内容，展开态容器拉宽到 open_width、
//     显示真正的 <input> —— 过渡的是同一个容器的 max-width / padding /
//     border-radius / box-shadow，与导航栏 .glass-nav-inner 同款缓动。
//   - 展开触发：点击搜索框（容器任意位置）/ focus 输入框 / 预填关键词。
//   - 保持展开：输入框有文字 或 光标在其中。
//   - 收起：输入框空 + blur / 点击组件外部。
//   - 搜索事件：输入防抖 220ms / 回车，组件上派发
//     CustomEvent('site-search', {detail:{query}})，各列表页自己监听
//     就地刷新列表——不弹出下拉、不走聚合搜索。

(function () {
    'use strict';

    var MAX_LEN = 60;
    var DEBOUNCE = 220;
    var CLOSE_DELAY = 150;
    var FOCUS_DELAY = 140;   /* 等展开动画起步再 focus，避免抢焦点卡顿 */

    var roots = document.querySelectorAll('.site-search');
    if (!roots.length) return;

    var instances = [];

    Array.prototype.forEach.call(roots, init);

    function init(root) {
        var collapsed = root.querySelector('.ss-collapsed');
        var input = root.querySelector('.ss-input');
        var clearBtn = root.querySelector('.ss-clear');
        if (!collapsed || !input) return;

        var st = {
            expanded: false,
            focused: false,
            timerClose: null,
            timerSearch: null,
            last: null
        };
        instances.push({ root: root, state: st, input: input, collapse: collapse });

        function emit(q) {
            q = (q || '').trim().slice(0, MAX_LEN);
            if (q === st.last) return;
            st.last = q;
            root.dispatchEvent(new CustomEvent('site-search', {
                detail: { query: q },
                bubbles: true
            }));
        }

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
            if (!force && input.value.trim()) return;   /* 有值不收 */
            clearTimeout(st.timerClose);
            clearTimeout(st.timerSearch);
            st.expanded = false;
            root.classList.remove('is-open');
        }

        function scheduleClose() {
            clearTimeout(st.timerClose);
            st.timerClose = setTimeout(function () {
                if (!st.focused && !input.value.trim()) collapse(true);
            }, CLOSE_DELAY);
        }

        function refreshClear() {
            if (clearBtn) clearBtn.classList.toggle('visible', !!input.value.trim());
        }

        /* ---- 事件 ---- */
        /* 点击搜索框任意位置即展开（含折叠态的图标/文字及四周留白） */
        root.addEventListener('click', function () { expand(); });
        collapsed.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); expand(); }
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
            st.timerSearch = setTimeout(function () { emit(q); }, DEBOUNCE);
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

        if (clearBtn) clearBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            input.value = '';
            clearTimeout(st.timerSearch);
            refreshClear();
            emit('');
            input.focus();
        });

        /* ---- 初始化 ---- */
        refreshClear();
        var prefill = (root.getAttribute('data-search-value') || '').trim().slice(0, MAX_LEN);
        if (prefill) {
            input.value = prefill;
            st.last = prefill;
            refreshClear();
            st.expanded = true;
            root.classList.add('is-open');
        }
    }

    /* 点击组件外部：所有「空 + 失焦」的实例平滑收起 */
    document.addEventListener('mousedown', function (e) {
        instances.forEach(function (inst) {
            if (inst.root.contains(e.target)) return;
            if (!inst.state.focused && !inst.input.value.trim()) inst.collapse(true);
        });
    });
})();
