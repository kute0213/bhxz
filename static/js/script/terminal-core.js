/**
 * terminal-core.js — 终端核心逻辑复用库
 *
 * 抽取 terminal.js 与 editor-terminal.js 的公共部分：
 *   - ANSI 颜色/样式解析与 CSS 生成
 *   - 终端输出缓冲区（含 \r / \n / \b / \x0c / ANSI 控制序列处理）
 *   - SSE 连接管理（连接、断线重连、心跳看门狗、待发送队列）
 *   - 命令历史（localStorage 持久化、上下键切换）
 *   - 输入发送（队列 + POST /admin/script/terminal/input）
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
        this.cols = this.options.cols || 120;
        this.rows = this.options.rows || 0;            // 运行时根据容器高度计算
        this.maxScrollback = this.options.maxScrollback || 2000;
        this.autoScroll = true;

        this.renderer = new AnsiRenderer();

        // 网格缓冲：lines[i] = 长度为 cols 的 cell 数组，cell = {ch, css}
        this.lines = [];
        this.cursorRow = 0;   // 光标的绝对行号（位于 lines 中）
        this.cursorCol = 0;

        this.lineHeight = 20; // 通过测量覆盖
        this._dirty = false;
        this._rafPending = false;
        this._lineEls = [];
        this._boundResize = null;

        this._buildDom();
        this._measure();
        this._bindScroll();
    }

    // ------------------- DOM 结构 -------------------
    TerminalBuffer.prototype._buildDom = function () {
        this.spacer = document.createElement('div');
        this.spacer.style.display = 'block';
        this.viewport = document.createElement('div');
        this.viewport.style.cssText = 'display:block;overflow:hidden;line-height:1.4;';
        this.inner = document.createElement('div');
        this.inner.style.cssText = 'position:relative;';
        this.inner.appendChild(this.spacer);
        this.inner.appendChild(this.viewport);
        this.container.appendChild(this.inner);
    };

    TerminalBuffer.prototype._measure = function () {
        const probe = document.createElement('div');
        probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;line-height:1.4;font:inherit;';
        probe.textContent = 'M';
        document.body.appendChild(probe);
        const h = probe.getBoundingClientRect().height;
        if (h > 0) this.lineHeight = h;
        document.body.removeChild(probe);
    };

    TerminalBuffer.prototype._visibleRows = function () {
        if (this.options.rows) return this.options.rows;
        const scroller = this.scroller || this.container;
        const h = scroller.clientHeight;
        if (this.lineHeight > 0 && h > 0) {
            return Math.max(3, Math.floor(h / this.lineHeight));
        }
        return 24;
    };

    // ------------------- 缓冲操作 -------------------
    TerminalBuffer.prototype._newLine = function () {
        const line = new Array(this.cols);
        for (let i = 0; i < this.cols; i++) line[i] = { ch: ' ', css: '' };
        return line;
    };

    TerminalBuffer.prototype._ensureRows = function (targetRow) {
        while (this.lines.length <= targetRow) {
            this.lines.push(this._newLine());
        }
        // 裁剪滚动缓冲
        const tooMany = this.lines.length - (this.maxScrollback + this._visibleRows());
        if (tooMany > 0) {
            this.lines.splice(0, tooMany);
            this.cursorRow -= tooMany;
            if (this.cursorRow < 0) this.cursorRow = 0;
        }
    };

    TerminalBuffer.prototype._cellCss = function () {
        return this.renderer.buildCss ? this.renderer.buildCss() : '';
    };

    TerminalBuffer.prototype._writeRun = function (text) {
        const css = this._cellCss();
        for (let i = 0; i < text.length; i++) {
            // 行尾自动换行
            if (this.cursorCol >= this.cols) {
                this.cursorCol = 0;
                this.cursorRow++;
                this._ensureRows(this.cursorRow);
            }
            this.lines[this.cursorRow][this.cursorCol] = { ch: text[i], css: css };
            this.cursorCol++;
        }
        this._markDirty();
    };

    // ------------------- ANSI 解析与输出 -------------------
    TerminalBuffer.prototype.handleOutput = function (text) {
        if (text == null) return;
        text = String(text);
        for (let i = 0; i < text.length; i++) {
            const ch = text[i];
            if (ch === '\n') {
                this.cursorRow++;
                this._ensureRows(this.cursorRow);
                this._markDirty();
            } else if (ch === '\r') {
                this.cursorCol = 0;
                this._markDirty();
            } else if (ch === '\b') {
                if (this.cursorCol > 0) this.cursorCol--;
            } else if (ch === '\t') {
                this.cursorCol = Math.min(this.cols - 1, this.cursorCol - (this.cursorCol % 8) + 8);
                this._markDirty();
            } else if (ch === '\x07' || ch === '\x00') {
                // 铃响 / 空字符：忽略
            } else if (ch === '\x1b') {
                i = this._parseEscape(text, i);
            } else {
                this._writeRun(ch);
            }
        }
        this._scheduleRender();
    };

    TerminalBuffer.prototype._parseEscape = function (text, start) {
        let i = start + 1;
        if (i >= text.length) return text.length - 1;

        const c = text[i];

        // OSC：ESC ] ... BEL / ESC \
        if (c === ']') {
            i++;
            while (i < text.length) {
                if (text[i] === '\x07') { i++; break; }
                if (text[i] === '\x1b' && i + 1 < text.length && text[i + 1] === '\\') { i += 2; break; }
                i++;
            }
            return i - 1;
        }

        // CSI：ESC [ params intermediate final
        if (c === '[') {
            i++;
            let paramStr = '';
            let privateMark = '';
            // 首字符可能是私有标记（? > = !）
            if (i < text.length && (text[i] === '?' || text[i] === '>' || text[i] === '=' || text[i] === '!')) {
                privateMark = text[i];
                i++;
            }
            while (i < text.length) {
                const code = text.charCodeAt(i);
                if (code >= 0x40 && code <= 0x7e) {
                    const finalByte = text[i];
                    i++;
                    const params = paramStr ? paramStr.split(';').map(p => parseInt(p, 10) || 0) : [];
                    this._dispatchCsi(finalByte, params, privateMark);
                    return i - 1;
                }
                if (code >= 0x20 && code <= 0x3f) {
                    paramStr += text[i];
                    i++;
                    continue;
                }
                break;
            }
            return i - 1;
        }

        // 其它 ESC 引入的单字节控制序列
        if (c === '7') this._saveCursor();        // 保存光标
        else if (c === '8') this._restoreCursor(); // 恢复光标
        // 其余忽略但不中断
        return i;
    };

    TerminalBuffer.prototype._dispatchCsi = function (finalByte, params, privateMark) {
        const n0 = params.length ? params[0] : 0;
        const n = n0 || 1;
        switch (finalByte) {
            case 'm': // SGR
                this.renderer.applySgr(params.length ? params : [0]);
                this._markDirty();
                break;
            case 'A': this.cursorRow = Math.max(0, this.cursorRow - n); this._markDirty(); break; // 上
            case 'B': this.cursorRow += n; this._ensureRows(this.cursorRow); this._markDirty(); break; // 下
            case 'C': this.cursorCol = Math.min(this.cols - 1, this.cursorCol + n); this._markDirty(); break; // 右
            case 'D': this.cursorCol = Math.max(0, this.cursorCol - n); this._markDirty(); break; // 左
            case 'E': this.cursorRow += n; this.cursorCol = 0; this._ensureRows(this.cursorRow); this._markDirty(); break;
            case 'F': this.cursorRow = Math.max(0, this.cursorRow - n); this.cursorCol = 0; this._markDirty(); break;
            case 'G': case '`': this.cursorCol = Math.max(0, Math.min(this.cols - 1, n0 - 1)); this._markDirty(); break; // 列
            case 'd': this.cursorRow = Math.max(0, n0 - 1); this._ensureRows(this.cursorRow); this._markDirty(); break; // 行
            case 'H': case 'f': { // 光标定位 (row;col, 1-based)
                const r = params.length ? (params[0] || 1) : 1;
                const cc = params.length > 1 ? (params[1] || 1) : 1;
                this.cursorRow = Math.max(0, r - 1);
                this.cursorCol = Math.max(0, Math.min(this.cols - 1, cc - 1));
                this._ensureRows(this.cursorRow);
                this._markDirty();
                break;
            }
            case 'J': this._eraseDisplay(params.length ? n0 : 0); break;    // 清屏
            case 'K': this._eraseLine(params.length ? n0 : 0); break;       // 清行
            case 's': this._saveCursor(); break;                            // 保存光标(私有)
            case 'u': this._restoreCursor(); break;                         // 恢复光标
            // 其余控制序列（开关模式、滚动区域、插入删除字符等）暂不支持，安全忽略
        }
    };

    TerminalBuffer.prototype._saveCursor = function () {
        this._savedRow = this.cursorRow;
        this._savedCol = this.cursorCol;
    };

    TerminalBuffer.prototype._restoreCursor = function () {
        if (this._savedRow === undefined) return;
        this.cursorRow = this._savedRow;
        this.cursorCol = this._savedCol;
        this._ensureRows(this.cursorRow);
        this._markDirty();
    };

    TerminalBuffer.prototype._fillLineCells = function (line, from, to, css) {
        for (let i = from; i < to && i < this.cols; i++) {
            line[i] = { ch: ' ', css: css };
        }
    };

    TerminalBuffer.prototype._eraseLine = function (mode) {
        const css = this._cellCss();
        const line = this.lines[this.cursorRow];
        if (!line) return;
        if (mode === 0) this._fillLineCells(line, this.cursorCol, this.cols, css);
        else if (mode === 1) this._fillLineCells(line, 0, this.cursorCol, css);
        else this._fillLineCells(line, 0, this.cols, css);
        this._markDirty();
    };

    TerminalBuffer.prototype._eraseDisplay = function (mode) {
        const css = this._cellCss();
        const rows = this._visibleRows();
        const viewStart = Math.max(0, this.lines.length - rows);

        if (mode === 3) {
            // 清空滚动缓冲：只保留当前行及可见区域
            const keepFrom = Math.max(0, this.cursorRow);
            this.lines = this.lines.slice(keepFrom);
            this.cursorRow = 0;
            this.cursorCol = 0;
            this._ensureRows(0);
            this._markDirty();
            return;
        }
        if (mode === 2) {
            for (let r = viewStart; r < this.lines.length; r++) {
                this._fillLineCells(this.lines[r], 0, this.cols, css);
            }
        } else if (mode === 0) {
            // 从光标到屏幕(可视区)末尾
            this._fillLineCells(this.lines[this.cursorRow], this.cursorCol, this.cols, css);
            for (let r = this.cursorRow + 1; r < this.lines.length; r++) {
                this._fillLineCells(this.lines[r], 0, this.cols, css);
            }
        } else if (mode === 1) {
            for (let r = viewStart; r < this.cursorRow; r++) {
                this._fillLineCells(this.lines[r], 0, this.cols, css);
            }
            this._fillLineCells(this.lines[this.cursorRow], 0, this.cursorCol, css);
        }
        this._markDirty();
    };

    // ------------------- 渲染 -------------------
    TerminalBuffer.prototype._markDirty = function () {
        this._dirty = true;
    };

    TerminalBuffer.prototype._scheduleRender = function () {
        const self = this;
        if (this._rafPending) return;
        this._rafPending = true;
        requestAnimationFrame(function () {
            self._rafPending = false;
            self._render();
        });
    };

    TerminalBuffer.prototype._renderLine = function (line) {
        // 求最后一个非空单元格，跳过行尾空白
        let last = -1;
        for (let i = 0; i < this.cols; i++) {
            if (line[i].ch !== ' ') last = i;
        }
        if (last < 0) return '';
        let html = '';
        let curCss = null;
        let buf = '';
        const flush = function () {
            if (!buf) return;
            if (curCss) {
                html += '<span style="' + curCss + '">';
            }
            html += buf.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            if (curCss) html += '</span>';
            buf = '';
        };
        for (let i = 0; i <= last; i++) {
            const cell = line[i];
            if (cell.css !== curCss) { flush(); curCss = cell.css; }
            buf += cell.ch;
        }
        flush();
        return html;
    };

    TerminalBuffer.prototype._getLineEl = function (index) {
        if (this._lineEls[index]) {
            this._lineEls[index].style.display = '';
            return this._lineEls[index];
        }
        const el = document.createElement('div');
        el.style.cssText = 'padding:0;white-space:pre;overflow:hidden;min-height:1.2em;line-height:1.4;';
        this.viewport.appendChild(el);
        this._lineEls[index] = el;
        return el;
    };

    TerminalBuffer.prototype._render = function () {
        if (!this._dirty) return;
        this._dirty = false;

        const rows = this._visibleRows();
        const total = this.lines.length;
        let first = total - rows;
        if (first < 0) first = 0;

        // 缩放缓冲，保证 viewport 恰好容纳 rows 行
        while (this._lineEls.length < rows) this._getLineEl(this._lineEls.length);
        for (let i = rows; i < this._lineEls.length; i++) {
            this._lineEls[i].style.display = 'none';
        }

        for (let i = 0; i < rows; i++) {
            const src = first + i;
            const line = src < total ? this.lines[src] : this._newLine();
            const el = this._lineEls[i];
            const html = this._renderLine(line);
            if (el.innerHTML !== html) el.innerHTML = html;
        }

        // 滚动缓冲高度 = 可视区域上方的历史行数
        this.spacer.style.height = (first * this.lineHeight) + 'px';
        this.viewport.style.height = (rows * this.lineHeight) + 'px';

        if (this.autoScroll && this.scroller) {
            this.scroller.scrollTop = this.scroller.scrollHeight;
        }
    };

    TerminalBuffer.prototype._bindScroll = function () {
        const scroller = this.scroller;
        if (!scroller) return;
        const self = this;
        scroller.addEventListener('scroll', function () {
            const dist = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
            self.autoScroll = dist < 30;
        });
        const onResize = function () { self._reflow(); };
        this._boundResize = onResize;
        window.addEventListener('resize', onResize);
    };

    TerminalBuffer.prototype._reflow = function () {
        this._markDirty();
        this._render();
        if (this.autoScroll && this.scroller) {
            this.scroller.scrollTop = this.scroller.scrollHeight;
        }
    };

    TerminalBuffer.prototype.appendLine = function (text, type) {
        // 追加一行到缓冲末尾，颜色随类型而定；用于运行标记 / 系统提示等
        const colorMap = {
            'info': '#60a5fa', 'error': '#f87171', 'warning': '#fbbf24',
            'success': '#4ade80', 'dim': '#64748b', 'script': '#a3e635',
            'input': '#fbbf24',
        };
        const color = colorMap[type] || '#e2e8f0';

        // 换到新的一行
        this.cursorRow++;
        this._ensureRows(this.cursorRow);
        this.cursorCol = 0;
        this.renderer.reset();

        const str = String(text);
        for (let i = 0; i < str.length; i++) {
            if (this.cursorCol >= this.cols) {
                this.cursorRow++;
                this._ensureRows(this.cursorRow);
                this.cursorCol = 0;
            }
            this.lines[this.cursorRow][this.cursorCol] = { ch: str[i], css: 'color:' + color };
            this.cursorCol++;
        }
        this._markDirty();
        this._render();
    };

    TerminalBuffer.prototype.clear = function (keepCurrentLine) {
        this.lines = [];
        this.cursorRow = 0;
        this.cursorCol = 0;
        this.renderer.reset();
        if (keepCurrentLine !== false) {
            this._ensureRows(0);
        }
        this._markDirty();
        this._render();
    };

    TerminalBuffer.prototype.scrollToBottom = function () {
        this.autoScroll = true;
        if (this.scroller) this.scroller.scrollTop = this.scroller.scrollHeight;
    };

    // 返回终端当前几何信息（行/列），供同步 PTY 窗口尺寸使用
    TerminalBuffer.prototype.getGeometry = function () {
        const rows = this._visibleRows();
        const w = this.container ? this.container.clientWidth : 0;
        const charWidth = Math.max(6, this.lineHeight * 0.6);
        const cols = w > 100 ? Math.max(2, Math.floor(w / charWidth)) : this.cols;
        return { rows: rows, cols: cols };
    };

    TerminalBuffer.prototype.destroy = function () {
        if (this._boundResize) {
            window.removeEventListener('resize', this._boundResize);
            this._boundResize = null;
        }
        this._lineEls = [];
        if (this.inner && this.inner.parentNode === this.container) {
            this.container.removeChild(this.inner);
        }
    };

    // ==================================================================
    // SseTerminal：基于 EventSource 的终端连接管理
    // ==================================================================
    function SseTerminal(options) {
        this.url = options.url || '/admin/script/terminal/stream';
        this.inputUrl = options.inputUrl || '/admin/script/terminal/input';
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
