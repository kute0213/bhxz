/* 我的音频页：复制播放链接 + 公开状态切换 / 删除（无刷新） */
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

    /* ---------- 无刷新操作（复用 base.js 的 .admin-action） ---------- */

    var list = document.getElementById('my-music-list');
    var empty = document.getElementById('my-music-empty');

    function refreshEmpty() {
        if (!list || !empty) return;
        var hasCard = !!list.querySelector('.music-card');
        list.classList.toggle('hidden', !hasCard);
        empty.classList.toggle('hidden', hasCard);
    }

    function badgeHtml(status) {
        if (status === 2) {
            return '<span class="inline-block px-2 py-0.5 rounded text-xs font-bold bg-green-500/20 text-green-300 border border-green-500/30">已公开</span>';
        }
        if (status === 1) {
            return '<span class="inline-block px-2 py-0.5 rounded text-xs font-bold bg-yellow-500/20 text-yellow-300 border border-yellow-500/30">待审核</span>';
        }
        return '<span class="inline-block px-2 py-0.5 rounded text-xs font-bold bg-cream/10 text-cream/60 border border-cream/20">私有</span>';
    }

    function updateToggleBtn(card, status) {
        var btn = card && card.querySelector('.music-toggle-btn');
        if (!btn) return;
        var isPrivate = status === 0;
        btn.setAttribute('data-status', String(status));
        btn.className = 'music-toggle-btn admin-action px-3 py-2 rounded-lg text-xs border transition-colors flex items-center gap-1.5 ' +
            (isPrivate ? 'border-green-500/30 text-green-300 hover:bg-green-500/10'
                       : 'border-yellow-500/30 text-yellow-300 hover:bg-yellow-500/10');
        btn.title = isPrivate ? '申请公开（需审核）' : '转为私有';
        btn.innerHTML = '<i data-lucide="' + (isPrivate ? 'eye' : 'eye-off') + '" class="w-3.5 h-3.5"></i>' +
            '<span>' + (isPrivate ? '申请公开' : '转为私有') + '</span>';
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons({ root: btn }); } catch (_) {}
        }
    }

    function updateWaitingHint(card, status) {
        var hint = card && card.querySelector('[data-music-waiting]');
        if (hint) hint.classList.toggle('hidden', status !== 1);
    }

    document.addEventListener('admin:action', function (e) {
        var detail = e.detail || {};
        var el = detail.el;
        var data = detail.data || {};
        if (!el) return;

        if (el.classList.contains('music-toggle-btn')) {
            var card = el.closest('.music-card');
            var status = data.status;
            if (card && typeof status === 'number') {
                var slot = card.querySelector('[data-music-status]');
                if (slot) {
                    slot.setAttribute('data-music-status', String(status));
                    slot.innerHTML = badgeHtml(status);
                }
                updateWaitingHint(card, status);
                updateToggleBtn(card, status);
            }
            return;
        }

        if (el.classList.contains('music-delete-btn')) {
            /* .admin-action 会在 250ms 后移除卡片，稍后再判断列表是否为空 */
            setTimeout(refreshEmpty, 320);
        }
    });
})();
