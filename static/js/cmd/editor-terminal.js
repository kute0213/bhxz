/**
 * editor-terminal.js — 持久终端面板
 *
 * 功能：
 *   - 持久 shell 会话（cd 等状态保持）
 *   - 真实命令提示符（从 shell 获取）
 *   - 命令历史记录（↑/↓ 切换）
 *   - SSE 流式输出 + POST 输入
 *   - 快捷键：Ctrl+L 清屏、Ctrl+C 中断、Enter 执行
 *   - 终端重置（重启 shell）
 *
 * 暴露：window.TerminalPanel
 */
window.TerminalPanel = (function () {

    // 命令历史
    let cmdHistory = [];
    let historyIndex = -1;
    let draftValue = '';

    // SSE 连接状态
    let eventSource = null;
    let connected = false;
    let reconnectTimer = null;     // 手动重连定时器
    let manualCloseToken = 0;      // 主动关闭令牌：每次主动关闭递增，onerror 据此判断是否跳过重连
    const RECONNECT_DELAY = 3000;  // 重连延迟（毫秒）

    // 心跳看门狗：记录最后收到任意数据（含心跳）的时间，
    // 超过阈值则认为连接已死，主动重连。
    let lastDataTime = Date.now();
    let watchdogTimer = null;
    const WATCHDOG_TIMEOUT = 35000;  // 35 秒无数据视为断连（服务端心跳 10s 一次）
    const WATCHDOG_CHECK_INTERVAL = 5000;  // 每 5 秒检查一次

    // 终端输出缓冲区（用于 ANSI 处理、回显等）
    let currentLine = '';

    // ============================================================
    // 初始化
    // ============================================================
    function init() {
        const input = document.getElementById('terminal-input');
        if (!input) return;

        input.addEventListener('keydown', onInputKeydown);
        loadHistory();

        // 建立 SSE 连接
        connectStream();

        // 点击终端区域聚焦输入框
        const wrapper = document.getElementById('editor-output-wrapper');
        if (wrapper) {
            wrapper.addEventListener('click', function () {
                focusInput();
            });
        }

        // 页面可见性监听：切回页面时若连接已断开则主动重连
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            // 已连接则无需处理
            if (connected && eventSource) return;
            // 取消挂起的延迟重连，立即重连
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            connectStream();
        });
    }

    // ============================================================
    // SSE 连接
    // ============================================================
    function connectStream() {
        // 取消可能挂起的重连
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }

        // 防御：面板折叠时不建立连接，避免不可见时浪费服务端资源。
        // 仅当面板元素存在且已折叠时才跳过；元素不存在（如初始化阶段）
        // 仍允许连接，避免影响正常流程。
        const panel = document.getElementById('output-panel');
        if (panel && panel.classList.contains('collapsed')) {
            return;
        }

        // 主动关闭旧连接（递增 token，onerror 据此判断是否跳过重连）
        // 旧 onerror 回调捕获本次 token 值，若发现 token 已变化则视为主动关闭
        const closedToken = ++manualCloseToken;
        if (eventSource) {
            try { eventSource.close(); } catch (_) { /* ignore */ }
            eventSource = null;
        }

        connected = false;
        lastDataTime = Date.now();
        appendLine('正在连接终端…', 'dim');

        // 使用 EventSource 实现 SSE（支持携带 cookie）
        const es = new EventSource('/admin/cmd/terminal/stream', { withCredentials: true });

        es.onopen = function () {
            connected = true;
            lastDataTime = Date.now();
            // 连接成功，清除挂起的重连
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            // 启动心跳看门狗
            startWatchdog();
        };

        es.onmessage = function (e) {
            let msg;
            try {
                msg = JSON.parse(e.data);
            } catch (_) {
                return;
            }
            // 任何消息都视为连接活跃
            lastDataTime = Date.now();
            handleSseEvent(msg);
        };

        es.onerror = function () {
            // 捕获本次连接的 token：若 token 已变化，说明是主动关闭，跳过重连
            const myToken = closedToken;
            if (connected) {
                appendLine('[连接断开，正在重连…]', 'warning');
                connected = false;
            }
            // 关闭当前 EventSource，避免其默认自动重连与手动重连冲突
            try { es.close(); } catch (_) { /* ignore */ }
            if (eventSource === es) {
                eventSource = null;
            }
            // 主动关闭时不触发重连（token 已递增说明是主动关闭）
            if (myToken !== manualCloseToken) return;
            scheduleReconnect();
        };

        eventSource = es;
    }

    // ============================================================
    // 心跳看门狗
    // ============================================================

    function startWatchdog() {
        stopWatchdog();
        watchdogTimer = setInterval(function () {
            // 面板折叠时不触发重连
            if (!isPanelVisible()) return;
            // 已断开则交给 onerror 路径处理
            if (!connected) return;
            const elapsed = Date.now() - lastDataTime;
            if (elapsed > WATCHDOG_TIMEOUT) {
                appendLine('[长时间无心跳，主动重连…]', 'warning');
                // 强制关闭当前连接，触发重连
                if (eventSource) {
                    try { eventSource.close(); } catch (_) { /* ignore */ }
                    eventSource = null;
                }
                connected = false;
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
        // 已有重连挂起则不重复调度
        if (reconnectTimer) return;
        // 面板折叠时不重连，避免不可见时浪费资源
        // 展开时由 toggle 处理器调用 reconnect()
        if (!isPanelVisible()) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            // 双重检查：定时器触发时面板可能已被折叠
            if (!isPanelVisible()) return;
            connectStream();
        }, RECONNECT_DELAY);
    }

    function isPanelVisible() {
        const panel = document.getElementById('output-panel');
        if (!panel) return false;
        // 折叠状态下视为不可见
        return !panel.classList.contains('collapsed');
    }

    function reconnect() {
        // 取消挂起的重连，立即尝试连接
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (connected && eventSource) return;  // 已连接
        if (!isPanelVisible()) return;  // 面板折叠时不连接
        connectStream();
    }

    function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};

        switch (msg.type) {
            case 'connected':
                // 清除"正在连接"提示
                clearLastLineIf('正在连接终端…');
                break;
            case 'output':
                handleTerminalOutput(data.text || '');
                break;
            case 'heartbeat':
                // 心跳包，仅用于保持连接活跃，无需处理
                break;
            case 'closed':
                appendLine('[会话已结束，正在重连…]', 'warning');
                connected = false;
                // 服务端 _get_or_create_session 会自动创建新会话，
                // 这里主动重连以恢复终端可用性。
                if (eventSource) {
                    try { eventSource.close(); } catch (_) { /* ignore */ }
                    eventSource = null;
                }
                // 递增 token 避免即将触发的 onerror 再次调度重连
                ++manualCloseToken;
                scheduleReconnect();
                break;
            case 'error':
                appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
        }
    }

    // ============================================================
    // 终端输出处理（处理换行、回车、ANSI 等）
    // ============================================================
    function handleTerminalOutput(text) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;

        let i = 0;
        while (i < text.length) {
            const ch = text[i];

            if (ch === '\n') {
                // 换行
                finishLine(panel);
                i++;
            } else if (ch === '\r') {
                // 回车：回到行首
                currentLine = '';
                updateCurrentLine(panel);
                i++;
            } else if (ch === '\x1b') {
                // ANSI 转义序列：简单跳过
                i = skipAnsiEscape(text, i);
            } else if (ch === '\x08') {
                // 退格
                if (currentLine.length > 0) {
                    currentLine = currentLine.slice(0, -1);
                    updateCurrentLine(panel);
                }
                i++;
            } else if (ch === '\x07') {
                // 响铃：忽略
                i++;
            } else {
                // 普通字符
                currentLine += ch;
                updateCurrentLine(panel);
                i++;
            }
        }

        scrollToBottom();
    }

    function skipAnsiEscape(text, start) {
        // 跳过 ANSI 转义序列
        // CSI: \x1b[ 参数字节(0x30-0x3f) 中间字节(0x20-0x2f) 终止字节(0x40-0x7e)
        // OSC: \x1b] ... \x07 (BEL) 或 \x1b\\ (ST)
        let i = start + 1;
        if (i >= text.length) return i;

        if (text[i] === '[') {
            // CSI 序列
            i++;
            while (i < text.length) {
                const code = text.charCodeAt(i);
                // 0x20-0x2f: 中间字节（继续）
                // 0x30-0x3f: 参数字节（继续）
                // 0x40-0x7e: 终止字节（结束）
                if (code >= 0x40 && code <= 0x7e) {
                    i++;
                    break;
                }
                // 0x20-0x3f 之间的字节都是合法的参数/中间字节，继续
                if (code >= 0x20 && code <= 0x3f) {
                    i++;
                    continue;
                }
                // 非法字节，截断序列
                break;
            }
        } else if (text[i] === ']') {
            // OSC 序列：以 BEL(\x07) 或 ST(\x1b\\) 结束
            i++;
            while (i < text.length) {
                if (text[i] === '\x07') {
                    i++;
                    break;
                }
                if (text[i] === '\x1b' && i + 1 < text.length && text[i + 1] === '\\') {
                    i += 2;
                    break;
                }
                i++;
            }
        } else {
            // 其他转义序列（如 \x1b= \x1b> \x1b7 等）：跳过 1 个字符
            i++;
        }
        return i;
    }

    function finishLine(panel) {
        // 当前行转为正式行元素
        const lines = panel.querySelectorAll('.term-current-line');
        lines.forEach(function (el) {
            el.classList.remove('term-current-line');
        });
        currentLine = '';
        // 创建新的当前行
        const line = document.createElement('div');
        line.className = 'term-current-line';
        line.style.cssText = 'color:#e2e8f0;padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;';
        panel.appendChild(line);
    }

    function updateCurrentLine(panel) {
        let line = panel.querySelector('.term-current-line');
        if (!line) {
            line = document.createElement('div');
            line.className = 'term-current-line';
            line.style.cssText = 'color:#e2e8f0;padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;';
            panel.appendChild(line);
        }
        line.textContent = currentLine;
    }

    function clearLastLineIf(text) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;
        const last = panel.lastElementChild;
        if (last && last.textContent.trim() === text.trim()) {
            last.remove();
        }
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

        if (e.key === 'ArrowUp') {
            e.preventDefault();
            navigateHistory(-1, input);
            return;
        }

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            navigateHistory(1, input);
            return;
        }

        // Ctrl+L 清屏
        if (e.key === 'l' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            clearTerminal();
            return;
        }

        // Ctrl+C 中断
        if (e.key === 'c' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            sendInterrupt();
            return;
        }

        // Tab 补全（简单实现：发送 \t）
        if (e.key === 'Tab') {
            e.preventDefault();
            sendText('\t');
            return;
        }
    }

    function sendCommand(cmd) {
        sendText(cmd + '\n');
    }

    function sendText(text) {
        if (!connected) {
            appendLine('[未连接，无法发送]', 'error');
            return;
        }
        fetch('/admin/cmd/terminal/input', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text }),
        }).catch(function (err) {
            appendLine('[发送失败] ' + err.message, 'error');
        });
    }

    function sendInterrupt() {
        sendText('\x03');  // Ctrl+C
    }

    // ============================================================
    // 历史记录
    // ============================================================
    function addToHistory(cmd) {
        if (!cmd.trim()) return;
        if (cmdHistory[cmdHistory.length - 1] === cmd) return;
        cmdHistory.push(cmd);
        if (cmdHistory.length > 200) cmdHistory.shift();
        saveHistory();
    }

    function navigateHistory(dir, input) {
        if (cmdHistory.length === 0) return;

        if (historyIndex === -1) {
            draftValue = input.value;
        }

        if (dir < 0) {
            if (historyIndex === -1) {
                historyIndex = cmdHistory.length - 1;
            } else if (historyIndex > 0) {
                historyIndex--;
            }
        } else {
            if (historyIndex < cmdHistory.length - 1) {
                historyIndex++;
            } else {
                historyIndex = -1;
                input.value = draftValue;
                return;
            }
        }

        if (historyIndex >= 0 && historyIndex < cmdHistory.length) {
            input.value = cmdHistory[historyIndex];
            setTimeout(() => { input.selectionStart = input.selectionEnd = input.value.length; }, 0);
        }
    }

    function saveHistory() {
        try {
            localStorage.setItem('terminal_history', JSON.stringify(cmdHistory));
        } catch (_) { /* ignore */ }
    }

    function loadHistory() {
        try {
            const raw = localStorage.getItem('terminal_history');
            if (raw) cmdHistory = JSON.parse(raw) || [];
        } catch (_) { cmdHistory = []; }
    }

    // ============================================================
    // 输出辅助
    // ============================================================
    function appendLine(text, type) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;

        // 如果有当前行，先结束它
        const current = panel.querySelector('.term-current-line');
        if (current) current.classList.remove('term-current-line');

        const line = document.createElement('div');
        line.textContent = text;
        const colorMap = {
            'info':    '#60a5fa',
            'error':   '#f87171',
            'warning': '#fbbf24',
            'success': '#4ade80',
            'dim':     '#64748b',
            'script':  '#a3e635',
        };
        line.style.color = colorMap[type] || '#e2e8f0';
        line.style.cssText += 'padding:1px 0;white-space:pre-wrap;word-break:break-all;';
        panel.appendChild(line);
        scrollToBottom();
    }

    function appendCommandLine(cmd) {
        appendLine('$ ' + cmd, 'info');
    }

    function appendOutput(text) {
        // 兼容旧接口：直接追加文本
        handleTerminalOutput(text + '\n');
    }

    function clearTerminal() {
        const panel = document.getElementById('editor-output');
        if (panel) panel.innerHTML = '';
        currentLine = '';
        // 仅在已连接时发送清屏命令，避免未连接时报错
        if (connected) {
            sendText('\x0c');  // Ctrl+L
        }
    }

    function scrollToBottom() {
        const wrapper = document.getElementById('editor-output-wrapper');
        if (wrapper) wrapper.scrollTop = wrapper.scrollHeight;
    }

    function focusInput() {
        const input = document.getElementById('terminal-input');
        if (input) input.focus();
    }

    function getRunning() {
        return connected;
    }

    // ============================================================
    // Public API
    // ============================================================
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
