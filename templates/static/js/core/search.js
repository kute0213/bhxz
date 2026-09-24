// 滨海小镇 - 全站统一搜索组件（SiteSearch）
// 功能：点击搜索框放大置顶（挂载到 body，避免受 .page-content 的 transform 影响）、
//       输入时调用 API 搜索（无刷新）、ESC/点击遮罩收起。
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

        // 置顶时的遮罩（挂载到 body）
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
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons({ root: pinEl }); } catch (_) {}
        }

        function refreshIcons() {
            if (typeof lucide !== 'undefined' && lucide.createIcons) {
                try { lucide.createIcons({ root: pinEl }); } catch (_) {}
            }
        }

        function updateHasValue() {
            pinEl.classList.toggle('has-value', !!input.value.trim());
        }

        // 记录原始挂载位置，便于收起时还原
        var originParent = pinEl.parentNode;
        var originNext = pinEl.nextSibling;

        function pin() {
            if (pinned) return;
            pinned = true;
            originParent = pinEl.parentNode;
            originNext = pinEl.nextSibling;
            // 挂载到 body，确保 position:fixed 相对视口定位
            document.body.appendChild(pinEl);
            pinEl.classList.add('is-pinned');
            backdrop.classList.add('show');
            refreshIcons();
            // 移动 DOM 可能丢失焦点，重新聚焦到输入框
            setTimeout(function () { try { input.focus({ preventScroll: true }); } catch (_) { input.focus(); } }, 0);
        }

        function unpin() {
            if (!pinned) return;
            pinned = false;
            var wasFocused = document.activeElement === input;
            pinEl.classList.add('is-closing');
            backdrop.classList.remove('show');
            setTimeout(function () {
                pinEl.classList.remove('is-pinned', 'is-closing');
                if (originParent) {
                    if (originNext && originNext.parentNode === originParent) {
                        originParent.insertBefore(pinEl, originNext);
                    } else {
                        originParent.appendChild(pinEl);
                    }
                }
                if (wasFocused) { try { input.blur(); } catch (_) {} }
            }, 200);
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
            debouncedSearch();
        });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                runSearch(input.value);
                unpin();
                if (options.onSubmit) options.onSubmit(input.value);
            }
        });

        if (form) {
            form.addEventListener('submit', function (e) {
                e.preventDefault();
                e.stopPropagation();
                runSearch(input.value);
                unpin();
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
