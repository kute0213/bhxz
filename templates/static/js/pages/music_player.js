/* 大喇叭自定义音频播放器（磨砂玻璃风格）。
 *
 * 页面中每个 .music-player 元素（由 macros/music_macros.html 的
 * music_audio_player 宏渲染）都会初始化为一个独立播放器，支持：
 *   - 播放/暂停（同一时间只允许一个播放器出声）
 *   - 进度条：点击/拖动 seek，展示已缓冲范围
 *   - 倍速：0.5x ~ 2.0x
 *   - 音量：按钮静音/取消静音，滑块调节（音量记忆在 localStorage）
 *   - HLS 播放：优先使用本地 hls.js，不支持时回退原生播放
 *
 * 依赖：hls.js（static/lib/hls/hls.min.js，可选）、Lucide（可选）
 */
(function () {
    'use strict';

    var RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
    var VOLUME_KEY = 'bhxz:mp:volume';
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
        this.setup();
    }

    MusicPlayer.prototype.setup = function () {
        var self = this;

        // ---- 加载 HLS 或原生源 ----
        if (self.src) {
            var isHls = /\.m3u8(\?|$)/i.test(self.src);
            if (isHls && typeof window.Hls !== 'undefined' && window.Hls.isSupported()) {
                self.hls = new window.Hls({ lowLatencyMode: false });
                self.hls.loadSource(self.src);
                self.hls.attachMedia(self.audio);
            } else {
                self.audio.src = self.src;
            }
        }

        // ---- 播放/暂停 ----
        self.el.play.addEventListener('click', function () {
            if (self.root.classList.contains('is-error')) return;
            if (self.audio.paused) {
                pauseAll(self);
                self.audio.play().catch(function () { self.showError(); });
            } else {
                self.audio.pause();
            }
        });
        self.audio.addEventListener('play', function () {
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
        self.audio.addEventListener('error', function () { self.showError(); });

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

    MusicPlayer.prototype.showError = function () {
        this.root.classList.add('is-error');
        this.root.classList.remove('is-playing');
        this.el.play.classList.remove('is-loading');
        this.audio.pause();
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
})();
