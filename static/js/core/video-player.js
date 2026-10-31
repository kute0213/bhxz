// 站内统一视频播放器
// —— 把页面中的 <video> 换成与站点风格一致的自定义控件：
//    淡蓝色磨砂玻璃按钮、透明控制栏、中央播放按钮、拖动进度、音量上拉框、
//    倍速上拉框、全屏。原生 controls 会被移除，所有视觉与交互均由本项目实现。
// 用法：
//     SiteVideoPlayer.decorate(video)      // 装饰单个视频，返回包裹容器
//     SiteVideoPlayer.decorateAll(root)    // 装饰 root 内所有视频
//     SiteVideoPlayer.setTitle(video, txt) // 更新视频左上角伪文件名
//     DOMContentLoaded 时会自动全站执行一次。
(function () {
    'use strict';

    var ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
    var ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.4v14H7zM13.6 5H17v14h-3.4z"/></svg>';
    var ICON_VOLUME = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h3l4-3.5v13L7 15H4zM15.5 8.5a5 5 0 0 1 0 7M18 6a8.5 8.5 0 0 1 0 12"/></svg>';
    var ICON_MUTE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h3l4-3.5v13L7 15H4zM15.5 9.5l5 5m0-5l-5 5"/></svg>';
    var ICON_FULL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10V5h5M19 10V5h-5M5 14v5h5M19 14v5h-5"/></svg>';
    // 倍速可选值（上拉框按升序展示）
    var SPEEDS = [0.5, 1, 1.25, 1.5, 2];

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

    function makePopover(cls) {
        var pop = document.createElement('div');
        pop.className = 'svp-pop ' + cls;
        pop.hidden = true;
        return pop;
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
        var caption = document.createElement('div');
        caption.className = 'svp-caption';
        caption.hidden = true;
        wrap.appendChild(caption);

        function setCaption(text) {
            var value = String(text || '').trim();
            caption.textContent = value;
            caption.hidden = !value;
            if (value) video.setAttribute('data-title', value);
            else video.removeAttribute('data-title');
        }
        setCaption(video.getAttribute('data-title') || video.dataset.title || '');
        video.__svpSetTitle = setCaption;

        // 中央播放按钮（不覆盖整块视频，暂停时不会给画面蒙上淡蓝色）
        var overlay = document.createElement('button');
        overlay.type = 'button';
        overlay.className = 'svp-overlay';
        overlay.setAttribute('aria-label', '播放');
        overlay.innerHTML = ICON_PLAY;
        wrap.appendChild(overlay);

        // 底部控制栏（背景透明，按钮本身为淡蓝磨砂玻璃）
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

        // 音量：按钮 + 上拉框（静音开关 + 音量滑块）
        var volPop = makePopover('svp-pop-volume');
        var popMute = makeButton('svp-pop-mute', '静音');
        popMute.innerHTML = ICON_VOLUME;
        var volRange = document.createElement('input');
        volRange.type = 'range';
        volRange.className = 'svp-vol';
        volRange.min = '0';
        volRange.max = '100';
        volRange.step = '1';
        volRange.value = '100';
        volRange.setAttribute('aria-label', '音量');
        volPop.appendChild(popMute);
        volPop.appendChild(volRange);

        var mute = makeButton('svp-mute', '音量调节');
        mute.innerHTML = ICON_VOLUME;
        var volumeGroup = document.createElement('div');
        volumeGroup.className = 'svp-group svp-group-volume';
        volumeGroup.appendChild(mute);
        volumeGroup.appendChild(volPop);
        bar.appendChild(volumeGroup);

        // 倍速：按钮 + 上拉框（速度列表）
        var speedPop = makePopover('svp-pop-speed');
        var speedTitle = document.createElement('div');
        speedTitle.className = 'svp-pop-title';
        speedTitle.textContent = '播放速度';
        speedPop.appendChild(speedTitle);

        var speedList = document.createElement('div');
        speedList.className = 'svp-speed-list';
        var speedOptions = [];
        for (var si = 0; si < SPEEDS.length; si++) {
            (function (rate) {
                var opt = document.createElement('button');
                opt.type = 'button';
                opt.className = 'svp-speed-opt';
                opt.dataset.rate = String(rate);
                opt.textContent = rateLabel(rate);
                opt.addEventListener('click', function (e) {
                    e.stopPropagation();
                    applySpeed(rate);
                });
                speedList.appendChild(opt);
                speedOptions.push(opt);
            })(SPEEDS[si]);
        }
        speedPop.appendChild(speedList);

        var speed = makeButton('svp-speed', '播放速度 1x');
        speed.textContent = '1x';
        var speedGroup = document.createElement('div');
        speedGroup.className = 'svp-group svp-group-speed';
        speedGroup.appendChild(speed);
        speedGroup.appendChild(speedPop);
        bar.appendChild(speedGroup);

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
            if (!paused) closePops();
        }

        function play() {
            var p = video.play();
            if (p && typeof p.catch === 'function') p.catch(function () { /* 忽略自动播放限制 */ });
        }

        function togglePlay() {
            if (video.paused) play(); else video.pause();
        }

        /* ---------- 上拉框开关 ---------- */

        function closePops() {
            volPop.hidden = true;
            speedPop.hidden = true;
            volumeGroup.classList.remove('is-open');
            speedGroup.classList.remove('is-open');
        }

        function togglePop(pop, group) {
            var willOpen = pop.hidden;
            closePops();
            if (!willOpen) return;

            pop.hidden = false;
            group.classList.add('is-open');

            // 上方空间不足（例如编辑器滚动容器顶部）时改为向下展开，避免被裁掉
            pop.classList.remove('is-below');
            var rect = group.getBoundingClientRect();
            var height = pop.offsetHeight;
            var containerTop = 0;
            var node = group.parentNode;
            while (node && node !== document.body) {
                var style = window.getComputedStyle(node);
                if (style && /(auto|scroll|hidden)/.test(style.overflowY)) {
                    containerTop = node.getBoundingClientRect().top;
                    break;
                }
                node = node.parentNode;
            }
            if (rect.top - height - 12 < containerTop) pop.classList.add('is-below');
        }

        // 点击播放器其它区域 / 播放器外部时收起上拉框，避免误触
        document.addEventListener('click', function (e) {
            var target = e.target;
            if (!wrap.contains(target)) { closePops(); return; }
            if (!(target.closest && (target.closest('.svp-group') || target.closest('.svp-pop')))) closePops();
        }, true);

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

        // 音量
        function syncVolume() {
            var muted = video.muted || video.volume === 0;
            var ratio = muted ? 0 : video.volume;
            volRange.value = String(Math.round((isFinite(ratio) ? ratio : 1) * 100));
            var icon = muted ? ICON_MUTE : ICON_VOLUME;
            mute.innerHTML = icon;
            popMute.innerHTML = icon;
            mute.setAttribute('aria-label', '音量调节');
            mute.title = '音量调节';
            popMute.setAttribute('aria-label', muted ? '取消静音' : '静音');
            popMute.title = muted ? '取消静音' : '静音';
        }

        mute.addEventListener('click', function (e) {
            e.stopPropagation();
            togglePop(volPop, volumeGroup);
        });

        volRange.addEventListener('input', function () {
            var value = Number(volRange.value) / 100;
            video.muted = value === 0;
            video.volume = value;
            syncVolume();
        });

        popMute.addEventListener('click', function (e) {
            e.stopPropagation();
            if (video.muted || video.volume === 0) {
                video.muted = false;
                if (video.volume === 0) video.volume = 0.5;
            } else {
                video.muted = true;
            }
            syncVolume();
        });

        video.addEventListener('volumechange', syncVolume);

        // 倍速
        function syncSpeedOptions(rate) {
            for (var i = 0; i < speedOptions.length; i++) {
                speedOptions[i].classList.toggle('is-active', Number(speedOptions[i].dataset.rate) === Number(rate));
            }
        }

        function applySpeed(rate) {
            video.playbackRate = rate;
            speed.textContent = rateLabel(rate);
            speed.title = '播放速度 ' + rateLabel(rate);
            speed.setAttribute('aria-label', '播放速度 ' + rateLabel(rate));
            syncSpeedOptions(rate);
            closePops();
        }

        speed.addEventListener('click', function (e) {
            e.stopPropagation();
            togglePop(speedPop, speedGroup);
        });

        video.addEventListener('ratechange', function () {
            var rate = Number(video.playbackRate) || 1;
            speed.textContent = rateLabel(rate);
            speed.title = '播放速度 ' + rateLabel(rate);
            speed.setAttribute('aria-label', '播放速度 ' + rateLabel(rate));
            syncSpeedOptions(rate);
        });

        // 全屏
        full.addEventListener('click', function () {
            closePops();
            if (document.fullscreenElement) {
                document.exitFullscreen && document.exitFullscreen();
            } else if (wrap.requestFullscreen) {
                wrap.requestFullscreen();
            } else if (video.webkitEnterFullscreen) {
                video.webkitEnterFullscreen();
            }
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
        syncVolume();
        syncSpeedOptions(Number(video.playbackRate) || 1);
        return wrap;
    }

    function decorateAll(root) {
        if (!root || !root.querySelectorAll) return;
        var videos = root.querySelectorAll('video');
        for (var i = 0; i < videos.length; i++) decorate(videos[i]);
    }

    // 更新视频伪文件名（重新装饰前也能直接更新，见编辑器「改名」）
    function setTitle(video, text) {
        if (!video) return;
        if (typeof video.__svpSetTitle === 'function') {
            video.__svpSetTitle(text || '');
            return;
        }
        var value = String(text || '').trim();
        if (value) video.setAttribute('data-title', value);
        else video.removeAttribute('data-title');
    }

    window.SiteVideoPlayer = { decorate: decorate, decorateAll: decorateAll, setTitle: setTitle };

    function boot() { decorateAll(document); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
