// 统一 Markdown 编辑器：自动初始化页面中所有 .markdown-editor 组件。
// 功能：工具栏插入、实时预览、字数统计、编辑/预览同步滚动。
// 依赖：static/lib/marked/marked.min.js
(function () {
    'use strict';

    function insertText(ta, before, after) {
        var start = ta.selectionStart;
        var end = ta.selectionEnd;
        var text = ta.value;
        var selected = text.substring(start, end);
        ta.value = text.substring(0, start) + before + selected + after + text.substring(end);
        ta.selectionStart = start + before.length;
        ta.selectionEnd = start + before.length + selected.length;
        ta.focus();
    }

    function initEditor(root) {
        var textarea = root.querySelector('textarea');
        var preview = root.querySelector('[data-md-preview]');
        if (!textarea || !preview) return;
        var count = root.querySelector('[data-md-count]');

        function updatePreview() {
            if (count) count.textContent = (textarea.value || '').length + ' 字';
            if (window.marked) {
                preview.innerHTML = DOMPurify.sanitize(marked.parse(textarea.value || ''));
            }
        }

        // 工具栏按钮
        root.querySelectorAll('[data-md-before]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                insertText(textarea, btn.getAttribute('data-md-before') || '', btn.getAttribute('data-md-after') || '');
                updatePreview();
            });
        });

        textarea.addEventListener('input', updatePreview);
        updatePreview();

        // 编辑/预览同步滚动
        var syncing = false;
        function syncScroll(src, dst) {
            if (syncing) return;
            syncing = true;
            var ratio = src.scrollTop / (src.scrollHeight - src.clientHeight);
            dst.scrollTop = ratio * (dst.scrollHeight - dst.clientHeight);
            syncing = false;
        }
        textarea.addEventListener('scroll', function () { syncScroll(textarea, preview); });
        preview.addEventListener('scroll', function () { syncScroll(preview, textarea); });
    }

    function initAll() {
        document.querySelectorAll('.markdown-editor').forEach(initEditor);
    }

    // DOM 内容变化时自动初始化动态加载的编辑器
    var observer = null;
    function startObserver() {
        if (observer) return;
        observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1 && node.querySelector && node.querySelector('.markdown-editor')) {
                        initAll();
                    }
                });
            });
        });
        if (document.body) observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initAll(); startObserver(); });
    } else {
        initAll(); startObserver();
    }
})();