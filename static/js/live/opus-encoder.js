// 音频直播 - 浏览器端 Opus 低延迟编码上传
// 作用：把 AudioWorklet 采集到的 48kHz 双声道 PCM 用 WebCodecs AudioEncoder
//       编码成 20ms/帧的 Opus 包，每 2 帧（约 40ms）通过 HTTPS 上传一批。
// 说明：这是低延迟主路径；浏览器不支持 WebCodecs 时由 PCM → MP3 链路兜底。

(function () {
    'use strict';

    var SAMPLE_RATE = 48000;
    var CHANNELS = 2;
    var FRAME_SAMPLES = 960;          // 20ms @ 48kHz
    var FRAME_MS = 20;
    var BATCH_FRAMES = 2;             // 每批 2 帧（约 40ms）
    var MAX_UPLOAD_QUEUE = 3;         // 网络慢时最多积压 3 批，超出丢弃最旧数据
    var MAX_FAILURES = 5;

    function OpusUploader(opts) {
        opts = opts || {};
        this.uploadUrl = opts.uploadUrl;
        this.onError = opts.onError || function () {};

        this._encoder = null;
        this._enabled = false;
        this._closed = false;
        this._left = [];
        this._right = [];
        this._batch = [];
        this._uploads = [];
        this._uploading = false;
        this._failures = 0;
        this._timestamp = 0;          // AudioData 时间戳（微秒）
        this._abort = null;
    }

    OpusUploader.isSupported = function () {
        return typeof window !== 'undefined'
            && typeof window.AudioEncoder === 'function'
            && typeof window.AudioData === 'function'
            && typeof window.AudioEncoder.isConfigSupported === 'function';
    };

    // 初始化编码器；不支持时返回 false（调用方静默跳过，继续使用 MP3 链路）
    OpusUploader.prototype.init = function () {
        var self = this;
        if (!OpusUploader.isSupported()) return Promise.resolve(false);

        var config = {
            codec: 'opus',
            sampleRate: SAMPLE_RATE,
            numberOfChannels: CHANNELS,
            bitrate: 32000,
            // 固定 20ms 帧，保证播放端可按固定时长做抖动缓冲
            opus: { frameDuration: FRAME_MS * 1000 }
        };

        return window.AudioEncoder.isConfigSupported(config).then(function (res) {
            if (self._closed || !res || !res.supported) return false;
            self._encoder = new window.AudioEncoder({
                output: function (chunk) { self._onChunk(chunk); },
                error: function () { self._shutdown('Opus 编码器异常'); }
            });
            self._encoder.configure(config);
            self._enabled = true;
            return true;
        }).catch(function () {
            return false;
        });
    };

    // 喂入 AudioWorklet 抛出的 s16le 交错 PCM（ArrayBuffer）
    OpusUploader.prototype.pushPcm = function (buffer) {
        if (!this._enabled || this._closed || !buffer || !buffer.byteLength) return;
        var pcm = new Int16Array(buffer);
        var left = this._left;
        var right = this._right;
        for (var i = 0; i + 1 < pcm.length; i += 2) {
            left.push(pcm[i] / 32768);
            right.push(pcm[i + 1] / 32768);
        }
        while (left.length >= FRAME_SAMPLES) {
            this._encodeFrame();
        }
    };

    OpusUploader.prototype._encodeFrame = function () {
        var planar = new Float32Array(FRAME_SAMPLES * CHANNELS);
        for (var i = 0; i < FRAME_SAMPLES; i++) {
            planar[i] = this._left[i];
            planar[FRAME_SAMPLES + i] = this._right[i];
        }
        this._left.splice(0, FRAME_SAMPLES);
        this._right.splice(0, FRAME_SAMPLES);

        var data = new window.AudioData({
            format: 'f32-planar',
            sampleRate: SAMPLE_RATE,
            numberOfFrames: FRAME_SAMPLES,
            numberOfChannels: CHANNELS,
            timestamp: this._timestamp,
            data: planar
        });
        this._timestamp += FRAME_MS * 1000;
        try {
            this._encoder.encode(data);
        } catch (e) {
            this._shutdown('Opus 编码失败');
        }
        data.close();
    };

    OpusUploader.prototype._onChunk = function (chunk) {
        if (this._closed) return;
        var bytes = new Uint8Array(chunk.byteLength);
        chunk.copyTo(bytes);
        this._batch.push(bytes);
        if (this._batch.length >= BATCH_FRAMES) this._flushBatch();
    };

    OpusUploader.prototype._flushBatch = function () {
        if (!this._batch.length) return;
        var packets = this._batch;
        this._batch = [];

        var total = 0;
        packets.forEach(function (p) { total += 2 + p.length; });
        var body = new Uint8Array(total);
        var view = new DataView(body.buffer);
        var offset = 0;
        packets.forEach(function (p) {
            view.setUint16(offset, p.length, false);  // 大端长度前缀
            offset += 2;
            body.set(p, offset);
            offset += p.length;
        });

        if (this._uploads.length >= MAX_UPLOAD_QUEUE) this._uploads.shift();
        this._uploads.push(body.buffer);
        this._pump();
    };

    OpusUploader.prototype._pump = function () {
        var self = this;
        if (this._uploading || !this._uploads.length || this._closed) return;
        var body = this._uploads.shift();
        this._uploading = true;
        this._abort = new AbortController();

        fetch(this.uploadUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: body,
            signal: this._abort.signal
        }).then(function (res) {
            return res.json().catch(function () { return {}; }).then(function (data) {
                if (!res.ok || data.success === false) {
                    throw new Error(data.message || ('Opus 上传失败（' + res.status + '）'));
                }
            });
        }).then(function () {
            self._uploading = false;
            self._failures = 0;
            self._pump();
        }).catch(function (err) {
            self._uploading = false;
            if (self._closed) return;
            self._failures += 1;
            if (self._failures >= MAX_FAILURES) {
                self._shutdown((err && err.message) || 'Opus 上传失败');
                return;
            }
            // 丢掉落后的旧数据，保持低延迟；下一批继续尝试
            self._pump();
        });
    };

    // 主动关闭（断开麦克风 / 页面卸载）
    OpusUploader.prototype.close = function () {
        this._closed = true;
        this._enabled = false;
        this._uploads.length = 0;
        this._batch = [];
        this._left.length = 0;
        this._right.length = 0;
        if (this._abort) {
            try { this._abort.abort(); } catch (e) {}
            this._abort = null;
        }
        if (this._encoder) {
            try { this._encoder.close(); } catch (e) {}
            this._encoder = null;
        }
    };

    // 内部故障：停止编码并通知上层回退到 PCM / MP3 链路
    OpusUploader.prototype._shutdown = function (message) {
        if (this._closed) return;
        var callback = this.onError;
        this.close();
        try { callback(message); } catch (e) {}
    };

    window.OpusUploader = OpusUploader;
})();
