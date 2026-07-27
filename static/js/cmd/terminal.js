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
 *
 * 依赖：terminal-core.js（window.TerminalCore）
 */

window.CmdTerminal = (function () {
    const TC = window.TerminalCore;

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

    // ---- 子模块 ----
    let buffer = null;
    let sseTerminal = null;
    let history = null;

    // ---- 状态 ----
    let onCloseCallback = null;
    let scriptRunning = false;
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

        if (!modal || !output || !input) return;

        TC.ensureBlinkStyle();

        buffer = new TC.TerminalBuffer(output, { scroller: output });
        history = new TC.CommandHistory('cmd_terminal_history');
        sseTerminal = new TC.SseTerminal({
            url: '/admin/cmd/terminal/stream',
            inputUrl: '/admin/cmd/terminal/input',
            onEvent: handleSseEvent,
            onConnected: function () { updateStatus('idle'); },
            onDisconnected: function () { updateStatus('error'); },
            shouldConnect: function () { return isOpen(); },
        });

        _initAbortButton();
        _bindEvents();

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            if (!isOpen()) return;
            if (sseTerminal.isConnected()) return;
            sseTerminal.connect();
        });
    }

    function _initAbortButton() {
        if (!titleBar) return;
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
            updateStatus(sseTerminal.isConnected() ? 'idle' : 'error');
        });
        const closeBtnEl = document.getElementById('terminal-close-btn');
        if (closeBtnEl && closeBtnEl.parentNode) {
            closeBtnEl.parentNode.insertBefore(abortBtn, closeBtnEl);
        }
    }

    function _bindEvents() {
        runBtn.addEventListener('click', function () { runCommand(input.value); });
        clearBtn.addEventListener('click', clearOutput);
        closeBtn.addEventListener('click', close);

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                close();
            }
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                runCommand(input.value);
                input.value = '';
                history.resetIndex();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                history.navigate(-1, input);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                history.navigate(1, input);
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

        if (titleBar) {
            titleBar.addEventListener('mousedown', function (e) {
                if (e.target.closest('button')) return;
                isDragging = true;
                const rect = content.getBoundingClientRect();
                dragOffsetX = e.clientX - rect.left;
                dragOffsetY = e.clientY - rect.top;
                content.style.transition = 'none';
            });
            document.addEventListener('mousemove', _onDragMove);
            document.addEventListener('mouseup', function () {
                if (isDragging) {
                    isDragging = false;
                    content.style.transition = '';
                }
            });
        }
    }

    function _onDragMove(e) {
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

        if (!sseTerminal.eventSource) {
            sseTerminal.connect();
        }

        buffer.scrollToBottom();
        setTimeout(function () { input.focus(); }, 50);
        onCloseCallback = onClose || null;
    }

    function close() {
        sseTerminal.disconnect();

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
    // SSE 事件处理
    // ============================================================
    function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};

        switch (msg.type) {
            case 'connected':
                updateStatus('idle');
                break;
            case 'output':
                buffer.handleOutput(data.text || '');
                break;
            case 'closed':
                buffer.appendLine('[会话已结束，正在重连…]', 'warning');
                updateStatus('error');
                sseTerminal.connect();
                break;
            case 'heartbeat':
                break;
            case 'error':
                buffer.appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
        }
    }

    // ============================================================
    // 状态指示
    // ============================================================
    function updateStatus(state) {
        if (!statusDot || !statusText) return;
        const classes = 'terminal-status-dot w-2.5 h-2.5 rounded-full ';
        if (state === 'idle' || state === 'done') {
            statusDot.className = classes + 'bg-emerald-400';
            statusText.textContent = '就绪';
        } else if (state === 'connecting') {
            statusDot.className = classes + 'bg-gold-400 animate-pulse';
            statusText.textContent = '连接中...';
        } else if (state === 'running') {
            statusDot.className = classes + 'bg-gold-400 animate-pulse';
            statusText.textContent = '执行中...';
        } else if (state === 'error') {
            statusDot.className = classes + 'bg-red-400';
            statusText.textContent = '已断开';
        }
    }

    // ============================================================
    // 输出辅助
    // ============================================================
    function appendLine(text, type) {
        if (buffer) buffer.appendLine(text, type);
    }

    function clearOutput() {
        if (buffer) buffer.clear();
        if (sseTerminal.isConnected()) {
            sseTerminal.send('\x0c');
        }
        updateStatus(sseTerminal.isConnected() ? 'idle' : 'error');
    }

    // ============================================================
    // 输入处理
    // ============================================================
    function runCommand(command) {
        if (!command || !command.trim()) return;
        history.add(command);
        appendLine(command, 'input');
        sendText(command + '\n');
    }

    function sendText(text) {
        if (sseTerminal) sseTerminal.send(text);
    }

    function sendInterrupt() {
        sendText('\x03');
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
        } else {
            updateStatus(sseTerminal.isConnected() ? 'idle' : 'error');
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
        isConnected: function () { return sseTerminal ? sseTerminal.isConnected() : false; },
        sendText: sendText,
    };
})();
