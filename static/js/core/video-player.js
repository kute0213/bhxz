// 站内统一视频播放器
// —— 把页面中的 <video> 换成与站点风格一致的自定义控件：
//    大播放按钮、播放/暂停、进度条、时间、静音、全屏。
//    原生 controls 会被移除，所有视觉与交互均由本项目实现。
// 用法：
//     SiteVideoPlayer.decorate(video)   // 装饰单个视频，返回包裹容器
//     SiteVideoPlayer.decorateAll(root) // 装饰 root 内所有视频
//     DOMContentLoaded 时会自动全站执行一次。
(function () {
    'use strict';

    var ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
    var ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.4v14H7zM13.6 5H17v14h-3.4z"/></svg>';
    var ICON_VOLUME = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h3l4-3.5v13L7 15H4zM15.5 8.5a5 5 0 0 1 0 7M18 6a8.5 8.5 0 0 1 0 12"/></svg>';
    var ICON_MUTE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h3l4-3.5v13L7 15H4zM15.5 9.5l5 5m0-5l-5 5"/></svg>';
    var ICON_FULL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10V5h5M19 10V5h-5M5 14v5h5M19 14v5h-5"/></svg>';
    // 播放速度循环：1x → 1.25x → 1.5x → 2x → 0.5x
    var SPEEDS = [1, 1.25, 1.5, 2, 0.5];

    function rateLabel(rate) {
        var value = Number(rate);
        if (!isFinite(value)) value = 1;
        return (Math.round(value * 100) / 100).toString() + 'x';
    }

    function fmt(sec) {
        if (!isFinite(sec) || sec <= 0) return '0:00';
        var s = Math.floor(sec);
        var m = Math.floor(s / 60);
        var r = s % 60;
        if (m >= 60) {
            var h = Math.floor(m / 60);
            m = m % 60;
            return h + ':' + (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
        }
        return m + ':' + (r < 10 ? '0' : '') + r;
    }

    function makeButton(cls, label) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'svp-btn ' + cls;
        b.setAttribute('aria-label', label);
        b.title = label;
        return b;
    }

    function decorate(video) {
        if (!video || video.__svpReady || video.dataset.svpSkip) return null;
        video.__svpReady = true;

        // 移除原生控件，统一使用站内控件
        video.removeAttribute('controls');
        video.controls = false;
        video.setAttribute('playsinline', '');

        var wrap = document.createElement('div');
        wrap.className = 'svp';
        wrap.setAttribute('contenteditable', 'false');
        wrap.dataset.svp = '1';

        var parent = video.parentNode;
        if (parent) parent.insertBefore(wrap, video);
        wrap.appendChild(video);

        // 伪文件名（来自指南 config.json）：显示在视频左上角
        var captionText = video.getAttribute('data-title') || video.dataset.title || '';
        if (captionText) {
            var caption = document.createElement('div');
            caption.className = 'svp-caption';
            caption.textContent = captionText;
            wrap.appendChild(caption);
        }

        // 中央大播放按钮
        var overlay = document.createElement('button');
        overlay.type = 'button';
        overlay.className = 'svp-overlay';
        overlay.setAttribute('aria-label', '播放');
        overlay.innerHTML = ICON_PLAY;
        wrap.appendChild(overlay);

        // 底部控制栏
        var bar = document.createElement('div');
        bar.className = 'svp-bar';

        var toggle = makeButton('svp-toggle', '播放');
        toggle.innerHTML = ICON_PLAY;
        bar.appendChild(toggle);

        var seek = document.createElement('input');
        seek.type = 'range';
        seek.className = 'svp-seek';
        seek.min = '0';
        seek.max = '1000';
        seek.step = '1';
        seek.value = '0';
        seek.setAttribute('aria-label', '播放进度');
        bar.appendChild(seek);

        var time = document.createElement('span');
        time.className = 'svp-time';
        time.textContent = '0:00 / 0:00';
        bar.appendChild(time);

        var mute = makeButton('svp-mute', '静音');
        mute.innerHTML = ICON_VOLUME;
        bar.appendChild(mute);

        var speed = makeButton('svp-speed', '播放速度 1x');
        speed.textContent = '1x';
        bar.appendChild(speed);

        var full = makeButton('svp-full', '全屏');
        full.innerHTML = ICON_FULL;
        bar.appendChild(full);

        wrap.appendChild(bar);

        var dragging = false;

        function duration() {
            return (isFinite(video.duration) && video.duration > 0) ? video.duration : 0;
        }

        function updateTime() {
            var dur = duration();
            var cur = video.currentTime || 0;
            if (!dragging && dur) seek.value = String(Math.round(cur / dur * 1000));
            time.textContent = fmt(cur) + ' / ' + fmt(dur);
        }

        function updateState() {
            var paused = video.paused;
            toggle.innerHTML = paused ? ICON_PLAY : ICON_PAUSE;
            toggle.setAttribute('aria-label', paused ? '播放' : '暂停');
            toggle.title = paused ? '播放' : '暂停';
            overlay.classList.toggle('is-hidden', !paused);
            wrap.classList.toggle('is-playing', !paused);
        }

        function play() {
            var p = video.play();
            if (p && typeof p.catch === 'function') p.catch(function () { /* 忽略自动播放限制 */ });
        }

        function togglePlay() {
            if (video.paused) play(); else video.pause();
        }

        overlay.addEventListener('click', togglePlay);
        toggle.addEventListener('click', togglePlay);
        video.addEventListener('click', togglePlay);

        seek.addEventListener('pointerdown', function () { dragging = true; });
        seek.addEventListener('input', function () {
            var dur = duration();
            if (dur) video.currentTime = (Number(seek.value) || 0) / 1000 * dur;
            updateTime();
        });
        var stopDrag = function () { dragging = false; updateTime(); };
        seek.addEventListener('pointerup', stopDrag);
        seek.addEventListener('pointercancel', stopDrag);
        seek.addEventListener('change', stopDrag);

        mute.addEventListener('click', function () {
            video.muted = !video.muted;
        });
        video.addEventListener('volumechange', function () {
            mute.innerHTML = video.muted || video.volume === 0 ? ICON_MUTE : ICON_VOLUME;
            mute.setAttribute('aria-label', video.muted ? '取消静音' : '静音');
            mute.title = video.muted ? '取消静音' : '静音';
        });

        full.addEventListener('click', function () {
            if (document.fullscreenElement) {
                document.exitFullscreen && document.exitFullscreen();
            } else if (wrap.requestFullscreen) {
                wrap.requestFullscreen();
            } else if (video.webkitEnterFullscreen) {
                video.webkitEnterFullscreen();
            }
        });

        // 倍速按钮：每次点击切换到下一个速度，并在按钮上显示当前倍速
        var speedIndex = 0;
        function applySpeed(rate) {
            video.playbackRate = rate;
            speed.textContent = rateLabel(rate);
            speed.title = '播放速度 ' + rateLabel(rate);
            speed.setAttribute('aria-label', '播放速度 ' + rateLabel(rate));
        }
        speed.addEventListener('click', function () {
            speedIndex = (speedIndex + 1) % SPEEDS.length;
            applySpeed(SPEEDS[speedIndex]);
        });
        video.addEventListener('ratechange', function () {
            var rate = Number(video.playbackRate) || 1;
            var idx = SPEEDS.indexOf(rate);
            if (idx >= 0) speedIndex = idx;
            speed.textContent = rateLabel(rate);
            speed.title = '播放速度 ' + rateLabel(rate);
        });

        video.addEventListener('loadedmetadata', function () {
            updateTime();
            updateState();
        });
        video.addEventListener('durationchange', updateTime);
        video.addEventListener('timeupdate', updateTime);
        video.addEventListener('play', updateState);
        video.addEventListener('pause', updateState);
        video.addEventListener('ended', function () {
            updateState();
            updateTime();
        });

        updateState();
        updateTime();
        return wrap;
    }

    function decorateAll(root) {
        if (!root || !root.querySelectorAll) return;
        var videos = root.querySelectorAll('video');
        for (var i = 0; i < videos.length; i++) decorate(videos[i]);
    }

    window.SiteVideoPlayer = { decorate: decorate, decorateAll: decorateAll };

    function boot() { decorateAll(document); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
