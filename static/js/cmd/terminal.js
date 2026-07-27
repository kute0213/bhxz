/**
 * CMD 终端弹窗模块（持久 shell 版）
 *
 * 功能：
 *   - 磨砂玻璃风格弹窗，与页面设计统一
 *   - 淡入淡出 + 缩放动画
 *   - 标题栏拖拽移动
 *   - 持久 shell 会话（cd 等状态保持），SSE 流式输出
 *   - 命令历史（↑↓，持久化到 localStorage）
 *   - 终端自动滚动 / 手动滚动锁定
 *   - 运行状态指示灯
 *   - 快捷键：Ctrl+L 清屏、Ctrl+C 中断、Enter 执行、Tab 补全
 *   - 断线自动重连（延迟 3 秒）
 *   - 页面可见性监听：切回页面时主动重连
 *
 * 后端 API（与脚本编辑器终端一致）：
 *   - GET  /admin/cmd/terminal/stream  —— SSE 输出流
 *   - POST /admin/cmd/terminal/input   —— 发送输入
 *   - POST /admin/cmd/terminal/reset   —— 重置 shell
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
    let manualCloseToken = 0;   // 主动关闭令牌：递增避免 onerror 时序竞态
    let currentLine = '';       // 当前正在构建的输出行（处理 \r \n 等）
    const RECONNECT_DELAY = 3000;

    // ---- 心跳看门狗 ----
    let lastDataTime = Date.now();
    let watchdogTimer = null;
    const WATCHDOG_TIMEOUT = 35000;  // 35 秒无数据视为断连
    const WATCHDOG_CHECK_INTERVAL = 5000;  // 每 5 秒检查一次

    // ---- 拖拽 ----
    let isDragging = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;

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

        // 创建"中止脚本"按钮（添加到标题栏，默认隐藏）
        // 点击后调用后端 /admin/cmd/abort-script 终止正在执行的脚本
        if (titleBar) {
            abortBtn = document.createElement('button');
            abortBtn.className = 'px-2.5 py-1 bg-red-500/80 text-white text-xs font-bold rounded-lg hover:bg-red-500 transition-colors flex items-center gap-1';
            abortBtn.style.display = 'none';
            abortBtn.innerHTML = '<i data-lucide="square" class="w-3 h-3"></i> 中止';
            abortBtn.addEventListener('click', function () {
                // 优先调用 main.js 暴露的中止函数（会同时切断前端 SSE 连接）
                if (typeof window.__abortCmdScript === 'function') {
                    window.__abortCmdScript();
                } else {
                    // 降级：直接调用后端 abort API
                    fetch('/admin/cmd/abort-script', { method: 'POST' }).catch(function () { /* ignore */ });
                }
                scriptRunning = false;
                if (abortBtn) abortBtn.style.display = 'none';
                if (connected) updateStatus('idle'); else updateStatus('error');
            });
            // 插入到关闭按钮前面
            var closeBtnEl = document.getElementById('terminal-close-btn');
            if (closeBtnEl && closeBtnEl.parentNode) {
                closeBtnEl.parentNode.insertBefore(abortBtn, closeBtnEl);
            }
        }

        // 按钮
        runBtn.addEventListener('click', () => runCommand(input.value));
        clearBtn.addEventListener('click', clearOutput);
        closeBtn.addEventListener('click', close);

        // ESC 关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                close();
            }
        });

        // 输入框快捷键（与脚本编辑器终端一致）
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
                // Ctrl+L 清屏
                e.preventDefault();
                clearOutput();
            } else if (e.ctrlKey && e.key === 'c') {
                // Ctrl+C 中断（发送 \x03 到 shell）
                e.preventDefault();
                sendInterrupt();
            } else if (e.key === 'Tab') {
                // Tab 补全（发送 \t 到 shell）
                e.preventDefault();
                sendText('\t');
            }
        });

        // 自动滚动检测
        output.addEventListener('scroll', () => {
            const dist = output.scrollHeight - output.scrollTop - output.clientHeight;
            isAutoScroll = dist < 50;
        });

        // 拖拽
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

        // 加载历史记录
        loadHistory();

        // 页面可见性监听：切回页面时若连接已断开则主动重连
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            if (!isOpen()) return;
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
    // 打开 / 关闭
    // ============================================================
    function open(onClose) {
        if (!modal) init();
        if (!modal) return;

        // 重置拖拽位置
        content.style.position = '';
        content.style.left = '';
        content.style.top = '';
        content.style.margin = '';
        modal.style.alignItems = '';

        // 先移除隐藏，再添加动画类
        modal.classList.remove('hidden');
        // 重启动画：先移除再添加
        content.classList.remove('terminal-fade-out');
        content.classList.remove('terminal-fade-in');
        // 强制 reflow 让动画从头开始
        void content.offsetWidth;
        content.classList.add('terminal-fade-in');

        // 打开时建立 SSE 连接（如果尚未连接）
        if (!eventSource) {
            connectStream();
        }

        if (isAutoScroll) output.scrollTop = output.scrollHeight;
        setTimeout(() => input.focus(), 50);
        onCloseCallback = onClose || null;
    }

    function close() {
        // 关闭时断开 SSE 连接
        disconnectStream();

        // 播放关闭动画
        content.classList.remove('terminal-fade-in');
        content.classList.add('terminal-fade-out');

        const onAnimEnd = function () {
            content.classList.remove('terminal-fade-out');
            modal.classList.add('hidden');
            content.removeEventListener('animationend', onAnimEnd);
            // 重置拖拽
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
        // 取消可能挂起的重连
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }

        // 主动关闭旧连接（递增 token，onerror 据此判断是否跳过重连）
        const closedToken = ++manualCloseToken;
        if (eventSource) {
            try { eventSource.close(); } catch (_) { /* ignore */ }
            eventSource = null;
        }

        connected = false;
        lastDataTime = Date.now();
        updateStatus('connecting');

        // 建立 SSE 连接（携带 cookie）
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
                return;  // 非 JSON 数据（如 SSE 注释 / 心跳），忽略
            }
            // 任何消息都视为连接活跃
            lastDataTime = Date.now();
            handleSseEvent(msg);
        };

        es.onerror = function () {
            const myToken = closedToken;
            if (connected) {
                appendLine('[连接断开，正在重连…]', 'warning');
                connected = false;
            }
            // 关闭当前连接（阻止 EventSource 自动重连，改用自定义重连策略）
            try { es.close(); } catch (_) { /* ignore */ }
            if (eventSource === es) {
                eventSource = null;
            }
            updateStatus('error');

            // 主动关闭时不触发重连（token 已递增说明是主动关闭）
            if (myToken !== manualCloseToken) return;

            // 仅在弹窗打开时自动重连（延迟 3 秒）
            if (isOpen()) {
                scheduleReconnect();
            }
        };

        eventSource = es;
    }

    // ============================================================
    // 心跳看门狗
    // ============================================================
    function startWatchdog() {
        stopWatchdog();
        watchdogTimer = setInterval(function () {
            // 弹窗关闭时不触发
            if (!isOpen()) return;
            // 已断开则交给 onerror 路径处理
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
        // 已有重连挂起则不重复调度
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            if (isOpen()) {
                connectStream();
            }
        }, RECONNECT_DELAY);
    }

    function disconnectStream() {
        // 清除重连定时器
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        // 递增 token 阻止 onerror 触发重连
        ++manualCloseToken;
        // 停止看门狗
        stopWatchdog();
        // 关闭 SSE 连接
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
                // 连接建立成功
                connected = true;
                updateStatus('idle');
                break;
            case 'output':
                // shell 输出
                handleTerminalOutput(data.text || '');
                break;
            case 'closed':
                // 会话已结束，服务端会自动创建新会话，这里主动重连
                appendLine('[会话已结束，正在重连…]', 'warning');
                connected = false;
                updateStatus('error');
                if (eventSource) {
                    try { eventSource.close(); } catch (_) { /* ignore */ }
                    eventSource = null;
                }
                // 递增 token 避免即将触发的 onerror 再次调度重连
                ++manualCloseToken;
                if (isOpen()) {
                    scheduleReconnect();
                }
                break;
            case 'heartbeat':
                // 心跳事件，仅用于保活，无需处理
                break;
            case 'error':
                appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
            default:
                // 未知事件类型，忽略
                break;
        }
    }

    // ============================================================
    // 终端输出处理（处理换行、回车、ANSI 转义等）
    // 与脚本编辑器终端样式一致
    // ============================================================
    function handleTerminalOutput(text) {
        let i = 0;
        while (i < text.length) {
            const ch = text[i];

            if (ch === '\n') {
                // 换行：固化当前行
                finishLine();
                i++;
            } else if (ch === '\r') {
                // 回车：回到行首，清空当前行缓冲
                currentLine = '';
                updateCurrentLine();
                i++;
            } else if (ch === '\x1b') {
                // ANSI 转义序列：跳过
                i = skipAnsiEscape(text, i);
            } else if (ch === '\x08') {
                // 退格
                if (currentLine.length > 0) {
                    currentLine = currentLine.slice(0, -1);
                    updateCurrentLine();
                }
                i++;
            } else if (ch === '\x07') {
                // 响铃：忽略
                i++;
            } else {
                // 普通字符
                currentLine += ch;
                updateCurrentLine();
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
                // 0x40-0x7e: 终止字节（结束）
                if (code >= 0x40 && code <= 0x7e) {
                    i++;
                    break;
                }
                // 0x20-0x3f: 参数/中间字节（继续）
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

    function finishLine() {
        // 将当前行固化为正式行元素
        const lines = output.querySelectorAll('.term-current-line');
        lines.forEach(function (el) {
            el.classList.remove('term-current-line');
        });
        currentLine = '';
        // 创建新的空当前行
        const line = document.createElement('div');
        line.className = 'term-current-line';
        // 与脚本编辑器终端样式一致（浅灰色）
        line.style.cssText = 'color:#e2e8f0;padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;';
        output.appendChild(line);
    }

    function updateCurrentLine() {
        let line = output.querySelector('.term-current-line');
        if (!line) {
            line = document.createElement('div');
            line.className = 'term-current-line';
            // 与脚本编辑器终端样式一致（浅灰色）
            line.style.cssText = 'color:#e2e8f0;padding:0;white-space:pre-wrap;word-break:break-all;min-height:1.2em;';
            output.appendChild(line);
        }
        line.textContent = currentLine;
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
    // 输出辅助（与脚本编辑器终端颜色一致）
    // ============================================================
    function appendLine(text, type) {
        // 先固化当前行，避免与流式输出混淆
        const current = output.querySelector('.term-current-line');
        if (current) current.classList.remove('term-current-line');

        const div = document.createElement('div');
        // 与脚本编辑器终端颜色映射一致
        const colorMap = {
            'info':    '#60a5fa',
            'error':   '#f87171',
            'warning': '#fbbf24',
            'success': '#4ade80',
            'dim':     '#64748b',
            'script':  '#a3e635',
            'input':   '#fbbf24',  // 输入命令用金色
        };

        if (type === 'input') {
            // 输入命令行：$ 提示符 + 命令
            div.style.cssText = 'color:' + (colorMap['input']) + ';padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            const prompt = document.createElement('span');
            prompt.style.color = '#4ade80';
            prompt.textContent = '$ ';
            const cmd = document.createElement('span');
            cmd.textContent = text;
            div.appendChild(prompt);
            div.appendChild(cmd);
        } else if (type === 'script') {
            // 脚本标签 + 文本
            div.style.cssText = 'color:' + (colorMap['script']) + ';padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            const tag = document.createElement('span');
            tag.style.cssText = 'display:inline-block;padding:2px 6px;border-radius:4px;background:rgba(168,85,247,0.2);color:#d8b4fe;font-size:11px;margin-right:4px;';
            tag.textContent = '脚本';
            div.appendChild(tag);
            div.appendChild(document.createTextNode(text));
        } else {
            // 普通文本行
            const color = colorMap[type] || '#e2e8f0';
            div.style.cssText = 'color:' + color + ';padding:1px 0;white-space:pre-wrap;word-break:break-all;';
            div.textContent = text;
        }

        output.appendChild(div);
        if (isAutoScroll) output.scrollTop = output.scrollHeight;
    }

    function clearOutput() {
        // 清空本地输出区
        output.innerHTML = '';
        currentLine = '';
        // 仅在已连接时发送清屏指令到 shell（Ctrl+L / form feed）
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
        // 记录命令历史
        addToHistory(command);
        // 发送到持久 shell（后端 /admin/cmd/terminal/input 会自动创建会话）
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
        // 未连接时直接提示，避免发送到已关闭的会话
        if (!connected) {
            appendLine('[未连接，无法发送]', 'error');
            return;
        }
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
        // Ctrl+C = \x03（ETX）
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
    // Public API（保持不变）
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
    };
})();
