/**
 * terminal-xterm.js — 基于 xterm.js 的实时终端（弹窗 / 独立页共用）
 *
 * 用途：
 *   - 用业界标准的 xterm.js 渲染字符网格，彻底替代旧的自制 ANSI 渲染器，
 *     保证回车执行、光标、清屏、换行排版在浏览器中与实际终端一致。
 *   - 输入走 `term.onData`（字节级精确，回车发送 \r），由后端 PTY 真伪终端
 *     的驱动回显与执行，天然修复“只输入不执行”。
 *   - 输出走 SSE 实时回流写入 `term.write`。
 *   - 自适应尺寸：容器尺寸变化时调用 fit 并回传后端 /resize，保证 PTY 行
 *     宽与渲染一致，杜绝换行错位。
 *
 * 依赖：
 *   - xterm.min.js（window.Terminal）
 *   - xterm-addon-fit.min.js（window.FitAddon.FitAddon）
 *   - xterm.min.css（页面上以 <link> 引入）
 *
 * 暴露：window.TerminalXterm.attach(container, opts) -> controller
 */
window.TerminalXterm = (function () {
    'use strict';

    var STREAM_URL = '/admin/script/terminal/stream';
    var INPUT_URL = '/admin/script/terminal/input';
    var RESIZE_URL = '/admin/script/terminal/resize';
    var RESET_URL = '/admin/script/terminal/reset';

    function postJson(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).catch(function () { /* 网络错误静默，等待重连 */ });
    }

    function attach(container, opts) {
        opts = opts || {};

        var term = new Terminal({
            cursorBlink: true,
            fontSize: 13,
            lineHeight: 1.15,
            fontFamily: "'JetBrains Mono', Menlo, Consolas, 'Courier New', monospace",
            fontWeight: 'normal',
            scrollback: 3000,
            allowProposedApi: true,
            theme: {
                background: '#0b0f14',
                foreground: '#c8d3d5',
                cursor: '#4ade80',
                cursorAccent: '#0b0f14',
                selectionBackground: 'rgba(244,208,63,0.25)',
                black: '#000000', red: '#f87171', green: '#4ade80', yellow: '#f4d03f',
                blue: '#60a5fa', magenta: '#c084fc', cyan: '#55c6c6', white: '#c8d3d5',
                brightBlack: '#64748b', brightRed: '#f87171', brightGreen: '#4ade80',
                brightYellow: '#f4d03f', brightBlue: '#60a5fa', brightMagenta: '#c084fc',
                brightCyan: '#55c6c6', brightWhite: '#ffffff',
            },
        });

        var fitAddon = null;
        try {
            if (window.FitAddon && window.FitAddon.FitAddon && typeof term.loadAddon === 'function') {
                fitAddon = new window.FitAddon.FitAddon();
                term.loadAddon(fitAddon);
            }
        } catch (_) { fitAddon = null; }

        term.open(container);

        var onConnected = opts.onConnected || function () {};
        var onDisconnected = opts.onDisconnected || function () {};
        var connected = false;
        var closed = false;   // dispose 后禁止重连

        // ---- SSE 实时输出流 ----
        var es = null;
        var reconnectTimer = null;
        var manualClose = false;

        function connect() {
            if (closed) return;
            if (es) return;
            manualClose = false;
            es = new EventSource(STREAM_URL, { withCredentials: true });
            es.onopen = function () {
                connected = true;
                if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
                onConnected();
            };
            es.onmessage = function (e) {
                var m;
                try { m = JSON.parse(e.data); } catch (_) { return; }
                handleSse(m);
            };
            es.onerror = function () {
                tearDownSse();
                onDisconnected();
                if (manualClose) return;
                scheduleReconnect();
            };
        }

        function tearDownSse() {
            if (es) {
                try { es.close(); } catch (_) {}
                es = null;
            }
            connected = false;
        }

        function scheduleReconnect() {
            if (closed) return;
            if (reconnectTimer) return;
            reconnectTimer = setTimeout(function () {
                reconnectTimer = null;
                connect();
            }, 2500);
        }

        function handleSse(m) {
            if (!m || !m.type) return;
            var d = m.data || {};
            switch (m.type) {
                case 'output':
                    term.write(d.text || '');
                    break;
                case 'closed':
                    // shell 退出；稍后 EventSource 会触发 onerror，由其重连
                    break;
                case 'error':
                    term.write('\r\n\x1b[31m[终端错误] ' + (d.message || '') + '\x1b[0m\r\n');
                    break;
                case 'connected':
                case 'heartbeat':
                    break;
            }
        }

        // ---- 输入：把用户按键原样交给 PTY 驱动 ----
        term.onData(function (data) {
            if (!data) return;
            postJson(INPUT_URL, { text: data });
        });

        // 仅在后端可接受的尺寸变化（>=2x2）时回传 resize，避免初始零尺寸
        // 容器触发 400，也避免在终端尚未可见时同步错误行宽。
        var lastSent = null;
        term.onResize(function (geo) {
            var cols = Math.floor(geo.cols);
            var rows = Math.floor(geo.rows);
            if (!isFinite(cols) || !isFinite(rows) || cols < 2 || rows < 2) return;
            if (lastSent && lastSent.cols === cols && lastSent.rows === rows) return;
            lastSent = { cols: cols, rows: rows };
            postJson(RESIZE_URL, { cols: cols, rows: rows });
        });

        function fit() {
            if (!fitAddon) return;
            try {
                fitAddon.fit();
            } catch (_) { /* 容器尚不可见时失败可忽略 */ }
        }

        var ro = null;
        if (typeof ResizeObserver !== 'undefined') {
            ro = new ResizeObserver(function () { fit(); });
            ro.observe(container);
        }
        // 首次 fit，先延迟到布局完成
        setTimeout(fit, 120);
        setTimeout(fit, 400);

        // ------------------------------------------------------------
        return {
            term: term,
            connect: connect,
            isConnected: function () { return connected; },
            send: function (text) { if (text) postJson(INPUT_URL, { text: text }); },
            write: function (text) { term.write(text || ''); },
            insert: function (text) { term.paste(text || ''); },
            focus: function () { term.focus(); },
            clear: function () { term.clear(); },
            reset: function () {
                postJson(RESET_URL, {}).then(function () {
                    // 服务端重启 shell；旧 SSE 结束触发重连拿到新会话输出
                });
            },
            fit: fit,
            dispose: function () {
                closed = true;
                manualClose = true;
                if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
                tearDownSse();
                if (ro) { ro.disconnect(); ro = null; }
                try { term.dispose(); } catch (_) {}
            },
        };
    }

    return { attach: attach };
})();