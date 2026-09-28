// 滨海小镇 - 统一文件上传 / 无刷新发布组件
//
// 提供三个独立模块（全站共用，避免各页面重复造轮子）：
//   FilePicker    — 多文件选择 + 预览 + 删除，修复「清空 input.value 导致附件丢失」问题
//   UploadProgress— 基于 .progress-track / .progress-fill 的上传进度条
//   AjaxForm      — 拦截表单提交，XHR 上传（含进度）+ JSON 响应处理，无刷新
//
// 页面通过 data-file-picker 自动初始化文件选择器（见 macros/upload.html）。
// AjaxForm 需页面显式调用 AjaxForm.attach(form, options) 以绑定成功回调。

/* ------------------------------------------------------------------ */
/* FilePicker：多文件选择 + 预览 + 删除                                */
/* ------------------------------------------------------------------ */
var FilePicker = (function () {
    function formatSize(bytes) {
        bytes = Number(bytes) || 0;
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function attach(opts) {
        opts = opts || {};
        var input = opts.input;
        if (!input) return null;

        var list = opts.list;
        var button = opts.button;
        var maxCount = parseInt(opts.maxCount, 10) || 0;
        var maxBytes = parseInt(opts.maxBytes, 10) || 0;
        var files = [];
        var onChange = opts.onChange || function () {};

        function sync() {
            // 关键：先清空 value（允许重复选择同名文件），再把累计文件写回 input.files。
            // 若顺序相反，input.files 会被清空，导致提交时附件丢失。
            input.value = '';
            if (typeof DataTransfer !== 'undefined') {
                var dt = new DataTransfer();
                files.forEach(function (f) { dt.items.add(f); });
                input.files = dt.files;
            }
            render();
            onChange(files);
        }

        function render() {
            if (!list) return;
            if (files.length === 0) {
                list.innerHTML = '';
                return;
            }
            var html = '';
            files.forEach(function (f, idx) {
                html +=
                    '<div class="flex items-center justify-between px-3 py-2 rounded-lg bg-black/[0.03] border border-forest-700/40">' +
                    '  <div class="flex items-center gap-2 min-w-0">' +
                    '    <i data-lucide="file" class="w-3.5 h-3.5 text-cream/40 flex-shrink-0"></i>' +
                    '    <span class="text-xs text-cream/80 truncate">' + escapeHtml(f.name) + '</span>' +
                    '    <span class="text-xs text-cream/40 flex-shrink-0">(' + formatSize(f.size) + ')</span>' +
                    '  </div>' +
                    '  <button type="button" data-index="' + idx + '" class="file-picker-remove text-red-400/60 hover:text-red-400 transition-colors p-0.5 flex-shrink-0">' +
                    '    <i data-lucide="x" class="w-3.5 h-3.5"></i>' +
                    '  </button>' +
                    '</div>';
            });
            list.innerHTML = html;
            if (typeof lucide !== 'undefined' && lucide.createIcons) {
                try { lucide.createIcons({ root: list }); } catch (_) {}
            }
            list.querySelectorAll('.file-picker-remove').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    files.splice(parseInt(this.getAttribute('data-index'), 10), 1);
                    sync();
                });
            });
        }

        if (button) {
            button.addEventListener('click', function () { input.click(); });
        }
        input.addEventListener('change', function () {
            Array.prototype.forEach.call(input.files, function (f) {
                if (maxBytes && f.size > maxBytes) {
                    if (typeof Toast !== 'undefined') Toast.warning('文件「' + f.name + '」超过大小限制');
                    return;
                }
                if (maxCount && files.length >= maxCount) return;
                var dup = files.some(function (ef) { return ef.name === f.name && ef.size === f.size; });
                if (!dup) files.push(f);
            });
            sync();
        });

        return {
            getFiles: function () { return files.slice(); },
            hasFiles: function () { return files.length > 0; },
            clear: function () { files = []; sync(); }
        };
    }

    // 自动初始化 [data-file-picker]
    function initAll(root) {
        (root || document).querySelectorAll('[data-file-picker]:not([data-picker-ready])').forEach(function (wrap) {
            wrap.setAttribute('data-picker-ready', '1');
            var input = document.getElementById(wrap.getAttribute('data-input'));
            if (!input) return;
            wrap._picker = attach({
                input: input,
                list: document.getElementById(wrap.getAttribute('data-list')),
                button: document.getElementById(wrap.getAttribute('data-button')),
                maxCount: wrap.getAttribute('data-max-count'),
                maxBytes: wrap.getAttribute('data-max-bytes')
            });
        });
    }

    // 清空指定容器（或表单）内的所有文件选择器
    function clearWithin(root) {
        if (!root) return;
        root.querySelectorAll('[data-file-picker]').forEach(function (wrap) {
            if (wrap._picker) wrap._picker.clear();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initAll(document); });
    } else {
        initAll(document);
    }

    return { attach: attach, initAll: initAll, clearWithin: clearWithin, formatSize: formatSize };
})();

/* ------------------------------------------------------------------ */
/* UploadProgress：统一进度条（复用 .progress-track / .progress-fill） */
/* ------------------------------------------------------------------ */
var UploadProgress = (function () {
    function create(container) {
        if (!container) return null;
        container.classList.add('upload-progress');
        container.innerHTML =
            '<div class="progress-track md"><div class="progress-fill gold" style="width:0%"></div></div>' +
            '<div class="upload-progress-text"><span class="upload-progress-percent">0%</span>' +
            '<span class="upload-progress-status">上传中...</span></div>';
        var fill = container.querySelector('.progress-fill');
        var percentEl = container.querySelector('.upload-progress-percent');
        var statusEl = container.querySelector('.upload-progress-status');

        return {
            show: function () { container.style.display = ''; },
            hide: function () { container.style.display = 'none'; },
            reset: function () {
                fill.style.width = '0%';
                percentEl.textContent = '0%';
                statusEl.textContent = '上传中...';
            },
            set: function (pct) {
                pct = Math.max(0, Math.min(100, Math.round(pct)));
                fill.style.width = pct + '%';
                percentEl.textContent = pct + '%';
                if (pct >= 100) statusEl.textContent = '处理中...';
            },
            done: function (text) {
                fill.style.width = '100%';
                percentEl.textContent = '100%';
                statusEl.textContent = text || '完成';
            },
            fail: function (text) {
                fill.classList.remove('gold', 'blue', 'purple');
                fill.classList.add('red');
                statusEl.textContent = text || '上传失败';
            }
        };
    }
    return { create: create };
})();

/* ------------------------------------------------------------------ */
/* AjaxForm：无刷新表单提交（含上传进度 + JSON 响应）                  */
/* ------------------------------------------------------------------ */
var AjaxForm = (function () {
    function attach(form, options) {
        if (!form) return null;
        options = options || {};
        // 交给本组件处理，避免 base.js 的全局表单上传拦截重复提交
        form.setAttribute('data-upload-managed', 'true');

        var button = options.button || form.querySelector('[type="submit"]');
        var progress = options.progressContainer
            ? UploadProgress.create(options.progressContainer)
            : null;

        function setBusy(busy, text) {
            if (!button) return;
            button.disabled = busy;
            if (busy) {
                button.dataset.originalText = button.textContent;
                if (text) button.textContent = text;
            } else if (button.dataset.originalText) {
                button.textContent = button.dataset.originalText;
            }
        }

        function submit() {
            if (options.validate && options.validate() === false) return;

            var fd = new FormData(form);
            if (options.data) {
                Object.keys(options.data).forEach(function (k) {
                    fd.append(k, options.data[k]);
                });
            }

            var xhr = new XMLHttpRequest();
            xhr.open('POST', form.action || window.location.href, true);
            xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
            xhr.setRequestHeader('Accept', 'application/json');

            if (progress) {
                progress.show();
                progress.reset();
                xhr.upload.addEventListener('progress', function (e) {
                    if (e.lengthComputable) progress.set((e.loaded / e.total) * 100);
                });
            }
            setBusy(true, options.busyText || '提交中...');

            xhr.onload = function () {
                var data = {};
                try { data = JSON.parse(xhr.responseText); } catch (_) { data = {}; }
                var ok = xhr.status >= 200 && xhr.status < 400 && data.success !== false;

                if (ok) {
                    if (progress) {
                        progress.done('完成');
                        setTimeout(function () { progress.hide(); }, 900);
                    }
                    // 提交成功后清空文件选择器（预览 + input.files），避免残留
                    if (typeof FilePicker !== 'undefined' && FilePicker.clearWithin) {
                        FilePicker.clearWithin(form);
                    }
                    if (typeof Toast !== 'undefined' && data.message) Toast.success(data.message);
                    if (options.onSuccess) {
                        options.onSuccess(data, xhr);
                    } else if (data.redirect) {
                        window.location.href = data.redirect;
                        return;
                    } else {
                        window.location.reload();
                        return;
                    }
                } else {
                    if (progress) progress.fail(data.message || '提交失败');
                    if (typeof Toast !== 'undefined') Toast.error(data.message || '提交失败，请重试');
                    if (options.onError) options.onError(data, xhr);
                }
                setBusy(false);
            };

            xhr.onerror = function () {
                if (progress) progress.fail('网络异常');
                if (typeof Toast !== 'undefined') Toast.error('网络异常，提交失败');
                setBusy(false);
            };

            xhr.send(fd);
        }

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            e.stopPropagation();
            submit();
        }, true);

        return { submit: submit };
    }

    return { attach: attach };
})();
