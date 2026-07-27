/**
 * CMD 终端弹窗模块（持久 shell 版）
 *
 * 功能：
 *   - 磨砂玻璃风格弹窗，与页面设计统一
 *   - 淡入淡出 + 缩放动画
 *   - 标题栏拖拽移动
 *   - 持久 shell 会话（cd 等状态保持），SSE 流式输出
 *   - ANSI 16色/256色/真彩色 渲染支持
 *   - 命令历史（↑↓，持久化到 localStorage）
 *   - 终端自动滚动 / 手动滚动锁定
 *   - 运行状态指示灯
 *   - 快捷键：Ctrl+L 清屏、Ctrl+C 中断、Enter 执行、Tab 补全
 *   - 断线自动重连（延迟 3 秒）
 *   - 页面可见性监听：切回页面时主动重连
 *   - 待发送队列：连接建立前的命令自动排队，连接后按序发送
 */

window.CmdTerminal = (function () {
    // ---- DOM 元素 ----
    let modal = null;
    let content = null;
    let output = null;
    let input = null;
    let runBtn = null;
    let clearBtn = null;
    let closeBtn = null;
    let titleBar = null;
    let statusDot = null;
    let statusText = null;
    let abortBtn = null;

    // ---- 终端状态 ----
    let isAutoScroll = true;
    let commandHistory = [];
    let historyIndex = -1;
    let draftValue = '';
    let onCloseCallback = null;
    let scriptRunning = false;

    // ---- 持久 shell SSE 连接 ----
    let eventSource = null;
    let connected = false;
    let reconnectTimer = null;
    let manualCloseToken = 0;
    let pendingInputQueue = [];   // 连接建立前待发送的命令队列
    const RECONNECT_DELAY = 3000;

    // ---- ANSI 颜色解析状态 ----
    let currentLineFragments = [];  // 当前行的带样式片段 [{text, style}]
    // 当前样式栈（由 ANSI SGR 码累积）
    let ansiStyle = {
        bold: false,
        dim: false,
        italic: false,
        underline: false,
        blink: false,
        reverse: false,
        hidden: false,
        strikethrough: false,
        fg: null,
        bg: null,
    };
    let pendingCr = false;  // \r 后为 true：下一个普通字符将从行首开始覆盖

    // ---- 心跳看门狗 ----
    let lastDataTime = Date.now();
    let watchdogTimer = null;
    const WATCHDOG_TIMEOUT = 35000;
    const WATCHDOG_CHECK_INTERVAL = 5000;

    // ---- 拖拽 ----
    let isDragging = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;

    // ============================================================
    // ANSI 颜色映射
    // ============================================================
    const ANSI_COLORS = {
        0: '#000000', 1: '#aa0000', 2: '#00aa00', 3: '#aa5500',
        4: '#0000aa', 5: '#aa00aa', 6: '#00aaaa', 7: '#aaaaaa',
        // 亮色（实际终端可能不同，但这是常见映射）
        8: '#555555', 9: '#ff5555', 10: '#55ff55', 11: '#ffff55',
        12: '#5555ff', 13: '#ff55ff', 14: '#55ffff', 15: '#ffffff',
    };

    function ansi256ToHex(n) {
        n = Math.max(0, Math.min(255, n));
        if (n < 16) return ANSI_COLORS[n];
        if (n >= 232) {
            // 灰度
            const v = Math.round((n - 232) * 255 / 23);
            const hex = v.toString(16).padStart(2, '0');
            return '#' + hex + hex + hex;
        }
        // 216 色调色板 16-231: 16 + 36*r + 6*g + b  r,g,b ∈ [0,5]
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
        if (!params || params.length === 0) {
            resetAnsiStyle();
            return;
        }
        let i = 0;
        while (i < params.length) {
            const p = params[i];
            if (p === 0) {
                resetAnsiStyle();
            } else if (p === 1) { ansiStyle.bold = true; }
            else if (p === 2) { ansiStyle.dim = true; }
            else if (p === 3) { ansiStyle.italic = true; }
            else if (p === 4) { ansiStyle.underline = true; }
            else if (p === 5) { ansiStyle.blink = true; }
            else if (p === 7) { ansiStyle.reverse = true; }
            else if (p === 8) { ansiStyle.hidden = true; }
            else if (p === 9) { ansiStyle.strikethrough = true; }
            else if (p === 22) { ansiStyle.bold = false; ansiStyle.dim = false; }
            else if (p === 23) { ansiStyle.italic = false; }
            else if (p === 24) { ansiStyle.underline = false; }
            else if (p === 25) { ansiStyle.blink = false; }
            else if (p === 27) { ansiStyle.reverse = false; }
            else if (p === 28) { ansiStyle.hidden = false; }
            else if (p === 29) { ansiStyle.strikethrough = false; }
            else if (p >= 30 && p <= 37) { ansiStyle.fg = ANSI_COLORS[p - 30]; }
            else if (p >= 40 && p <= 47) { ansiStyle.bg = ANSI_COLORS[p - 40]; }
            else if (p >= 90 && p <= 97) { ansiStyle.fg = ANSI_COLORS[p - 90 + 8]; }
            else if (p >= 100 && p <= 107) { ansiStyle.bg = ANSI_COLORS[p - 100 + 8]; }
            else if (p === 39) { ansiStyle.fg = null; }
            else if (p === 49) { ansiStyle.bg = null; }
            else if (p === 38 && i + 1 < params.length) {
                // 前景: 38;5;n (256色) 或 38;2;r;g;b (真彩色)
                const mode = params[i + 1];
                if (mode === 5 && i + 2 < params.length) {
                    ansiStyle.fg = ansi256ToHex(params[i + 2]);
                    i += 2;
                } else if (mode === 2 && i + 4 < params.length) {
                    ansiStyle.fg = `rgb(${params[i + 2]},${params[i + 3]},${params[i + 4]})`;
                    i += 4;
                }
            } else if (p === 48 && i + 1 < params.length) {
                const mode = params[i + 1];
                if (mode === 5 && i + 2 < params.length) {
                    ansiStyle.bg = ansi256ToHex(params[i + 2]);
                    i += 2;
                } else if (mode === 2 && i + 4 < params.length) {
                    ansiStyle.bg = `rgb(${params[i + 2]},${params[i + 3]},${params[i + 4]})`;
                    i += 4;
                }
            }
            i++;
        }
    }

    function buildStyleCss() {
        const parts = [];
        let fg = ansiStyle.fg;
        let bg = ansiStyle.bg;

        if (ansiStyle.reverse) {
            [fg, bg] = [bg, fg];
            if (!fg) fg = '#e2e8f0';
            if (!bg) bg = '#000000';
        }

        if (fg) parts.push('color:' + fg);
        else parts.push('color:#e2e8f0');

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
        // 如果最后一个片段样式相同，合并
        const last = currentLineFragments[currentLineFragments.length - 1];
        if (last && last.css === css) {
            last.text += text;
        } else {
            currentLineFragments.push({ text, css });
        }
    }

    function flushCurrentLine() {
        if (currentLineFragments.length === 0) return;
        const line = document.createElement('div');
        line.style.cssText = 'padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;line-height:1.4;';
        for (const frag of currentLineFragments) {
            const span = document.createElement('span');
            span.style.cssText = frag.css;
            span.textContent = frag.text;
            line.appendChild(span);
        }
        output.appendChild(line);
        currentLineFragments = [];
    }

    function getCurrentLineElement() {
        let line = output.querySelector('.term-current-line');
        if (!line) {
            line = document.createElement('div');
            line.className = 'term-current-line';
            line.style.cssText = 'padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;line-height:1.4;';
            output.appendChild(line);
        }
        return line;
    }

    function renderCurrentLine() {
        const line = getCurrentLineElement();
        line.innerHTML = '';
        for (const frag of currentLineFragments) {
            const span = document.createElement('span');
            span.style.cssText = frag.css;
            span.textContent = frag.text;
            line.appendChild(span);
        }
    }

    function eraseInLine(mode) {
        // CSI n K: Erase in Line
        // 0: 从光标到行尾
        // 1: 从行首到光标
        // 2: 整行
        if (mode === 2 || mode === 0) {
            // 简化处理：清空当前行内容
            currentLineFragments = [];
        }
    }

    // ============================================================
    // 初始化
    // ============================================================
    function init() {
        modal = document.getElementById('terminal-modal');
        content = document.getElementById('terminal-modal-content');
        output = document.getElementById('terminal-output');
        input = document.getElementById('terminal-input');
        runBtn = document.getElementById('terminal-run-btn');
        clearBtn = document.getElementById('terminal-clear-btn');
        closeBtn = document.getElementById('terminal-close-btn');
        titleBar = modal ? modal.querySelector('.terminal-title-bar') : null;
        statusDot = modal ? modal.querySelector('.terminal-status-dot') : null;
        statusText = modal ? modal.querySelector('.terminal-status-text') : null;

        if (!modal) return;

        // 添加闪烁动画样式
        if (!document.getElementById('term-blink-style')) {
            const style = document.createElement('style');
            style.id = 'term-blink-style';
            style.textContent = '@keyframes term-blink{0%,50%{opacity:1}50.01%,100%{opacity:0}}';
            document.head.appendChild(style);
        }

        if (titleBar) {
            abortBtn = document.createElement('button');
            abortBtn.className = 'px-2.5 py-1 bg-red-500/80 text-white text-xs font-bold rounded-lg hover:bg-red-500 transition-colors flex items-center gap-1';
            abortBtn.style.display = 'none';
            abortBtn.innerHTML = '<i data-lucide="square" class="w-3 h-3"></i> 中止';
            abortBtn.addEventListener('click', function () {
                if (typeof window.__abortCmdScript === 'function') {
                    window.__abortCmdScript();
                } else {
                    fetch('/admin/cmd/abort-script', { method: 'POST' }).catch(function () { /* ignore */ });
                }
                scriptRunning = false;
                if (abortBtn) abortBtn.style.display = 'none';
                if (connected) updateStatus('idle'); else updateStatus('error');
            });
            var closeBtnEl = document.getElementById('terminal-close-btn');
            if (closeBtnEl && closeBtnEl.parentNode) {
                closeBtnEl.parentNode.insertBefore(abortBtn, closeBtnEl);
            }
        }

        runBtn.addEventListener('click', () => runCommand(input.value));
        clearBtn.addEventListener('click', clearOutput);
        closeBtn.addEventListener('click', close);

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                close();
            }
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                runCommand(input.value);
                input.value = '';
                historyIndex = -1;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                navigateHistory(-1, input);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                navigateHistory(1, input);
            } else if (e.ctrlKey && e.key === 'l') {
                e.preventDefault();
                clearOutput();
            } else if (e.ctrlKey && e.key === 'c') {
                e.preventDefault();
                sendInterrupt();
            } else if (e.key === 'Tab') {
                e.preventDefault();
                sendText('\t');
            }
        });

        output.addEventListener('scroll', () => {
            const dist = output.scrollHeight - output.scrollTop - output.clientHeight;
            isAutoScroll = dist < 50;
        });

        if (titleBar) {
            titleBar.addEventListener('mousedown', (e) => {
                if (e.target.closest('button')) return;
                isDragging = true;
                const rect = content.getBoundingClientRect();
                dragOffsetX = e.clientX - rect.left;
                dragOffsetY = e.clientY - rect.top;
                content.style.transition = 'none';
            });
            document.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const x = e.clientX - dragOffsetX;
                const y = e.clientY - dragOffsetY;
                const w = content.offsetWidth;
                const h = content.offsetHeight;
                const maxX = window.innerWidth - w - 10;
                const maxY = window.innerHeight - h - 10;
                modal.style.alignItems = 'flex-start';
                content.style.margin = '0';
                content.style.left = Math.max(10, Math.min(x, maxX)) + 'px';
                content.style.top = Math.max(10, Math.min(y, maxY)) + 'px';
                content.style.position = 'fixed';
            });
            document.addEventListener('mouseup', () => {
                if (isDragging) {
                    isDragging = false;
                    content.style.transition = '';
                }
            });
        }

        loadHistory();

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            if (!isOpen()) return;
            if (connected && eventSource) return;
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            connectStream();
        });
    }

    // ============================================================
    // 打开 / 关闭
    // ============================================================
    function open(onClose) {
        if (!modal) init();
        if (!modal) return;

        content.style.position = '';
        content.style.left = '';
        content.style.top = '';
        content.style.margin = '';
        modal.style.alignItems = '';

        modal.classList.remove('hidden');
        content.classList.remove('terminal-fade-out');
        content.classList.remove('terminal-fade-in');
        void content.offsetWidth;
        content.classList.add('terminal-fade-in');

        if (!eventSource) {
            connectStream();
        }

        if (isAutoScroll) output.scrollTop = output.scrollHeight;
        setTimeout(() => input.focus(), 50);
        onCloseCallback = onClose || null;
    }

    function close() {
        disconnectStream();

        content.classList.remove('terminal-fade-in');
        content.classList.add('terminal-fade-out');

        const onAnimEnd = function () {
            content.classList.remove('terminal-fade-out');
            modal.classList.add('hidden');
            content.removeEventListener('animationend', onAnimEnd);
            content.style.position = '';
            content.style.left = '';
            content.style.top = '';
            content.style.margin = '';
            modal.style.alignItems = '';
        };
        content.addEventListener('animationend', onAnimEnd);

        scriptRunning = false;
        if (abortBtn) abortBtn.style.display = 'none';
        if (onCloseCallback) {
            onCloseCallback();
            onCloseCallback = null;
        }
    }

    function isOpen() {
        return modal && !modal.classList.contains('hidden');
    }

    // ============================================================
    // SSE 连接管理
    // ============================================================
    function connectStream() {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }

        const closedToken = ++manualCloseToken;
        if (eventSource) {
            try { eventSource.close(); } catch (_) { /* ignore */ }
            eventSource = null;
        }

        connected = false;
        lastDataTime = Date.now();
        updateStatus('connecting');

        const es = new EventSource('/admin/cmd/terminal/stream', { withCredentials: true });

        es.onopen = function () {
            connected = true;
            lastDataTime = Date.now();
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            startWatchdog();

            // 连接建立后，发送队列中等待的命令
            flushPendingQueue();
        };

        es.onmessage = function (e) {
            let msg;
            try {
                msg = JSON.parse(e.data);
            } catch (_) {
                return;
            }
            lastDataTime = Date.now();
            handleSseEvent(msg);
        };

        es.onerror = function () {
            const myToken = closedToken;
            if (connected) {
                appendLine('[连接断开，正在重连…]', 'warning');
                connected = false;
            }
            try { es.close(); } catch (_) { /* ignore */ }
            if (eventSource === es) {
                eventSource = null;
            }
            updateStatus('error');

            if (myToken !== manualCloseToken) return;

            if (isOpen()) {
                scheduleReconnect();
            }
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
            if (!isOpen()) return;
            if (!connected) return;
            const elapsed = Date.now() - lastDataTime;
            if (elapsed > WATCHDOG_TIMEOUT) {
                appendLine('[长时间无心跳，主动重连…]', 'warning');
                if (eventSource) {
                    try { eventSource.close(); } catch (_) { /* ignore */ }
                    eventSource = null;
                }
                connected = false;
                updateStatus('error');
                scheduleReconnect();
            }
        }, WATCHDOG_CHECK_INTERVAL);
    }

    function stopWatchdog() {
        if (watchdogTimer) {
            clearInterval(watchdogTimer);
            watchdogTimer = null;
        }
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            if (isOpen()) {
                connectStream();
            }
        }, RECONNECT_DELAY);
    }

    function disconnectStream() {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        ++manualCloseToken;
        stopWatchdog();
        if (eventSource) {
            try { eventSource.close(); } catch (_) { /* ignore */ }
            eventSource = null;
        }
        connected = false;
    }

    function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};

        switch (msg.type) {
            case 'connected':
                connected = true;
                updateStatus('idle');
                break;
            case 'output':
                handleTerminalOutput(data.text || '');
                break;
            case 'closed':
                appendLine('[会话已结束，正在重连…]', 'warning');
                connected = false;
                updateStatus('error');
                if (eventSource) {
                    try { eventSource.close(); } catch (_) { /* ignore */ }
                    eventSource = null;
                }
                ++manualCloseToken;
                if (isOpen()) {
                    scheduleReconnect();
                }
                break;
            case 'heartbeat':
                break;
            case 'error':
                appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
            default:
                break;
        }
    }

    // ============================================================
    // 终端输出处理（支持 ANSI 颜色、\r \n \b 等控制字符）
    // ============================================================
    function handleTerminalOutput(text) {
        let i = 0;
        while (i < text.length) {
            const ch = text[i];

            if (ch === '\n') {
                // 将当前正在编辑的"正在进行行"固化
                const cl = output.querySelector('.term-current-line');
                if (cl) cl.classList.remove('term-current-line');
                flushCurrentLine();
                // 换行后创建新的当前行
                currentLineFragments = [];
                pendingCr = false;
                pushTextFragment('');
                renderCurrentLine();
                i++;
            } else if (ch === '\r') {
                // 回车：标记下一个普通字符从行首开始覆盖
                // 不立即清空：若后面紧跟 \n (CRLF)，行内容应正常保留
                pendingCr = true;
                i++;
            } else if (ch === '\x1b') {
                // ANSI 转义序列
                const result = parseAnsiEscape(text, i);
                i = result.next;
                if (result.sgr) {
                    applyAnsiSgr(result.params);
                    renderCurrentLine();
                } else if (result.eraseLine !== undefined) {
                    eraseInLine(result.eraseLine);
                    pendingCr = false;
                    renderCurrentLine();
                }
                // 其他序列（光标移动等）忽略
            } else if (ch === '\x08') {
                // 退格
                if (pendingCr) {
                    pendingCr = false;
                }
                if (currentLineFragments.length > 0) {
                    const last = currentLineFragments[currentLineFragments.length - 1];
                    if (last.text.length > 0) {
                        last.text = last.text.slice(0, -1);
                    } else if (currentLineFragments.length > 1) {
                        currentLineFragments.pop();
                    }
                    renderCurrentLine();
                }
                i++;
            } else if (ch === '\x07') {
                // BEL 响铃：忽略
                i++;
            } else if (ch === '\x0c') {
                // Form feed (Ctrl+L): 清屏
                clearOutputNoSend();
                pendingCr = false;
                i++;
            } else {
                // 普通字符：若之前有 \r 则清空当前行（覆盖模式）
                if (pendingCr) {
                    currentLineFragments = [];
                    pendingCr = false;
                }
                pushTextFragment(ch);
                renderCurrentLine();
                i++;
            }
        }
        scrollToBottom();
    }

    function parseAnsiEscape(text, start) {
        let i = start + 1;
        if (i >= text.length) return { next: i };

        if (text[i] === '[') {
            // CSI 序列
            i++;
            let paramStr = '';
            while (i < text.length) {
                const code = text.charCodeAt(i);
                if (code >= 0x40 && code <= 0x7e) {
                    const finalByte = text[i];
                    i++;
                    if (finalByte === 'm') {
                        const params = paramStr ? paramStr.split(';').map(s => parseInt(s, 10) || 0) : [0];
                        return { next: i, sgr: true, params };
                    } else if (finalByte === 'K') {
                        const mode = paramStr ? parseInt(paramStr, 10) : 0;
                        return { next: i, eraseLine: mode };
                    }
                    // 其他 CSI 序列（光标移动等）
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
        } else if (text[i] === ']') {
            // OSC 序列
            i++;
            while (i < text.length) {
                if (text[i] === '\x07') { i++; break; }
                if (text[i] === '\x1b' && i + 1 < text.length && text[i + 1] === '\\') { i += 2; break; }
                i++;
            }
            return { next: i };
        } else {
            return { next: i + 1 };
        }
    }

    // ============================================================
    // 状态指示
    // ============================================================
    function updateStatus(state) {
        if (!statusDot || !statusText) return;
        if (state === 'idle' || state === 'done') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-emerald-400';
            statusText.textContent = '就绪';
        } else if (state === 'connecting') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-gold-400 animate-pulse';
            statusText.textContent = '连接中...';
        } else if (state === 'running') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-gold-400 animate-pulse';
            statusText.textContent = '执行中...';
        } else if (state === 'error') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-red-400';
            statusText.textContent = '已断开';
        }
    }

    // ============================================================
    // 输出辅助
    // ============================================================
    function appendLine(text, type) {
        const cl = output.querySelector('.term-current-line');
        if (cl) cl.classList.remove('term-current-line');
        flushCurrentLine();

        const div = document.createElement('div');
        const colorMap = {
            'info':    '#60a5fa',
            'error':   '#f87171',
            'warning': '#fbbf24',
            'success': '#4ade80',
            'dim':     '#64748b',
            'script':  '#a3e635',
            'input':   '#fbbf24',
        };

        if (type === 'input') {
            div.style.cssText = 'padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            const prompt = document.createElement('span');
            prompt.style.cssText = 'color:#4ade80;';
            prompt.textContent = '$ ';
            const cmd = document.createElement('span');
            cmd.style.cssText = 'color:' + colorMap['input'] + ';';
            cmd.textContent = text;
            div.appendChild(prompt);
            div.appendChild(cmd);
        } else if (type === 'script') {
            div.style.cssText = 'padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            const tag = document.createElement('span');
            tag.style.cssText = 'display:inline-block;padding:2px 6px;border-radius:4px;background:rgba(168,85,247,0.2);color:#d8b4fe;font-size:11px;margin-right:4px;';
            tag.textContent = '脚本';
            div.appendChild(tag);
            const txt = document.createElement('span');
            txt.style.cssText = 'color:' + colorMap['script'] + ';';
            txt.textContent = text;
            div.appendChild(txt);
        } else {
            const color = colorMap[type] || '#e2e8f0';
            div.style.cssText = 'color:' + color + ';padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            div.textContent = text;
        }

        output.appendChild(div);
        // 重置当前行为空
        currentLineFragments = [];
        resetAnsiStyle();
        pushTextFragment('');
        renderCurrentLine();
        if (isAutoScroll) output.scrollTop = output.scrollHeight;
    }

    function clearOutputNoSend() {
        output.innerHTML = '';
        currentLineFragments = [];
        pendingCr = false;
        resetAnsiStyle();
        pushTextFragment('');
        renderCurrentLine();
    }

    function clearOutput() {
        clearOutputNoSend();
        if (connected) {
            sendText('\x0c');
        }
        if (connected) updateStatus('idle');
    }

    // ============================================================
    // 输入处理
    // ============================================================
    function runCommand(command) {
        if (!command || !command.trim()) return;
        addToHistory(command);
        // 显示命令回显
        appendLine(command, 'input');
        sendText(command + '\n');
    }

    function addToHistory(cmd) {
        if (!cmd.trim()) return;
        if (commandHistory[commandHistory.length - 1] === cmd) return;
        commandHistory.push(cmd);
        if (commandHistory.length > 200) commandHistory.shift();
        saveHistory();
    }

    function navigateHistory(dir, inputEl) {
        if (commandHistory.length === 0) return;

        if (historyIndex === -1) {
            draftValue = inputEl.value;
        }

        if (dir < 0) {
            if (historyIndex === -1) {
                historyIndex = commandHistory.length - 1;
            } else if (historyIndex > 0) {
                historyIndex--;
            }
        } else {
            if (historyIndex < commandHistory.length - 1) {
                historyIndex++;
            } else {
                historyIndex = -1;
                inputEl.value = draftValue;
                return;
            }
        }

        if (historyIndex >= 0 && historyIndex < commandHistory.length) {
            inputEl.value = commandHistory[historyIndex];
            setTimeout(() => { inputEl.selectionStart = inputEl.selectionEnd = inputEl.value.length; }, 0);
        }
    }

    function saveHistory() {
        try {
            localStorage.setItem('cmd_terminal_history', JSON.stringify(commandHistory));
        } catch (_) { /* ignore */ }
    }

    function loadHistory() {
        try {
            const raw = localStorage.getItem('cmd_terminal_history');
            if (raw) commandHistory = JSON.parse(raw) || [];
        } catch (_) { commandHistory = []; }
    }

    function sendText(text) {
        // 未连接时加入队列
        if (!connected) {
            pendingInputQueue.push(text);
            // 确保正在连接
            if (!eventSource && isOpen()) {
                connectStream();
            }
            return;
        }
        sendTextNow(text);
    }

    function sendTextNow(text) {
        fetch('/admin/cmd/terminal/input', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text }),
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.json().then(function (data) {
                    appendLine('[发送失败] ' + (data.message || 'HTTP ' + resp.status), 'error');
                }).catch(function () {
                    appendLine('[发送失败] HTTP ' + resp.status, 'error');
                });
            }
        }).catch(function (err) {
            appendLine('[发送失败] ' + (err.message || String(err)), 'error');
        });
    }

    function sendInterrupt() {
        sendText('\x03');
    }

    function scrollToBottom() {
        if (isAutoScroll) output.scrollTop = output.scrollHeight;
    }

    // ============================================================
    // 脚本运行状态（由 main.js 调用）
    // ============================================================
    function setScriptRunning(running) {
        scriptRunning = running;
        if (abortBtn) {
            abortBtn.style.display = running ? '' : 'none';
            if (running && window.lucide) lucide.createIcons();
        }
        if (running) {
            updateStatus('running');
        } else if (connected) {
            updateStatus('idle');
        } else {
            updateStatus('error');
        }
    }

    function setOnClose(callback) {
        onCloseCallback = callback || null;
    }

    // ============================================================
    // Public API
    // ============================================================
    return {
        init: init,
        open: open,
        close: close,
        isOpen: isOpen,
        appendLine: appendLine,
        runCommand: runCommand,
        clearOutput: clearOutput,
        setScriptRunning: setScriptRunning,
        setOnClose: setOnClose,
        // 暴露给外部检查连接状态
        isConnected: () => connected,
        // 直接发送（不显示回显）
        sendText: sendText,
    };
})();
