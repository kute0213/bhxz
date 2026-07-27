/**
 * editor-terminal.js — 持久终端面板
 *
 * 功能：
 *   - 持久 shell 会话（cd 等状态保持）
 *   - ANSI 16色/256色/真彩色 渲染支持
 *   - 命令历史记录（↑/↓ 切换）
 *   - SSE 流式输出 + POST 输入
 *   - 快捷键：Ctrl+L 清屏、Ctrl+C 中断、Enter 执行
 *   - 终端重置（重启 shell）
 *   - 待发送队列：连接建立前的命令自动排队
 *
 * 暴露：window.TerminalPanel
 */
window.TerminalPanel = (function () {

    let cmdHistory = [];
    let historyIndex = -1;
    let draftValue = '';

    let eventSource = null;
    let connected = false;
    let reconnectTimer = null;
    let manualCloseToken = 0;
    let pendingInputQueue = [];
    const RECONNECT_DELAY = 3000;

    let lastDataTime = Date.now();
    let watchdogTimer = null;
    const WATCHDOG_TIMEOUT = 35000;
    const WATCHDOG_CHECK_INTERVAL = 5000;

    // ANSI 状态
    let currentLineFragments = [];
    let ansiStyle = {
        bold: false, dim: false, italic: false, underline: false,
        blink: false, reverse: false, hidden: false, strikethrough: false,
        fg: null, bg: null,
    };
    let pendingCr = false;

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

    function resetAnsiStyle() {
        ansiStyle = {
            bold: false, dim: false, italic: false, underline: false,
            blink: false, reverse: false, hidden: false, strikethrough: false,
            fg: null, bg: null,
        };
    }

    function applyAnsiSgr(params) {
        if (!params || params.length === 0) { resetAnsiStyle(); return; }
        let i = 0;
        while (i < params.length) {
            const p = params[i];
            if (p === 0) resetAnsiStyle();
            else if (p === 1) ansiStyle.bold = true;
            else if (p === 2) ansiStyle.dim = true;
            else if (p === 3) ansiStyle.italic = true;
            else if (p === 4) ansiStyle.underline = true;
            else if (p === 5) ansiStyle.blink = true;
            else if (p === 7) ansiStyle.reverse = true;
            else if (p === 8) ansiStyle.hidden = true;
            else if (p === 9) ansiStyle.strikethrough = true;
            else if (p === 22) { ansiStyle.bold = false; ansiStyle.dim = false; }
            else if (p === 23) ansiStyle.italic = false;
            else if (p === 24) ansiStyle.underline = false;
            else if (p === 25) ansiStyle.blink = false;
            else if (p === 27) ansiStyle.reverse = false;
            else if (p === 28) ansiStyle.hidden = false;
            else if (p === 29) ansiStyle.strikethrough = false;
            else if (p >= 30 && p <= 37) ansiStyle.fg = ANSI_COLORS[p - 30];
            else if (p >= 40 && p <= 47) ansiStyle.bg = ANSI_COLORS[p - 40];
            else if (p >= 90 && p <= 97) ansiStyle.fg = ANSI_COLORS[p - 90 + 8];
            else if (p >= 100 && p <= 107) ansiStyle.bg = ANSI_COLORS[p - 100 + 8];
            else if (p === 39) ansiStyle.fg = null;
            else if (p === 49) ansiStyle.bg = null;
            else if (p === 38 && i + 1 < params.length) {
                const mode = params[i + 1];
                if (mode === 5 && i + 2 < params.length) { ansiStyle.fg = ansi256ToHex(params[i + 2]); i += 2; }
                else if (mode === 2 && i + 4 < params.length) { ansiStyle.fg = `rgb(${params[i+2]},${params[i+3]},${params[i+4]})`; i += 4; }
            } else if (p === 48 && i + 1 < params.length) {
                const mode = params[i + 1];
                if (mode === 5 && i + 2 < params.length) { ansiStyle.bg = ansi256ToHex(params[i + 2]); i += 2; }
                else if (mode === 2 && i + 4 < params.length) { ansiStyle.bg = `rgb(${params[i+2]},${params[i+3]},${params[i+4]})`; i += 4; }
            }
            i++;
        }
    }

    function buildStyleCss() {
        const parts = [];
        let fg = ansiStyle.fg, bg = ansiStyle.bg;
        if (ansiStyle.reverse) { [fg, bg] = [bg, fg]; if (!fg) fg = '#e2e8f0'; if (!bg) bg = '#000000'; }
        parts.push('color:' + (fg || '#e2e8f0'));
        if (bg) parts.push('background-color:' + bg);
        if (ansiStyle.bold) parts.push('font-weight:700');
        if (ansiStyle.dim) parts.push('opacity:0.6');
        if (ansiStyle.italic) parts.push('font-style:italic');
        if (ansiStyle.underline) parts.push('text-decoration:underline');
        if (ansiStyle.blink) parts.push('animation:term-blink 1s steps(2) infinite');
        if (ansiStyle.hidden) parts.push('visibility:hidden');
        if (ansiStyle.strikethrough) parts.push('text-decoration:line-through');
        return parts.join(';');
    }

    function pushTextFragment(text) {
        if (!text) return;
        const css = buildStyleCss();
        const last = currentLineFragments[currentLineFragments.length - 1];
        if (last && last.css === css) { last.text += text; }
        else { currentLineFragments.push({ text, css }); }
    }

    function flushCurrentLine(panel) {
        if (currentLineFragments.length === 0) return;
        const line = document.createElement('div');
        line.style.cssText = 'padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;line-height:1.4;';
        for (const frag of currentLineFragments) {
            const span = document.createElement('span');
            span.style.cssText = frag.css;
            span.textContent = frag.text;
            line.appendChild(span);
        }
        panel.appendChild(line);
        currentLineFragments = [];
    }

    function getCurrentLineElement(panel) {
        let line = panel.querySelector('.term-current-line');
        if (!line) {
            line = document.createElement('div');
            line.className = 'term-current-line';
            line.style.cssText = 'padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;line-height:1.4;';
            panel.appendChild(line);
        }
        return line;
    }

    function renderCurrentLine(panel) {
        const line = getCurrentLineElement(panel);
        line.innerHTML = '';
        for (const frag of currentLineFragments) {
            const span = document.createElement('span');
            span.style.cssText = frag.css;
            span.textContent = frag.text;
            line.appendChild(span);
        }
    }

    function ensureBlinkStyle() {
        if (!document.getElementById('term-blink-style')) {
            const style = document.createElement('style');
            style.id = 'term-blink-style';
            style.textContent = '@keyframes term-blink{0%,50%{opacity:1}50.01%,100%{opacity:0}}';
            document.head.appendChild(style);
        }
    }

    // ============================================================
    // 初始化
    // ============================================================
    function init() {
        ensureBlinkStyle();
        const input = document.getElementById('terminal-input');
        if (!input) return;

        input.addEventListener('keydown', onInputKeydown);
        loadHistory();
        connectStream();

        const wrapper = document.getElementById('editor-output-wrapper');
        if (wrapper) {
            wrapper.addEventListener('click', function () { focusInput(); });
        }

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            if (connected && eventSource) return;
            if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
            connectStream();
        });
    }

    // ============================================================
    // SSE 连接
    // ============================================================
    function connectStream() {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }

        const panel = document.getElementById('output-panel');
        if (panel && panel.classList.contains('collapsed')) return;

        const closedToken = ++manualCloseToken;
        if (eventSource) { try { eventSource.close(); } catch (_) {} eventSource = null; }

        connected = false;
        lastDataTime = Date.now();
        appendLine('正在连接终端…', 'dim');

        const es = new EventSource('/admin/cmd/terminal/stream', { withCredentials: true });

        es.onopen = function () {
            connected = true;
            lastDataTime = Date.now();
            if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
            startWatchdog();
            flushPendingQueue();
        };

        es.onmessage = function (e) {
            let msg;
            try { msg = JSON.parse(e.data); } catch (_) { return; }
            lastDataTime = Date.now();
            handleSseEvent(msg);
        };

        es.onerror = function () {
            const myToken = closedToken;
            if (connected) { appendLine('[连接断开，正在重连…]', 'warning'); connected = false; }
            try { es.close(); } catch (_) {}
            if (eventSource === es) { eventSource = null; }
            if (myToken !== manualCloseToken) return;
            scheduleReconnect();
        };

        eventSource = es;
    }

    function flushPendingQueue() {
        while (pendingInputQueue.length > 0 && connected) {
            const text = pendingInputQueue.shift();
            sendTextNow(text);
        }
    }

    function startWatchdog() {
        stopWatchdog();
        watchdogTimer = setInterval(function () {
            if (!isPanelVisible()) return;
            if (!connected) return;
            const elapsed = Date.now() - lastDataTime;
            if (elapsed > WATCHDOG_TIMEOUT) {
                appendLine('[长时间无心跳，主动重连…]', 'warning');
                if (eventSource) { try { eventSource.close(); } catch (_) {} eventSource = null; }
                connected = false;
                scheduleReconnect();
            }
        }, WATCHDOG_CHECK_INTERVAL);
    }

    function stopWatchdog() {
        if (watchdogTimer) { clearInterval(watchdogTimer); watchdogTimer = null; }
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        if (!isPanelVisible()) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            if (!isPanelVisible()) return;
            connectStream();
        }, RECONNECT_DELAY);
    }

    function isPanelVisible() {
        const panel = document.getElementById('output-panel');
        if (!panel) return false;
        return !panel.classList.contains('collapsed');
    }

    function reconnect() {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        if (connected && eventSource) return;
        if (!isPanelVisible()) return;
        connectStream();
    }

    function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};
        switch (msg.type) {
            case 'connected':
                clearLastLineIf('正在连接终端…');
                break;
            case 'output':
                handleTerminalOutput(data.text || '');
                break;
            case 'heartbeat':
                break;
            case 'closed':
                appendLine('[会话已结束，正在重连…]', 'warning');
                connected = false;
                if (eventSource) { try { eventSource.close(); } catch (_) {} eventSource = null; }
                ++manualCloseToken;
                scheduleReconnect();
                break;
            case 'error':
                appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
        }
    }

    // ============================================================
    // 终端输出处理
    // ============================================================
    function handleTerminalOutput(text) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;

        let i = 0;
        while (i < text.length) {
            const ch = text[i];
            if (ch === '\n') {
                const cl = panel.querySelector('.term-current-line');
                if (cl) cl.classList.remove('term-current-line');
                flushCurrentLine(panel);
                currentLineFragments = [];
                pendingCr = false;
                pushTextFragment('');
                renderCurrentLine(panel);
                i++;
            } else if (ch === '\r') {
                pendingCr = true;
                i++;
            } else if (ch === '\x1b') {
                const result = parseAnsiEscape(text, i);
                i = result.next;
                if (result.sgr) { applyAnsiSgr(result.params); renderCurrentLine(panel); }
            } else if (ch === '\x08') {
                if (pendingCr) pendingCr = false;
                if (currentLineFragments.length > 0) {
                    const last = currentLineFragments[currentLineFragments.length - 1];
                    if (last.text.length > 0) { last.text = last.text.slice(0, -1); }
                    else if (currentLineFragments.length > 1) { currentLineFragments.pop(); }
                    renderCurrentLine(panel);
                }
                i++;
            } else if (ch === '\x07') { i++; }
            else if (ch === '\x0c') { clearTerminalNoSend(); pendingCr = false; i++; }
            else {
                if (pendingCr) { currentLineFragments = []; pendingCr = false; }
                pushTextFragment(ch); renderCurrentLine(panel); i++;
            }
        }
        scrollToBottom();
    }

    function parseAnsiEscape(text, start) {
        let i = start + 1;
        if (i >= text.length) return { next: i };
        if (text[i] === '[') {
            i++;
            let paramStr = '';
            while (i < text.length) {
                const code = text.charCodeAt(i);
                if (code >= 0x40 && code <= 0x7e) {
                    const fb = text[i]; i++;
                    if (fb === 'm') {
                        const params = paramStr ? paramStr.split(';').map(s => parseInt(s, 10) || 0) : [0];
                        return { next: i, sgr: true, params };
                    }
                    return { next: i };
                }
                if (code >= 0x20 && code <= 0x3f) { paramStr += text[i]; i++; continue; }
                break;
            }
            return { next: i };
        } else if (text[i] === ']') {
            i++;
            while (i < text.length) {
                if (text[i] === '\x07') { i++; break; }
                if (text[i] === '\x1b' && i + 1 < text.length && text[i+1] === '\\') { i += 2; break; }
                i++;
            }
            return { next: i };
        } else { return { next: i + 1 }; }
    }

    function clearLastLineIf(text) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;
        const last = panel.lastElementChild;
        if (last && last.textContent.trim() === text.trim()) { last.remove(); }
    }

    // ============================================================
    // 输入处理
    // ============================================================
    function onInputKeydown(e) {
        const input = e.target;
        if (e.key === 'Enter') {
            e.preventDefault();
            const cmd = input.value;
            addToHistory(cmd);
            sendCommand(cmd);
            input.value = '';
            historyIndex = -1;
            return;
        }
        if (e.key === 'ArrowUp') { e.preventDefault(); navigateHistory(-1, input); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); navigateHistory(1, input); return; }
        if (e.key === 'l' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); clearTerminal(); return; }
        if (e.key === 'c' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendInterrupt(); return; }
        if (e.key === 'Tab') { e.preventDefault(); sendText('\t'); return; }
    }

    function sendCommand(cmd) { sendText(cmd + '\n'); }

    function sendText(text) {
        if (!connected) {
            pendingInputQueue.push(text);
            if (!eventSource && isPanelVisible()) { connectStream(); }
            return;
        }
        sendTextNow(text);
    }

    function sendTextNow(text) {
        fetch('/admin/cmd/terminal/input', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text }),
        }).catch(function (err) {
            appendLine('[发送失败] ' + err.message, 'error');
        });
    }

    function sendInterrupt() { sendText('\x03'); }

    function addToHistory(cmd) {
        if (!cmd.trim()) return;
        if (cmdHistory[cmdHistory.length - 1] === cmd) return;
        cmdHistory.push(cmd);
        if (cmdHistory.length > 200) cmdHistory.shift();
        saveHistory();
    }

    function navigateHistory(dir, input) {
        if (cmdHistory.length === 0) return;
        if (historyIndex === -1) draftValue = input.value;
        if (dir < 0) {
            if (historyIndex === -1) historyIndex = cmdHistory.length - 1;
            else if (historyIndex > 0) historyIndex--;
        } else {
            if (historyIndex < cmdHistory.length - 1) historyIndex++;
            else { historyIndex = -1; input.value = draftValue; return; }
        }
        if (historyIndex >= 0 && historyIndex < cmdHistory.length) {
            input.value = cmdHistory[historyIndex];
            setTimeout(() => { input.selectionStart = input.selectionEnd = input.value.length; }, 0);
        }
    }

    function saveHistory() { try { localStorage.setItem('terminal_history', JSON.stringify(cmdHistory)); } catch (_) {} }
    function loadHistory() { try { const raw = localStorage.getItem('terminal_history'); if (raw) cmdHistory = JSON.parse(raw) || []; } catch (_) { cmdHistory = []; } }

    // ============================================================
    // 输出辅助
    // ============================================================
    function appendLine(text, type) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;
        const current = panel.querySelector('.term-current-line');
        if (current) current.classList.remove('term-current-line');
        flushCurrentLine(panel);

        const line = document.createElement('div');
        const colorMap = {
            'info': '#60a5fa', 'error': '#f87171', 'warning': '#fbbf24',
            'success': '#4ade80', 'dim': '#64748b', 'script': '#a3e635',
        };
        line.style.cssText = 'color:' + (colorMap[type] || '#e2e8f0') + ';padding:1px 0;white-space:pre-wrap;word-break:break-all;';
        line.textContent = text;
        panel.appendChild(line);

        currentLineFragments = [];
        resetAnsiStyle();
        pushTextFragment('');
        renderCurrentLine(panel);
        scrollToBottom();
    }

    function appendCommandLine(cmd) { appendLine('$ ' + cmd, 'info'); }
    function appendOutput(text) { handleTerminalOutput(text + '\n'); }

    function clearTerminalNoSend() {
        const panel = document.getElementById('editor-output');
        if (panel) panel.innerHTML = '';
        currentLineFragments = [];
        pendingCr = false;
        resetAnsiStyle();
        pushTextFragment('');
        renderCurrentLine(panel);
    }

    function clearTerminal() {
        clearTerminalNoSend();
        if (connected) { sendText('\x0c'); }
    }

    function scrollToBottom() {
        const wrapper = document.getElementById('editor-output-wrapper');
        if (wrapper) wrapper.scrollTop = wrapper.scrollHeight;
    }

    function focusInput() {
        const input = document.getElementById('terminal-input');
        if (input) input.focus();
    }

    function getRunning() { return connected; }

    return {
        init: init,
        sendCommand: sendCommand,
        appendCommandLine: appendCommandLine,
        appendOutput: appendOutput,
        appendLine: appendLine,
        clear: clearTerminal,
        focus: focusInput,
        getRunning: getRunning,
        reconnect: reconnect,
        isPanelVisible: isPanelVisible,
    };
})();
