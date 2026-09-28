// 滨海小镇 - 全站统一搜索组件（SiteSearch）
// 功能：点击搜索框平滑放大置顶（FLIP 位移动画，挂载到 body 避免受 .page-content
//       的 transform 影响）、输入时调用 API 搜索（无刷新）。
//
// 交互约定：
//   - 点击/聚焦搜索框 → 展开并置顶；输入为空时才显示遮罩
//   - 执行搜索（回车/提交）后保持展开，不自动收起
//   - 仅当搜索框内容被清空时才自动收起
//   - ESC / 点击遮罩（仅空态可见）可主动收起
//
// 用法：
//   SiteSearch.attach({
//       input: document.getElementById('xxx'),   // 搜索输入框
//       form:  formEl,                           // 可选：包含输入框的表单（提交即搜索）
//       endpoint: '/api/buildings',              // 搜索 API
//       params: function () { return { my: 1 }; },// 额外查询参数
//       onResults: function (data, query) {},    // 结果回调（data 为 JSON）
//       onLoading: function (query) {},
//       onError: function (err, query) {}
//   });
var SiteSearch = (function () {
    function debounce(fn, wait) {
        var timer = null;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, wait);
        };
    }

    function attach(options) {
        options = options || {};
        var input = options.input;
        if (!input) return null;

        var form = options.form || input.closest('form');
        var pinEl = options.pinEl || form || input.closest('.site-search-wrap') || input.parentElement;
        if (!pinEl) return null;
        pinEl.classList.add('site-search-wrap');

        var endpoint = options.endpoint || '';
        var paramsFn = options.params || function () { return {}; };
        var wait = options.debounce != null ? options.debounce : 260;
        var minLength = options.minLength != null ? options.minLength : 0;

        var pinned = false;
        var reqSeq = 0;

        // 置顶时的遮罩（挂载到 body，仅在输入为空时显示）
        var backdrop = document.createElement('div');
        backdrop.className = 'site-search-backdrop';
        document.body.appendChild(backdrop);

        // 清除按钮（输入框有内容时显示）
        var clearBtn = pinEl.querySelector('.site-search-clear');
        if (!clearBtn) {
            clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.className = 'site-search-clear';
            clearBtn.setAttribute('aria-label', '清除搜索');
            clearBtn.innerHTML = '<i data-lucide="x" class="w-3.5 h-3.5"></i>';
            (input.parentElement || pinEl).appendChild(clearBtn);
        }

        function refreshIcons() {
            if (typeof lucide !== 'undefined' && lucide.createIcons) {
                try { lucide.createIcons({ root: pinEl }); } catch (_) {}
            }
        }
        refreshIcons();

        function hasText() {
            return !!input.value.trim();
        }

        function updateHasValue() {
            pinEl.classList.toggle('has-value', hasText());
            // 遮罩仅在「置顶且输入为空」时显示，避免搜索结果被遮挡
            backdrop.classList.toggle('show', pinned && !hasText());
        }

        // 记录原始挂载位置，便于收起时还原
        var originParent = pinEl.parentNode;
        var originNext = pinEl.nextSibling;

        function clearPinnedStyles() {
            var s = pinEl.style;
            s.position = '';
            s.left = '';
            s.top = '';
            s.width = '';
            s.margin = '';
            s.zIndex = '';
        }

        function pin() {
            if (pinned) return;
            pinned = true;
            originParent = pinEl.parentNode;
            originNext = pinEl.nextSibling;

            // 记录展开前的几何位置，作为 FLIP 动画起点
            var rect = pinEl.getBoundingClientRect();
            document.body.appendChild(pinEl);

            // 起点：固定在原位置
            var s = pinEl.style;
            s.position = 'fixed';
            s.margin = '0';
            s.left = rect.left + 'px';
            s.top = rect.top + 'px';
            s.width = rect.width + 'px';
            s.zIndex = '1200';
            // 强制回流，确保起点几何生效后再过渡到终点
            void pinEl.offsetWidth;

            pinEl.classList.add('is-pinned');

            // 终点：视口顶部居中
            var targetWidth = Math.min(680, window.innerWidth - 28);
            s.left = Math.max(14, (window.innerWidth - targetWidth) / 2) + 'px';
            s.top = '14px';
            s.width = targetWidth + 'px';

            updateHasValue();
            refreshIcons();
            // 移动 DOM 可能丢失焦点，重新聚焦到输入框
            setTimeout(function () { try { input.focus({ preventScroll: true }); } catch (_) { input.focus(); } }, 0);
        }

        function unpin() {
            if (!pinned) return;
            pinned = false;
            var wasFocused = document.activeElement === input;
            backdrop.classList.remove('show');
            pinEl.classList.add('is-closing');
            setTimeout(function () {
                pinEl.classList.remove('is-pinned', 'is-closing');
                clearPinnedStyles();
                if (originParent) {
                    if (originNext && originNext.parentNode === originParent) {
                        originParent.insertBefore(pinEl, originNext);
                    } else {
                        originParent.appendChild(pinEl);
                    }
                }
                if (wasFocused) { try { input.blur(); } catch (_) {} }
                // 归位时由基础过渡负责淡入，避免生硬跳变
            }, 180);
        }

        // 执行搜索后：仅在输入为空时收起，有内容则保持展开
        function settleAfterSubmit() {
            if (!hasText()) unpin();
        }

        function runSearch(query) {
            if (!endpoint) return;
            query = (query || '').trim();
            if (minLength > 0 && query.length > 0 && query.length < minLength) return;

            var seq = ++reqSeq;
            if (options.onLoading) options.onLoading(query);

            var params = new URLSearchParams();
            params.set('q', query);
            var extra = paramsFn() || {};
            Object.keys(extra).forEach(function (k) {
                if (extra[k] != null && extra[k] !== '') params.set(k, extra[k]);
            });

            fetch(endpoint + '?' + params.toString(), {
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (seq !== reqSeq) return;
                if (options.onResults) options.onResults(data, query);
            })
            .catch(function (err) {
                if (seq !== reqSeq) return;
                if (options.onError) options.onError(err, query);
            });
        }

        var debouncedSearch = debounce(function () { runSearch(input.value); }, wait);

        input.addEventListener('focus', pin);
        input.addEventListener('click', function () {
            if (!pinned) pin();
        });
        input.addEventListener('input', function () {
            updateHasValue();
            // 清空内容后自动收起（唯一会自动收起的时机）
            if (pinned && !hasText()) { unpin(); return; }
            debouncedSearch();
        });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                runSearch(input.value);
                settleAfterSubmit();
                if (options.onSubmit) options.onSubmit(input.value);
            }
        });

        if (form) {
            form.addEventListener('submit', function (e) {
                e.preventDefault();
                e.stopPropagation();
                runSearch(input.value);
                settleAfterSubmit();
                if (options.onSubmit) options.onSubmit(input.value);
            });
        }

        backdrop.addEventListener('click', function () {
            unpin();
            try { input.blur(); } catch (_) {}
        });

        if (clearBtn) {
            clearBtn.addEventListener('mousedown', function (e) { e.preventDefault(); });
            clearBtn.addEventListener('click', function () {
                input.value = '';
                updateHasValue();
                runSearch('');
                if (pinned) { unpin(); }
                try { input.focus({ preventScroll: true }); } catch (_) { input.focus(); }
            });
        }

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && pinned) {
                unpin();
                try { input.blur(); } catch (_) {}
            }
        });

        updateHasValue();

        return {
            pin: pin,
            unpin: unpin,
            search: runSearch,
            refresh: function () { runSearch(input.value); },
            getQuery: function () { return input.value.trim(); }
        };
    }

    return { attach: attach };
})();
