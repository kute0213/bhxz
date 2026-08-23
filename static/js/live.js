/* ============================================================
 * live.js — 大喇叭实时直播台前端（多路并发）
 * 功能：多路直播卡片播放、主播麦克风推流（MediaRecorder 分片 →
 *       服务器 ffmpeg 实时 HLS）、开播/结束、状态轮询。
 * ============================================================ */
(function () {
    var root = document.getElementById('live-broadcast');
    if (!root) return;

    var statusUrl = root.getAttribute('data-status-url') || '/api/live/status';
    var pushUrl = root.getAttribute('data-push-url') || '/music/live/push';
    var isOwner = root.getAttribute('data-owner') === '1';
    var pushToken = root.getAttribute('data-token') || '';

    var recorder = null;
    var stream = null;

    function toast(ok, msg) {
        if (typeof Toast !== 'undefined') {
            if (ok) Toast.success(msg); else Toast.error(msg);
        }
    }

    function setStatus(text) {
        var el = document.querySelector('[data-broadcast-status]');
        if (el) el.textContent = text;
    }

    function pickMime() {
        if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return undefined;
        var cands = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/ogg'];
        for (var i = 0; i < cands.length; i++) {
            if (MediaRecorder.isTypeSupported(cands[i])) return cands[i];
        }
        return undefined;
    }

    function pushChunk(blob) {
        if (!pushToken) return;
        fetch(pushUrl, {
            method: 'POST',
            headers: { 'X-Push-Token': pushToken },
            body: blob
        }).catch(function () {});
    }

    function startRecorder(s) {
        stream = s;
        var mime = pickMime();
        try {
            recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
        } catch (e) {
            recorder = new MediaRecorder(stream);
        }
        recorder.ondataavailable = function (e) {
            if (e.data && e.data.size > 0) pushChunk(e.data);
        };
        // 每 2 秒产生一个分片推送到服务器，与 HLS 分片时长保持一致
        recorder.start(2000);
        setStatus('推流中… 说话即可被游戏内大喇叭实时播放');
    }

    function beginPush() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus('当前浏览器不支持麦克风推流');
            showRetry();
            return;
        }
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(startRecorder)
            .catch(function () {
                setStatus('麦克风权限被拒绝，点击「重试推流」或检查浏览器设置');
                showRetry();
            });
    }

    function showRetry() {
        var btn = document.querySelector('[data-live-retry]');
        if (btn) btn.classList.remove('hidden');
    }

    // 主播进入直播页（或开播成功后刷新）：自动开始推流
    if (isOwner && pushToken) {
        beginPush();
    }

    var retryBtn = document.querySelector('[data-live-retry]');
    if (retryBtn) {
        retryBtn.addEventListener('click', function () {
            retryBtn.classList.add('hidden');
            beginPush();
        });
    }

    // ---- 开播按钮：JS 直连（在用户手势中获取麦克风权限，成功后刷新页面）----
    var startForm = document.getElementById('live-start-form');
    if (startForm) {
        startForm.addEventListener('submit', function (e) {
            e.preventDefault();
            var input = startForm.querySelector('input[name="title"]');
            var title = (input && input.value || '').trim();
            if (!title) { toast(false, '请填写直播标题'); return; }

            var btn = document.getElementById('live-start-btn');
            if (btn) btn.disabled = true;

            // 1. 先在用户手势中请求麦克风权限（授权会持久化）
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                toast(false, '当前浏览器不支持麦克风推流');
                if (btn) btn.disabled = false;
                return;
            }
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(function (s) {
                    // 释放当前流，仅保留授权状态；刷新后由自动推流重新获取
                    s.getTracks().forEach(function (t) { t.stop(); });
                    return fetch(startForm.action, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                        body: JSON.stringify({ title: title })
                    });
                })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data.success) {
                        toast(false, data.message || '开播失败，请稍后再试');
                        if (btn) btn.disabled = false;
                        return;
                    }
                    // 2. 开播成功 → 刷新页面进入直播状态，页面加载时自动推流
                    location.reload();
                })
                .catch(function () {
                    toast(false, '麦克风权限被拒绝，无法开播');
                    if (btn) btn.disabled = false;
                });
        });
    }

    // ---- 结束直播：先停止本地推流，再提交表单结束服务端直播 ----
    var stopBtn = document.querySelector('[data-broadcast-status]') && document.querySelector('form[action*="live/stop"] button[type="submit"]');
    if (stopBtn) {
        stopBtn.addEventListener('click', function () {
            if (recorder && recorder.state !== 'inactive') {
                try { recorder.stop(); } catch (e) {}
            }
            if (stream) {
                stream.getTracks().forEach(function (t) { t.stop(); });
            }
            stream = null;
            recorder = null;
        });
    }

    // ---- 多路播放直播（浏览器限制自动播放，需用户点击）----
    var playBtns = document.querySelectorAll('[data-live-play]');
    playBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var card = btn.closest('.pixel-card');
            var audio = card && card.querySelector('[data-live-audio]');
            if (!audio) return;
            if (audio.paused) {
                // 先暂停其它卡片，避免多路同时出声
                document.querySelectorAll('[data-live-audio]').forEach(function (a) {
                    if (a !== audio && !a.paused) a.pause();
                });
                audio.play().catch(function () {
                    toast(false, '播放失败，请稍后重试');
                });
            } else {
                audio.pause();
            }
        });
    });

    // ---- 状态轮询：直播列表变化时刷新页面，保持页面与真实状态一致 ----
    var initialLive = root.getAttribute('data-owner') === '1' ? true : !!document.querySelector('[data-live-audio]');
    setInterval(function () {
        fetch(statusUrl, { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var hasLive = !!(data.broadcasts && data.broadcasts.length);
                if (hasLive !== initialLive) {
                    location.reload();
                }
            })
            .catch(function () {});
    }, 5000);
})();
