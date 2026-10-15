/* 大喇叭自定义音频播放器（磨砂玻璃风格）。
 *
 * 页面中每个 .music-player 元素（由 macros/music_macros.html 的
 * music_audio_player 宏渲染）都会初始化为一个独立播放器，支持：
 *   - 播放/暂停（同一时间只允许一个播放器出声）
 *   - 进度条：点击/拖动 seek，展示已缓冲范围
 *   - 倍速：0.5x ~ 2.0x
 *   - 音量：按钮静音/取消静音，滑块调节（音量记忆在 localStorage）
 *   - HLS 播放：优先使用本地 hls.js，不支持时回退原生播放
 *     · 点击播放才开始加载（页面加载不预取分片），避免列表页请求风暴
 *     · 网络类致命错误自动退避重试，瞬时 404 可自愈，不会永久锁死播放
 *
 * 依赖：hls.js（static/lib/hls/hls.min.js，可选）、Lucide（可选）
 */
(function () {
    'use strict';

    var RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
    var VOLUME_KEY = 'bhxz:mp:volume';
    var RETRY_MAX = 3;              // 网络类致命错误的最大自动重试次数
    var players = [];

    function $(root, sel) { return root.querySelector(sel); }

    function formatTime(sec) {
        if (!isFinite(sec) || sec < 0) sec = 0;
        sec = Math.floor(sec);
        var h = Math.floor(sec / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var s = sec % 60;
        if (h > 0) {
            return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        }
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function pauseAll(except) {
        players.forEach(function (p) {
            if (p !== except) p.pause(true);
        });
    }

    function MusicPlayer(root) {
        this.root = root;
        this.src = root.getAttribute('data-src') || '';
        this.audio = new Audio();
        this.audio.preload = 'none';
        this.audio.crossOrigin = 'anonymous';

        this.el = {
            play: $(root, '.mp-play'),
            progress: $(root, '.mp-progress'),
            fill: $(root, '.mp-fill'),
            buffered: $(root, '.mp-buffered'),
            thumb: $(root, '.mp-thumb'),
            current: $(root, '.mp-current'),
            duration: $(root, '.mp-duration'),
            speedBtn: $(root, '.mp-speed-btn'),
            speedMenu: $(root, '.mp-speed-menu'),
            speedWrap: $(root, '.mp-speed'),
            volBtn: $(root, '.mp-vol-btn'),
            volSlider: $(root, '.mp-vol-slider'),
            volWrap: $(root, '.mp-volume'),
        };

        this.hls = null;
        this.dragging = false;
        this.retries = 0;             // 网络类致命错误的已重试次数
        this.pendingPlay = false;     // 已点击播放、正在等待清单就绪
        this.manifestReady = false;   // HLS 清单是否已成功解析
        this.lastFatal = null;        // 最近一次致命错误，用于恢复时决定是否重载清单
        this.setup();
    }

    /* 初始化 hls.js。
     * autoStartLoad=false：页面加载时不预取任何分片，只有用户点击播放才开始加载，
     * 避免列表页一次性发起大量分片请求（网络抖动时会成片报 404）。
     * 同时监听致命错误：网络类错误自动退避重试，瞬时 404 可自愈，
     * 不再一次失败就永久置为错误态、导致该音频始终无法播放。 */
    MusicPlayer.prototype.initHls = function () {
        var self = this;
        self.hls = new window.Hls({
            lowLatencyMode: false,
            autoStartLoad: false,
            manifestLoadingMaxRetry: 4,
            levelLoadingMaxRetry: 4,
            fragLoadingMaxRetry: 6,
        });
        // 清单解析完成：拿到总时长；若用户已点击播放则正式开始播放
        self.hls.on(window.Hls.Events.MANIFEST_PARSED, function () {
            self.manifestReady = true;
            self.lastFatal = null;
            self.retries = 0;
            if (!self.pendingPlay) return;
            self.pendingPlay = false;
            self.el.play.classList.remove('is-loading');
            var p = self.audio.play();
            if (p && p.catch) p.catch(function () { self.showError(); });
        });
        // 清单加载完成即可拿到总时长，无需等用户点击播放
        self.hls.on(window.Hls.Events.LEVEL_LOADED, function (_e, data) {
            var total = data && data.details && data.details.totalduration;
            if (total && isFinite(total) && self.el.duration) {
                self.el.duration.textContent = formatTime(total);
            }
        });
        self.hls.on(window.Hls.Events.ERROR, function (_e, data) {
            if (!data || !data.fatal) return;
            if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR) {
                try { self.hls.recoverMediaError(); } catch (_) {}
                return;
            }
            self.retryNetwork(data.details);
        });
        self.hls.loadSource(self.src);
        self.hls.attachMedia(self.audio);
    };

    /* 网络类致命错误：退避重试，超过 RETRY_MAX 次才置为错误态。
     * 瞬时 404 / 连接抖动可自愈，不再一次失败就永久失效。 */
    MusicPlayer.prototype.retryNetwork = function (details) {
        var self = this;
        self.lastFatal = details;
        if (self.retries >= RETRY_MAX) { self.showError(); return; }
        self.retries++;
        var delay = 700 * self.retries;
        setTimeout(function () {
            if (!self.hls) return;
            try {
                // 清单本身加载失败时需重新 loadSource，分片失败只需继续加载
                if (details === 'manifestLoadError') self.hls.loadSource(self.src);
                self.hls.startLoad();
            } catch (_) {}
        }, delay);
    };

    /* 开始播放：清除此前的错误态并重新加载（瞬时失败可自愈）。 */
    MusicPlayer.prototype.startPlayback = function () {
        var self = this;
        self.root.classList.remove('is-error');
        self.retries = 0;
        self.el.play.classList.add('is-loading');

        // 不支持 HLS（如 Safari 原生播放）：直接交给 audio 元素
        if (!self.hls) {
            var p = self.audio.play();
            if (p && p.catch) p.catch(function () { self.showError(); });
            return;
        }

        try {
            if (!self.manifestReady) {
                // 清单尚未成功解析：重新加载清单，等 MANIFEST_PARSED 后再正式播放
                self.pendingPlay = true;
                self.hls.loadSource(self.src);
                self.hls.startLoad();
            } else {
                self.hls.startLoad();
                var q = self.audio.play();
                if (q && q.catch) q.catch(function () { self.showError(); });
            }
        } catch (_) {
            self.showError();
        }
    };

    MusicPlayer.prototype.setup = function () {
        var self = this;

        // ---- 加载 HLS 或原生源 ----
        if (self.src) {
            var isHls = /\.m3u8(\?|$)/i.test(self.src);
            if (isHls && typeof window.Hls !== 'undefined' && window.Hls.isSupported()) {
                self.initHls();
            } else {
                self.audio.src = self.src;
            }
        }

        // ---- 播放/暂停 ----
        self.el.play.addEventListener('click', function () {
            if (self.audio.paused) {
                pauseAll(self);
                self.startPlayback();
            } else {
                self.audio.pause();
            }
        });
        self.audio.addEventListener('play', function () {
            self.retries = 0;
            self.root.classList.add('is-playing');
            self.el.play.classList.remove('is-loading');
        });
        self.audio.addEventListener('pause', function () {
            self.root.classList.remove('is-playing');
        });
        self.audio.addEventListener('ended', function () {
            self.root.classList.remove('is-playing');
            self.el.play.classList.remove('is-loading');
        });

        // ---- 加载状态 / 元数据 ----
        self.audio.addEventListener('waiting', function () { self.el.play.classList.add('is-loading'); });
        self.audio.addEventListener('playing', function () { self.el.play.classList.remove('is-loading'); });
        self.audio.addEventListener('loadedmetadata', function () {
            if (self.el.duration) self.el.duration.textContent = formatTime(self.audio.duration);
        });
        self.audio.addEventListener('durationchange', function () {
            if (self.el.duration) self.el.duration.textContent = formatTime(self.audio.duration);
        });
        // hls.js 托管媒体时由 Hls 的 ERROR 事件统一处理并可恢复；
        // 这里只处理无 hls.js（原生播放）的媒体错误，避免一次瞬时错误永久置错。
        self.audio.addEventListener('error', function () {
            if (self.hls) return;
            self.showError();
        });

        // ---- 进度条 ----
        function setFill() {
            var d = self.audio.duration;
            var t = self.audio.currentTime;
            var pct = (d > 0 && isFinite(d)) ? Math.min(100, (t / d) * 100) : 0;
            if (self.el.fill) self.el.fill.style.width = pct + '%';
            if (self.el.thumb) self.el.thumb.style.left = pct + '%';
            if (self.el.current) self.el.current.textContent = formatTime(t);
        }
        function setBuffered() {
            var bar = self.el.progress;
            if (!bar || !self.el.buffered) return;
            var w = bar.clientWidth;
            var max = 0;
            try {
                var buf = self.audio.buffered;
                for (var i = 0; i < buf.length; i++) {
                    if (buf.end(i) > max) max = buf.end(i);
                }
            } catch (_) { return; }
            var d = self.audio.duration || 0;
            var pct = (d > 0 && isFinite(d)) ? Math.min(100, (max / d) * 100) : 0;
            self.el.buffered.style.width = (w > 0 ? (pct / 100) * w : 0) + 'px';
        }
        self.audio.addEventListener('timeupdate', setFill);
        self.audio.addEventListener('progress', setBuffered);
        setBuffered();

        // 点击/拖动 seek
        function seekFromEvent(e) {
            var bar = self.el.progress;
            var rect = bar.getBoundingClientRect();
            var ratio = (e.clientX - rect.left) / rect.width;
            ratio = Math.max(0, Math.min(1, ratio));
            var d = self.audio.duration;
            if (d > 0 && isFinite(d)) {
                self.audio.currentTime = ratio * d;
                setFill();
            }
        }
        self.el.progress.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            self.dragging = true;
            self.el.progress.classList.add('is-dragging');
            seekFromEvent(e);
            var onMove = function (ev) { seekFromEvent(ev); };
            var onUp = function () {
                self.dragging = false;
                self.el.progress.classList.remove('is-dragging');
                window.removeEventListener('pointermove', onMove);
                window.removeEventListener('pointerup', onUp);
            };
            window.addEventListener('pointermove', onMove);
            window.addEventListener('pointerup', onUp);
        });
        self.el.progress.addEventListener('click', function (e) {
            if (self.dragging) return;
            seekFromEvent(e);
        });

        // ---- 倍速 ----
        function setRate(rate) {
            self.audio.playbackRate = rate;
            if (self.el.speedBtn) self.el.speedBtn.textContent = rate.toFixed(2).replace(/\.?0+$/, '') + 'x';
            if (self.el.speedMenu) {
                self.el.speedMenu.querySelectorAll('button').forEach(function (b) {
                    b.classList.toggle('is-active', parseFloat(b.getAttribute('data-rate')) === rate);
                });
            }
        }
        if (self.el.speedBtn) {
            self.el.speedBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                self.el.speedWrap.classList.toggle('open');
            });
            RATES.forEach(function (r) {
                var b = document.createElement('button');
                b.type = 'button';
                b.setAttribute('data-rate', r);
                b.textContent = r + 'x';
                b.addEventListener('click', function () { setRate(r); self.el.speedWrap.classList.remove('open'); });
                self.el.speedMenu.appendChild(b);
            });
            setRate(1);
        }

        // ---- 音量 ----
        var saved = parseFloat(localStorage.getItem(VOLUME_KEY));
        var initVol = (isFinite(saved) && saved >= 0 && saved <= 1) ? saved : 1;
        self.audio.volume = initVol;
        if (self.el.volSlider) self.el.volSlider.value = String(initVol);
        if (self.el.volBtn) {
            self.el.volBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (self.el.volWrap.classList.contains('open')) {
                    self.audio.muted = !self.audio.muted;
                    self.refreshMute();
                } else {
                    self.el.volWrap.classList.add('open');
                }
            });
        }
        if (self.el.volSlider) {
            self.el.volSlider.addEventListener('input', function () {
                var v = parseFloat(self.el.volSlider.value) || 0;
                self.audio.volume = v;
                self.audio.muted = v === 0;
                localStorage.setItem(VOLUME_KEY, String(v));
                self.refreshMute();
            });
        }
        self.refreshMute();

        // 点击页面其它位置时收起弹层
        self.root.addEventListener('click', function (e) {
            if (self.el.speedWrap && !self.el.speedWrap.contains(e.target)) {
                self.el.speedWrap.classList.remove('open');
            }
            if (self.el.volWrap && !self.el.volWrap.contains(e.target)) {
                self.el.volWrap.classList.remove('open');
            }
        });

        players.push(self);
    };

    MusicPlayer.prototype.pause = function (silent) {
        var self = this;
        try { self.audio.pause(); } catch (_) {}
        self.root.classList.remove('is-playing');
        self.el.play.classList.remove('is-loading');
        if (self.el.speedWrap) self.el.speedWrap.classList.remove('open');
        if (self.el.volWrap) self.el.volWrap.classList.remove('open');
        if (!silent && typeof Toast !== 'undefined') {
            // 无额外提示，仅停止其它播放器
        }
    };

    MusicPlayer.prototype.refreshMute = function () {
        var muted = this.audio.muted || this.audio.volume === 0;
        if (this.el.volBtn) this.el.volBtn.classList.toggle('is-muted', muted);
    };

    /* 播放失败：仅在自动重试耗尽后调用。
     * 只做状态提示，不再永久锁死播放按钮——用户再次点击播放会重新发起加载。 */
    MusicPlayer.prototype.showError = function () {
        this.pendingPlay = false;
        this.root.classList.add('is-error');
        this.root.classList.remove('is-playing');
        this.el.play.classList.remove('is-loading');
        try { this.audio.pause(); } catch (_) {}
        if (this.hls) { try { this.hls.stopLoad(); } catch (_) {} }
    };

    // ---- 初始化 ----
    function init() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons(); } catch (_) {}
        }
        document.querySelectorAll('.music-player').forEach(function (root) {
            if (root.__mp) return;
            root.__mp = new MusicPlayer(root);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 暴露初始化入口：动态插入的播放器（如「加载更多」「无刷新搜索」）可手动初始化。
    window.BhxzMusicPlayerInit = init;
})();
