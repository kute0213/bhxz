/* 我的音频页：复制播放链接 */
(function () {
    document.querySelectorAll('.copy-link-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var url = btn.getAttribute('data-url') || '';
            function done(ok) {
                if (typeof Toast !== 'undefined') {
                    if (ok) Toast.success('链接已复制'); else Toast.error('复制失败，请手动复制');
                }
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(url).then(function () { done(true); }, function () { done(false); });
            } else {
                var ta = document.createElement('textarea');
                ta.value = url;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                try { done(document.execCommand('copy')); } catch (_) { done(false); }
                document.body.removeChild(ta);
            }
        });
    });
})();
