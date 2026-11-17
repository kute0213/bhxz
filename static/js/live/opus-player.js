// 音频直播 - Opus 低延迟播放
// 作用：用 fetch 流式读取服务端转发的 Opus 包（2 字节长度前缀帧），
//       交给 WebCodecs AudioDecoder 解码，再用 Web Audio 精确调度播放。
// 说明：以约 80ms 抖动缓冲为首要目标，积压过大时丢弃旧帧保证延迟不累积；
//       不支持 WebCodecs / 1.5 秒内没有可播放数据时通过 onFallback 回退 MP3。

(function () {
    'use strict';

    var TARGET_BUFFER = 0.08;         // 目标缓冲 80ms
    var START_TIMEOUT_MS = 1500;      // 超时未出音则回退
    var MAX_BACKLOG = 0.4;            // 积压超过 400ms 视为异常
    var TRIM_TO = 0.15;               // 积压时只保留未来 150ms 内已排期的音频

    function OpusPlayer(opts) {
        opts = opts || {};
        this.streamUrl = opts.streamUrl;
        this.volume = opts.volume == null ? 1 : opts.volume;
        this.onFallback = opts.onFallback || function () {};
        this.onStatus = opts.onStatus || function () {};

        this._ctx = null;
        this._gain = null;
        this._decoder = null;
        this._reader = null;
        this._abort = null;
        this._sources = [];           // {node, start, end}
        this._scheduledUntil = 0;
        this._timestamp = 0;
        this._gotAudio = false;
        this._stopped = false;
        this._fallbackFired = false;
        this._timer = null;
    }

    OpusPlayer.isSupported = function () {
        return typeof window !== 'undefined'
            && typeof window.AudioDecoder === 'function'
            && typeof window.AudioData === 'function'
            && typeof window.AudioDecoder.isConfigSupported === 'function'
            && !!(window.AudioContext || window.webkitAudioContext);
    };

    OpusPlayer.prototype.start = function () {
        var self = this;
        var Ctx = window.AudioContext || window.webkitAudioContext;
        this._ctx = new Ctx({ sampleRate: 48000 });
        if (this._ctx.state === 'suspended') {
            this._ctx.resume().catch(function () {});
        }
        this._gain = this._ctx.createGain();
        this._gain.gain.value = this.volume;
        this._gain.connect(this._ctx.destination);

        this._timer = setTimeout(function () {
            if (!self._gotAudio && !self._stopped) {
                self._fallback('未能在 1.5 秒内收到可播放音频');
            }
        }, START_TIMEOUT_MS);

        var config = { codec: 'opus', sampleRate: 48000, numberOfChannels: 2 };
        return window.AudioDecoder.isConfigSupported(config).then(function (res) {
            if (!res || !res.supported) throw new Error('浏览器不支持 Opus 解码');
            return self._openStream();
        }).catch(function (err) {
            self._fallback((err && err.message) || 'Opus 播放不可用');
        });
    };

    OpusPlayer.prototype._openStream = function () {
        var self = this;
        this._abort = new AbortController();
        return fetch(this.streamUrl, {
            signal: this._abort.signal,
            cache: 'no-store',
            headers: { 'Accept': 'application/octet-stream' }
        }).then(function (res) {
            if (!res.ok || !res.body) throw new Error('音频流连接失败（' + res.status + '）');

            self._decoder = new window.AudioDecoder({
                output: function (frame) { self._onFrame(frame); },
                error: function () { self._fallback('Opus 解码失败'); }
            });
            self._decoder.configure({ codec: 'opus', sampleRate: 48000, numberOfChannels: 2 });

            self._reader = res.body.getReader();
            var pending = new Uint8Array(0);

            function pump() {
                return self._reader.read().then(function (result) {
                    if (result.done) {
                        if (!self._stopped) self._fallback('音频流已结束');
                        return;
                    }
                    pending = concatBuffer(pending, result.value);
                    var pos = 0;
                    while (pending.length - pos >= 2) {
                        var size = (pending[pos] << 8) | pending[pos + 1];
                        if (pending.length - pos - 2 < size) break;
                        var packet = pending.subarray(pos + 2, pos + 2 + size);
                        pos += 2 + size;
                        if (size === 0) continue;   // 心跳帧
                        self._decode(packet);
                    }
                    pending = pending.slice(pos);
                    // 异常数据兜底：正常一批只有几百字节，超过 64KB 说明格式错乱
                    if (pending.length > 65536) pending = new Uint8Array(0);
                    return pump();
                });
            }
            return pump();
        });
    };

    OpusPlayer.prototype._decode = function (packet) {
        if (this._stopped || !this._decoder) return;
        try {
            var chunk = new window.EncodedAudioChunk({
                type: 'key',
                timestamp: this._timestamp,
                duration: 20000,
                data: packet
            });
            this._timestamp += 20000;
            this._decoder.decode(chunk);
        } catch (e) {
            // 单个包损坏时跳过，不中断整条链路
        }
    };

    OpusPlayer.prototype._onFrame = function (frame) {
        var ctx = this._ctx;
        if (!ctx || this._stopped) {
            frame.close();
            return;
        }
        var channels = frame.numberOfChannels || 2;
        var buffer = ctx.createBuffer(channels, frame.numberOfFrames, frame.sampleRate || 48000);
        for (var ch = 0; ch < channels; ch++) {
            frame.copyTo(buffer.getChannelData(ch), { planeIndex: ch, format: 'f32-planar' });
        }
        frame.close();

        if (!this._gotAudio) {
            this._gotAudio = true;
            if (this._timer) { clearTimeout(this._timer); this._timer = null; }
            this.onStatus('正在收听（低延迟）');
        }

        var now = ctx.currentTime;
        var startAt = this._scheduledUntil;
        if (startAt < now + 0.02) {
            // 首次播放或上一段已播完：从目标缓冲处重新对齐
            startAt = now + TARGET_BUFFER;
        } else if (startAt - now > MAX_BACKLOG) {
            // 积压过大（网络突发 / 设备卡顿）：丢掉尚未播放的排期，避免延迟累积
            this._trim(now + TRIM_TO);
            startAt = Math.max(now + 0.03, this._scheduledUntil);
        }

        var source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(this._gain);
        source.start(startAt);
        this._scheduledUntil = startAt + buffer.duration;
        this._sources.push({ node: source, start: startAt, end: this._scheduledUntil });
        this._prune(now);
    };

    OpusPlayer.prototype._trim = function (limit) {
        var kept = [];
        var end = limit;
        for (var i = 0; i < this._sources.length; i++) {
            var item = this._sources[i];
            if (item.start > limit) {
                try { item.node.stop(); } catch (e) {}
            } else {
                kept.push(item);
                if (item.end > end) end = item.end;
            }
        }
        this._sources = kept;
        this._scheduledUntil = end;
    };

    OpusPlayer.prototype._prune = function (now) {
        if (this._sources.length < 8) return;
        this._sources = this._sources.filter(function (item) {
            return item.end > now - 0.2;
        });
    };

    OpusPlayer.prototype.setVolume = function (value) {
        this.volume = value;
        if (this._gain) this._gain.gain.value = value;
    };

    OpusPlayer.prototype._fallback = function (reason) {
        if (this._stopped || this._fallbackFired) return;
        this._fallbackFired = true;
        this.stop();
        this.onFallback(reason);
    };

    OpusPlayer.prototype.stop = function () {
        this._stopped = true;
        if (this._timer) { clearTimeout(this._timer); this._timer = null; }
        if (this._abort) {
            try { this._abort.abort(); } catch (e) {}
            this._abort = null;
        }
        if (this._reader) {
            try { this._reader.cancel(); } catch (e) {}
            this._reader = null;
        }
        if (this._decoder) {
            try { this._decoder.close(); } catch (e) {}
            this._decoder = null;
        }
        for (var i = 0; i < this._sources.length; i++) {
            try { this._sources[i].node.stop(); } catch (e) {}
        }
        this._sources = [];
        if (this._gain) {
            try { this._gain.disconnect(); } catch (e) {}
            this._gain = null;
        }
        if (this._ctx) {
            try { this._ctx.close().catch(function () {}); } catch (e) {}
            this._ctx = null;
        }
    };

    function concatBuffer(a, b) {
        if (!a.length) return b;
        var out = new Uint8Array(a.length + b.length);
        out.set(a, 0);
        out.set(b, a.length);
        return out;
    }

    window.OpusPlayer = OpusPlayer;
})();
