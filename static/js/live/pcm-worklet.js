// 音频直播 - 麦克风 PCM 采集工作线程
// 作用：把麦克风浮点音频转成 48kHz / 双声道 / s16le 小端 PCM，按块抛给主线程上传。
// 说明：AudioWorklet 运行在音频渲染线程，不受页面 JS 卡顿影响，保证采样连续。

const TARGET_RATE = 48000;

function toInt16(value) {
    let v = value < -1 ? -1 : (value > 1 ? 1 : value);
    return v < 0 ? Math.round(v * 0x8000) : Math.round(v * 0x7fff);
}

class PcmTap extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const opts = (options && options.processorOptions) || {};
        this.targetRate = opts.targetRate || TARGET_RATE;
        // ratio = 输入采样率 / 目标采样率（48k 时等于 1，走直通快路径）
        this.ratio = sampleRate / this.targetRate;
        this.sameRate = Math.abs(this.ratio - 1) < 1e-6;
        this.left = [];
        this.right = [];
        this.pos = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input.length || !input[0]) return true;
        const left = input[0];
        const right = input.length > 1 ? input[1] : left;
        for (let i = 0; i < left.length; i++) {
            this.left.push(left[i]);
            this.right.push(right[i]);
        }
        this._emit();
        return true;
    }

    _emit() {
        const n = this.left.length;
        if (!n) return;

        let out;
        if (this.sameRate) {
            out = new Int16Array(n * 2);
            for (let i = 0; i < n; i++) {
                out[i * 2] = toInt16(this.left[i]);
                out[i * 2 + 1] = toInt16(this.right[i]);
            }
            this.left.length = 0;
            this.right.length = 0;
            this.pos = 0;
        } else {
            const count = this.pos <= n - 1
                ? Math.floor((n - 1 - this.pos) / this.ratio) + 1
                : 0;
            if (count <= 0) return;
            out = new Int16Array(count * 2);
            let pos = this.pos;
            for (let i = 0; i < count; i++) {
                const idx = Math.floor(pos);
                const frac = pos - idx;
                const l = this.left[idx] + (this.left[idx + 1] - this.left[idx]) * frac;
                const r = this.right[idx] + (this.right[idx + 1] - this.right[idx]) * frac;
                out[i * 2] = toInt16(l);
                out[i * 2 + 1] = toInt16(r);
                pos += this.ratio;
            }
            const consumed = Math.min(n, Math.floor(pos));
            if (consumed > 0) {
                this.left.splice(0, consumed);
                this.right.splice(0, consumed);
                pos -= consumed;
            }
            this.pos = pos;
        }

        if (out.length) {
            this.port.postMessage(out.buffer, [out.buffer]);
        }
    }
}

registerProcessor('pcm-tap', PcmTap);
