/**
 * terminal-core.js — 终端核心逻辑复用库
 *
 * 抽取 terminal.js 与 editor-terminal.js 的公共部分：
 *   - ANSI 颜色/样式解析与 CSS 生成
 *   - 终端输出缓冲区（含 \r / \n / \b / \x0c / ANSI 控制序列处理）
 *   - SSE 连接管理（连接、断线重连、心跳看门狗、待发送队列）
 *   - 命令历史（localStorage 持久化、上下键切换）
 *   - 输入发送（队列 + POST /admin/cmd/terminal/input）
 *
 * 不依赖任何具体 DOM 结构，调用方传入容器与回调即可使用。
 * 暴露：window.TerminalCore
 */
window.TerminalCore = (function () {
    'use strict';

    // ==================================================================
    // ANSI 颜色映射
    // ==================================================================
    const ANSI_COLORS = {
        0: '#000000', 1: '#aa0000', 2: '#00aa00', 3: '#aa5500',
        4: '#0000aa', 5: '#aa00aa', 6: '#00aaaa', 7: '#aaaaaa',
        8: '#555555', 9: '#ff5555', 10: '#55ff55', 11: '#ffff55',
        12: '#5555ff', 13: '#ff55ff', 14: '#55ffff', 15: '#ffffff',
    };

    function ansi256ToHex(n) {
        n = Math.max(0, Math.min(255, n));
        if (n < 16) return ANSI_COLORS[n];
        if (n >= 232) {
            const v = Math.round((n - 232) * 255 / 23);
            const hex = v.toString(16).padStart(2, '0');
            return '#' + hex + hex + hex;
        }
        const c = n - 16;
        const r = Math.floor(c / 36);
        const g = Math.floor((c % 36) / 6);
        const b = c % 6;
        const toVal = (v) => v === 0 ? 0 : 55 + v * 40;
        const hex = (v) => v.toString(16).padStart(2, '0');
        return '#' + hex(toVal(r)) + hex(toVal(g)) + hex(toVal(b));
    }

    // ==================================================================
    // AnsiRenderer：维护当前 ANSI 样式并生成 CSS
    // ==================================================================
    function AnsiRenderer() {
        this.reset();
    }

    AnsiRenderer.prototype.reset = function () {
        this.bold = false;
        this.dim = false;
        this.italic = false;
        this.underline = false;
        this.blink = false;
        this.reverse = false;
        this.hidden = false;
        this.strikethrough = false;
        this.fg = null;
        this.bg = null;
    };

    AnsiRenderer.prototype.applySgr = function (params) {
        if (!params || params.length === 0) {
            this.reset();
            return;
        }
        let i = 0;
        while (i < params.length) {
            const p = params[i];
            switch (true) {
                case p === 0: this.reset(); break;
                case p === 1: this.bold = true; break;
                case p === 2: this.dim = true; break;
                case p === 3: this.italic = true; break;
                case p === 4: this.underline = true; break;
                case p === 5: this.blink = true; break;
                case p === 7: this.reverse = true; break;
                case p === 8: this.hidden = true; break;
                case p === 9: this.strikethrough = true; break;
                case p === 22: this.bold = false; this.dim = false; break;
                case p === 23: this.italic = false; break;
                case p === 24: this.underline = false; break;
                case p === 25: this.blink = false; break;
                case p === 27: this.reverse = false; break;
                case p === 28: this.hidden = false; break;
                case p === 29: this.strikethrough = false; break;
                case p >= 30 && p <= 37: this.fg = ANSI_COLORS[p - 30]; break;
                case p >= 40 && p <= 47: this.bg = ANSI_COLORS[p - 40]; break;
                case p >= 90 && p <= 97: this.fg = ANSI_COLORS[p - 90 + 8]; break;
                case p >= 100 && p <= 107: this.bg = ANSI_COLORS[p - 100 + 8]; break;
                case p === 39: this.fg = null; break;
                case p === 49: this.bg = null; break;
                case p === 38 && i + 1 < params.length:
                    i += this._applyExtendedColor(params, i, 'fg');
                    break;
                case p === 48 && i + 1 < params.length:
                    i += this._applyExtendedColor(params, i, 'bg');
                    break;
            }
            i++;
        }
    };

    AnsiRenderer.prototype._applyExtendedColor = function (params, i, key) {
        const mode = params[i + 1];
        if (mode === 5 && i + 2 < params.length) {
            this[key] = ansi256ToHex(params[i + 2]);
            return 2;
        }
        if (mode === 2 && i + 4 < params.length) {
            this[key] = `rgb(${params[i + 2]},${params[i + 3]},${params[i + 4]})`;
            return 4;
        }
        return 0;
    };

    AnsiRenderer.prototype.buildCss = function () {
        const parts = [];
        let fg = this.fg;
        let bg = this.bg;

        if (this.reverse) {
            [fg, bg] = [bg, fg];
            if (!fg) fg = '#e2e8f0';
            if (!bg) bg = '#000000';
        }

        parts.push('color:' + (fg || '#e2e8f0'));
        if (bg) parts.push('background-color:' + bg);
        if (this.bold) parts.push('font-weight:700');
        if (this.dim) parts.push('opacity:0.6');
        if (this.italic) parts.push('font-style:italic');
        if (this.underline) parts.push('text-decoration:underline');
        if (this.blink) parts.push('animation:term-blink 1s steps(2) infinite');
        if (this.hidden) parts.push('visibility:hidden');
        if (this.strikethrough) parts.push('text-decoration:line-through');

        return parts.join(';');
    };

    // ==================================================================
    // TerminalBuffer：终端输出缓冲区与渲染
    // ==================================================================
    function TerminalBuffer(container, options) {
        this.container = container;
        this.options = options || {};
        this.scroller = this.options.scroller || container.parentElement || container;
        this.renderer = new AnsiRenderer();
        this.fragments = [];      // 当前行片段 [{text, css}]
        this.pendingCr = false;   // \r 后未遇到普通字符
        this.autoScroll = true;
        this._bindScroll();
    }

    TerminalBuffer.prototype._bindScroll = function () {
        const scroller = this.scroller;
        if (!scroller) return;
        const self = this;
        scroller.addEventListener('scroll', function () {
            const dist = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
            self.autoScroll = dist < 50;
        });
    };

    TerminalBuffer.prototype._getCurrentLine = function () {
        let line = this.container.querySelector('.term-current-line');
        if (!line) {
            line = document.createElement('div');
            line.className = 'term-current-line';
            line.style.cssText = 'padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;line-height:1.4;';
            this.container.appendChild(line);
        }
        return line;
    };

    TerminalBuffer.prototype._renderCurrentLine = function () {
        const line = this._getCurrentLine();
        line.innerHTML = '';
        for (const frag of this.fragments) {
            const span = document.createElement('span');
            span.style.cssText = frag.css;
            span.textContent = frag.text;
            line.appendChild(span);
        }
    };

    TerminalBuffer.prototype._pushFragment = function (text) {
        if (!text) return;
        const css = this.renderer.buildCss();
        const last = this.fragments[this.fragments.length - 1];
        if (last && last.css === css) {
            last.text += text;
        } else {
            this.fragments.push({ text: text, css: css });
        }
    };

    TerminalBuffer.prototype._flushLine = function () {
        if (this.fragments.length === 0) return;
        const line = document.createElement('div');
        line.style.cssText = 'padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;line-height:1.4;';
        for (const frag of this.fragments) {
            const span = document.createElement('span');
            span.style.cssText = frag.css;
            span.textContent = frag.text;
            line.appendChild(span);
        }
        this.container.appendChild(line);
        this.fragments = [];
    };

    TerminalBuffer.prototype._finalizeCurrentLine = function () {
        const cl = this.container.querySelector('.term-current-line');
        if (cl) {
            // 当前行已在 DOM 中渲染，直接移除标记类即可作为 finalized 行。
            // 不再调用 _flushLine() 创建新 div，避免同一行内容被重复输出。
            cl.classList.remove('term-current-line');
        } else if (this.fragments.length > 0) {
            // 兜底：无当前行但仍有片段时 flush
            this._flushLine();
        }
        this.fragments = [];
    };

    TerminalBuffer.prototype._parseAnsiEscape = function (text, start) {
        let i = start + 1;
        if (i >= text.length) return { next: i };

        if (text[i] === '[') {
            i++;
            let paramStr = '';
            while (i < text.length) {
                const code = text.charCodeAt(i);
                if (code >= 0x40 && code <= 0x7e) {
                    const finalByte = text[i];
                    i++;
                    if (finalByte === 'm') {
                        const params = paramStr ? paramStr.split(';').map(s => parseInt(s, 10) || 0) : [0];
                        return { next: i, sgr: true, params: params };
                    }
                    if (finalByte === 'K') {
                        const mode = paramStr ? parseInt(paramStr, 10) : 0;
                        return { next: i, eraseLine: mode };
                    }
                    return { next: i };
                }
                if (code >= 0x20 && code <= 0x3f) {
                    paramStr += text[i];
                    i++;
                    continue;
                }
                break;
            }
            return { next: i };
        }

        if (text[i] === ']') {
            i++;
            while (i < text.length) {
                if (text[i] === '\x07') { i++; break; }
                if (text[i] === '\x1b' && i + 1 < text.length && text[i + 1] === '\\') { i += 2; break; }
                i++;
            }
            return { next: i };
        }

        return { next: i + 1 };
    };

    TerminalBuffer.prototype.handleOutput = function (text) {
        if (text == null) return;
        text = String(text);
        let i = 0;
        while (i < text.length) {
            const ch = text[i];
            if (ch === '\n') {
                this._finalizeCurrentLine();
                this.fragments = [];
                this.pendingCr = false;
                this._pushFragment('');
                this._renderCurrentLine();
                i++;
            } else if (ch === '\r') {
                this.pendingCr = true;
                i++;
            } else if (ch === '\x1b') {
                const result = this._parseAnsiEscape(text, i);
                i = result.next;
                if (result.sgr) {
                    this.renderer.applySgr(result.params);
                    this._renderCurrentLine();
                } else if (result.eraseLine !== undefined) {
                    if (result.eraseLine === 2 || result.eraseLine === 0) {
                        this.fragments = [];
                    }
                    this.pendingCr = false;
                    this._renderCurrentLine();
                }
            } else if (ch === '\x08') {
                if (this.pendingCr) this.pendingCr = false;
                if (this.fragments.length > 0) {
                    const last = this.fragments[this.fragments.length - 1];
                    if (last.text.length > 0) {
                        last.text = last.text.slice(0, -1);
                    } else if (this.fragments.length > 1) {
                        this.fragments.pop();
                    }
                    this._renderCurrentLine();
                }
                i++;
            } else if (ch === '\x07') {
                i++;
            } else if (ch === '\x0c') {
                this.clear(false);
                this.pendingCr = false;
                i++;
            } else {
                if (this.pendingCr) {
                    this.fragments = [];
                    this.pendingCr = false;
                }
                this._pushFragment(ch);
                this._renderCurrentLine();
                i++;
            }
        }
        this.scrollToBottom();
    };

    TerminalBuffer.prototype.appendLine = function (text, type) {
        this._finalizeCurrentLine();

        const colorMap = {
            'info': '#60a5fa',
            'error': '#f87171',
            'warning': '#fbbf24',
            'success': '#4ade80',
            'dim': '#64748b',
            'script': '#a3e635',
            'input': '#fbbf24',
        };

        const line = document.createElement('div');
        if (type === 'input') {
            line.style.cssText = 'padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            const prompt = document.createElement('span');
            prompt.style.cssText = 'color:#4ade80;';
            prompt.textContent = '$ ';
            const cmd = document.createElement('span');
            cmd.style.cssText = 'color:' + colorMap.input + ';';
            cmd.textContent = text;
            line.appendChild(prompt);
            line.appendChild(cmd);
        } else if (type === 'script') {
            line.style.cssText = 'padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            const tag = document.createElement('span');
            tag.style.cssText = 'display:inline-block;padding:2px 6px;border-radius:4px;background:rgba(168,85,247,0.2);color:#d8b4fe;font-size:11px;margin-right:4px;';
            tag.textContent = '脚本';
            line.appendChild(tag);
            const txt = document.createElement('span');
            txt.style.cssText = 'color:' + colorMap.script + ';';
            txt.textContent = text;
            line.appendChild(txt);
        } else {
            const color = colorMap[type] || '#e2e8f0';
            line.style.cssText = 'color:' + color + ';padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            line.textContent = text;
        }

        this.container.appendChild(line);
        this.fragments = [];
        this.renderer.reset();
        this._pushFragment('');
        this._renderCurrentLine();
        this.scrollToBottom();
    };

    TerminalBuffer.prototype.clear = function (keepCurrentLine) {
        this.container.innerHTML = '';
        this.fragments = [];
        this.pendingCr = false;
        this.renderer.reset();
        if (keepCurrentLine !== false) {
            this._pushFragment('');
            this._renderCurrentLine();
        }
    };

    TerminalBuffer.prototype.scrollToBottom = function () {
        if (!this.autoScroll) return;
        const scroller = this.scroller;
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
    };

    // ==================================================================
    // SseTerminal：基于 EventSource 的终端连接管理
    // ==================================================================
    function SseTerminal(options) {
        this.url = options.url || '/admin/cmd/terminal/stream';
        this.inputUrl = options.inputUrl || '/admin/cmd/terminal/input';
        this.onEvent = options.onEvent || function () {};
        this.onConnected = options.onConnected || function () {};
        this.onDisconnected = options.onDisconnected || function () {};
        this.shouldConnect = options.shouldConnect || function () { return true; };

        this.eventSource = null;
        this.connected = false;
        this.reconnectTimer = null;
        this.manualCloseToken = 0;
        this.pendingInputQueue = [];
        this.lastDataTime = Date.now();
        this.watchdogTimer = null;
        this._connecting = false;

        this.RECONNECT_DELAY = options.reconnectDelay || 3000;
        this.WATCHDOG_TIMEOUT = options.watchdogTimeout || 35000;
        this.WATCHDOG_INTERVAL = options.watchdogInterval || 5000;
    }

    SseTerminal.prototype.connect = function () {
        if (this._connecting) return;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (!this.shouldConnect()) return;

        this._connecting = true;
        const closedToken = ++this.manualCloseToken;
        if (this.eventSource) {
            try { this.eventSource.close(); } catch (_) {}
            this.eventSource = null;
        }

        this.connected = false;
        this.lastDataTime = Date.now();

        const es = new EventSource(this.url, { withCredentials: true });
        const self = this;

        es.onopen = function () {
            self._connecting = false;
            self.connected = true;
            self.lastDataTime = Date.now();
            if (self.reconnectTimer) {
                clearTimeout(self.reconnectTimer);
                self.reconnectTimer = null;
            }
            self._startWatchdog();
            self._flushPendingQueue();
            self.onConnected();
        };

        es.onmessage = function (e) {
            let msg;
            try { msg = JSON.parse(e.data); } catch (_) { return; }
            self.lastDataTime = Date.now();
            self.onEvent(msg);
        };

        es.onerror = function () {
            self._connecting = false;
            const myToken = closedToken;
            if (self.connected) {
                self.connected = false;
                self.onDisconnected('error');
            }
            try { es.close(); } catch (_) {}
            if (self.eventSource === es) self.eventSource = null;

            if (myToken !== self.manualCloseToken) return;
            self._scheduleReconnect();
        };

        this.eventSource = es;
    };

    SseTerminal.prototype.disconnect = function () {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        ++this.manualCloseToken;
        this._connecting = false;
        this._stopWatchdog();
        if (this.eventSource) {
            try { this.eventSource.close(); } catch (_) {}
            this.eventSource = null;
        }
        this.connected = false;
    };

    SseTerminal.prototype.send = function (text) {
        if (!this.connected) {
            this.pendingInputQueue.push(text);
            if (!this.eventSource && this.shouldConnect()) {
                this.connect();
            }
            return;
        }
        this._sendNow(text);
    };

    SseTerminal.prototype._sendNow = function (text) {
        const self = this;
        fetch(this.inputUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text }),
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.json().then(function (data) {
                    self.onEvent({ type: 'error', data: { message: '[发送失败] ' + (data.message || 'HTTP ' + resp.status) } });
                }).catch(function () {
                    self.onEvent({ type: 'error', data: { message: '[发送失败] HTTP ' + resp.status } });
                });
            }
        }).catch(function (err) {
            self.onEvent({ type: 'error', data: { message: '[发送失败] ' + (err.message || String(err)) } });
        });
    };

    SseTerminal.prototype._flushPendingQueue = function () {
        while (this.pendingInputQueue.length > 0 && this.connected) {
            const text = this.pendingInputQueue.shift();
            this._sendNow(text);
        }
    };

    SseTerminal.prototype._startWatchdog = function () {
        this._stopWatchdog();
        const self = this;
        this.watchdogTimer = setInterval(function () {
            if (!self.shouldConnect()) return;
            if (!self.connected) return;
            const elapsed = Date.now() - self.lastDataTime;
            if (elapsed > self.WATCHDOG_TIMEOUT) {
                self.onEvent({ type: 'error', data: { message: '[长时间无心跳，主动重连…]' } });
                if (self.eventSource) {
                    try { self.eventSource.close(); } catch (_) {}
                    self.eventSource = null;
                }
                self.connected = false;
                self._scheduleReconnect();
            }
        }, this.WATCHDOG_INTERVAL);
    };

    SseTerminal.prototype._stopWatchdog = function () {
        if (this.watchdogTimer) {
            clearInterval(this.watchdogTimer);
            this.watchdogTimer = null;
        }
    };

    SseTerminal.prototype._scheduleReconnect = function () {
        if (this.reconnectTimer) return;
        if (!this.shouldConnect()) return;
        const self = this;
        this.reconnectTimer = setTimeout(function () {
            self.reconnectTimer = null;
            if (self.shouldConnect()) self.connect();
        }, this.RECONNECT_DELAY);
    };

    SseTerminal.prototype.isConnected = function () {
        return this.connected;
    };

    // ==================================================================
    // CommandHistory：命令历史（localStorage 持久化）
    // ==================================================================
    function CommandHistory(storageKey, maxSize) {
        this.storageKey = storageKey;
        this.maxSize = maxSize || 200;
        this.items = [];
        this.index = -1;
        this.draft = '';
        this._load();
    }

    CommandHistory.prototype._load = function () {
        try {
            const raw = localStorage.getItem(this.storageKey);
            if (raw) this.items = JSON.parse(raw) || [];
        } catch (_) { this.items = []; }
    };

    CommandHistory.prototype._save = function () {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(this.items));
        } catch (_) {}
    };

    CommandHistory.prototype.add = function (cmd) {
        if (!cmd || !cmd.trim()) return;
        if (this.items[this.items.length - 1] === cmd) return;
        this.items.push(cmd);
        if (this.items.length > this.maxSize) this.items.shift();
        this._save();
    };

    CommandHistory.prototype.navigate = function (dir, inputEl) {
        if (this.items.length === 0) return;
        if (this.index === -1) this.draft = inputEl.value;

        if (dir < 0) {
            if (this.index === -1) this.index = this.items.length - 1;
            else if (this.index > 0) this.index--;
        } else {
            if (this.index < this.items.length - 1) this.index++;
            else {
                this.index = -1;
                inputEl.value = this.draft;
                return;
            }
        }

        if (this.index >= 0 && this.index < this.items.length) {
            inputEl.value = this.items[this.index];
            setTimeout(function () {
                inputEl.selectionStart = inputEl.selectionEnd = inputEl.value.length;
            }, 0);
        }
    };

    CommandHistory.prototype.resetIndex = function () {
        this.index = -1;
        this.draft = '';
    };

    // ==================================================================
    // 工具：确保闪烁动画样式只注入一次
    // ==================================================================
    function ensureBlinkStyle() {
        if (!document.getElementById('term-blink-style')) {
            const style = document.createElement('style');
            style.id = 'term-blink-style';
            style.textContent = '@keyframes term-blink{0%,50%{opacity:1}50.01%,100%{opacity:0}}';
            document.head.appendChild(style);
        }
    }

    // ==================================================================
    // 公共 API
    // ==================================================================
    return {
        AnsiRenderer: AnsiRenderer,
        TerminalBuffer: TerminalBuffer,
        SseTerminal: SseTerminal,
        CommandHistory: CommandHistory,
        ensureBlinkStyle: ensureBlinkStyle,
        ansi256ToHex: ansi256ToHex,
    };
})();
