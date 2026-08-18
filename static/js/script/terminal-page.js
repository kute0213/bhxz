/**
 * terminal-page.js — 独立页面版实时终端
 *
 * 相比 modal 版 terminal.js 的优化：
 *   - 无模态框打开/关闭/拖拽逻辑，页面加载即连接
 *   - 全视口高度，输出区自动撑满
 *   - 更清晰的连接状态指示
 *   - 快速中断按钮（Ctrl+C）
 *   - 会话重置功能
 *   - 更流畅的渲染性能
 *
 * 依赖：terminal-core.js（window.TerminalCore）
 */

document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    const TC = window.TerminalCore;
    if (!TC) {
        console.error('[TerminalPage] terminal-core.js 未加载');
        return;
    }

    // ---- DOM 元素 ----
    const output = document.getElementById('terminal-output');
    const input = document.getElementById('terminal-input');
    const runBtn = document.getElementById('terminal-run-btn');
    const clearBtn = document.getElementById('term-clear-btn');
    const resetBtn = document.getElementById('term-reset-btn');
    const interruptBtn = document.getElementById('term-interrupt-btn');
    const statusDot = document.getElementById('term-status-dot');
    const statusText = document.getElementById('term-status-text');
    const sessionInfo = document.getElementById('term-session-info');
    const connectingOverlay = document.getElementById('term-connecting-overlay');

    if (!output || !input) return;

    // ---- 读取 URL 参数：cmd / script（来自脚本控制台的跳转） ----
    var urlParams = new URLSearchParams(window.location.search);
    var autoCommand = urlParams.get('cmd');
    var autoScriptId = urlParams.get('script');
    var autoScriptName = urlParams.get('name') || '匿名脚本';
    var autoCommandDone = false;

    // ---- 初始化核心组件 ----
    TC.ensureBlinkStyle();

    const buffer = new TC.TerminalBuffer(output, {
        scroller: output,
        lineClass: 'term-line',
    });

    const history = new TC.CommandHistory('script_terminal_history');

    const sseTerminal = new TC.SseTerminal({
        url: '/admin/script/terminal/stream',
        inputUrl: '/admin/script/terminal/input',
        onEvent: handleSseEvent,
        onConnected: function () {
            updateStatus('connected');
            hideConnectingOverlay();
            updateSessionInfo('会话已连接');
            sendResize();
            // 若从脚本控制台带 cmd 参数跳转而来，连接就绪后自动执行
            if (autoCommand && !autoCommandDone) {
                autoCommandDone = true;
                executeCommand(autoCommand);
            }
        },
        onDisconnected: function () {
            updateStatus('disconnected');
            showConnectingOverlay('连接已断开，正在重连...');
            updateSessionInfo('已断开');
        },
        shouldConnect: function () { return true; },
    });

    // ---- 初始化 ----
    // 页面加载即自动连接
    connectTerminal();

    // ---- 事件绑定 ----
    runBtn.addEventListener('click', function () {
        executeCommand(input.value);
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            executeCommand(input.value);
            input.value = '';
            history.resetIndex();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            history.navigate(-1, input);
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            history.navigate(1, input);
        }
    });

    // 全局快捷键
    document.addEventListener('keydown', function (e) {
        if (e.ctrlKey && e.key === 'l') {
            e.preventDefault();
            clearTerminal();
        } else if (e.ctrlKey && e.key === 'c') {
            e.preventDefault();
            sendInterrupt();
        } else if (e.key === 'Tab') {
            if (document.activeElement === input) {
                e.preventDefault();
                sendText('\t');
            }
        }
    });

    clearBtn.addEventListener('click', clearTerminal);

    resetBtn.addEventListener('click', function () {
        resetSession();
    });

    interruptBtn.addEventListener('click', function () {
        if (scriptRunning) {
            abortRunningScript();
        } else {
            sendInterrupt();
        }
    });

    // 页面可见性：切回时检查连接
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            if (!sseTerminal.isConnected()) {
                connectTerminal();
            }
        }
    });

    // ------------------------------------------------------------------
    // 脚本执行（通过后端 SSE API /admin/script/run-script 运行 Python/MiniScript）
    // 依赖：ScriptModal（modal.js）提供 alert/prompt/confirm
    // ------------------------------------------------------------------
    var scriptRunning = false;
    var scriptFetchController = null;

    // 若从脚本控制台带 script 参数跳转而来，加载脚本并执行
    if (autoScriptId) {
        buffer.appendLine('[正在加载脚本: ' + autoScriptName + ']', 'system');
        showConnectingOverlay('正在加载脚本 ' + autoScriptName + ' ...');
        updateStatus('running');
        fetch('/admin/script/scripts/' + encodeURIComponent(autoScriptId))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.script) {
                    runScript(data.script.content, data.script.name || autoScriptName);
                } else {
                    buffer.appendLine('[加载脚本失败] ' + (data.message || '未知错误'), 'error');
                    updateStatus('error');
                    hideConnectingOverlay();
                }
            })
            .catch(function (err) {
                buffer.appendLine('[加载脚本失败] ' + err.message, 'error');
                updateStatus('error');
                hideConnectingOverlay();
            });
    }

    function runScript(code, name) {
        buffer.appendLine('运行脚本: ' + (name || '匿名'), 'script');
        showConnectingOverlay('脚本执行中...');
        updateStatus('running');
        scriptRunning = true;
        if (interruptBtn) interruptBtn.style.display = '';
        executeScriptViaSse(code);
    }

    async function executeScriptViaSse(code) {
        // 终止上一个未结束的脚本 SSE 连接
        if (scriptFetchController) {
            scriptFetchController.abort();
        }
        scriptFetchController = new AbortController();

        try {
            var resp = await fetch('/admin/script/run-script', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code }),
                signal: scriptFetchController.signal,
            });

            if (!resp.ok) {
                var errMsg = 'HTTP ' + resp.status;
                try {
                    var errData = await resp.json();
                    if (errData && errData.message) errMsg = errData.message;
                } catch (_) { /* ignore */ }
                buffer.appendLine('[错误] ' + errMsg, 'error');
                finishScriptRun();
                return;
            }

            await consumeSseStream(resp);
        } catch (err) {
            if (err && err.name === 'AbortError') {
                buffer.appendLine('[已请求终止脚本]', 'script');
            } else {
                buffer.appendLine('[网络错误] ' + (err.message || String(err)), 'error');
            }
        } finally {
            scriptFetchController = null;
            finishScriptRun();
        }
    }

    async function consumeSseStream(resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder('utf-8');
        var bufferStr = '';

        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            bufferStr += decoder.decode(chunk.value, { stream: true });

            var idx;
            while ((idx = bufferStr.indexOf('\n\n')) !== -1) {
                var rawEvent = bufferStr.slice(0, idx);
                bufferStr = bufferStr.slice(idx + 2);
                await handleScriptEvent(rawEvent);
            }
        }
    }

    async function handleScriptEvent(rawEvent) {
        var lines = rawEvent.split('\n');
        var dataStr = '';
        for (var i = 0; i < lines.length; i++) {
            if (lines[i].indexOf('data:') === 0) {
                dataStr += lines[i].slice(5).replace(/^\s/, '');
            }
        }
        if (!dataStr) return;

        var msg;
        try {
            msg = JSON.parse(dataStr);
        } catch (e) {
            return; // 非 JSON 数据忽略
        }
        if (!msg || !msg.type) return;
        var data = msg.data || {};

        switch (msg.type) {
            case 'output':
                buffer.appendLine(data.text != null ? String(data.text) : '', 'script');
                break;
            case 'alert':
                if (window.ScriptModal && window.ScriptModal.alert) {
                    await window.ScriptModal.alert(data.title || '提示', data.message || '');
                }
                break;
            case 'prompt': {
                var value = data.default || '';
                if (window.ScriptModal && window.ScriptModal.prompt) {
                    value = await window.ScriptModal.prompt(data.title || '输入', data.message || '', data.default || '');
                }
                await sendScriptResponse(value);
                break;
            }
            case 'confirm': {
                var ok = false;
                if (window.ScriptModal && window.ScriptModal.confirm) {
                    ok = await window.ScriptModal.confirm(data.title || '确认', data.message || '');
                }
                await sendScriptResponse(!!ok);
                break;
            }
            case 'error':
                buffer.appendLine('[错误] ' + (data.message || '未知错误'), 'error');
                break;
            case 'done':
                buffer.appendLine('[脚本执行完毕]', 'script');
                break;
            default:
                buffer.appendLine('[事件:' + msg.type + '] ' + JSON.stringify(data), 'error');
        }
    }

    async function sendScriptResponse(value) {
        try {
            await fetch('/admin/script/script-response', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: value }),
            });
        } catch (err) {
            buffer.appendLine('[回传响应失败] ' + err.message, 'error');
        }
    }

    function abortRunningScript() {
        try {
            fetch('/admin/script/abort-script', { method: 'POST' }).catch(function () { /* ignore */ });
        } catch (err) { /* ignore */ }
        if (scriptFetchController) {
            scriptFetchController.abort();
        }
    }

    function finishScriptRun() {
        scriptRunning = false;
        if (interruptBtn) interruptBtn.style.display = 'none';
        hideConnectingOverlay();
        updateStatus(sseTerminal.isConnected() ? 'connected' : 'disconnected');
    }

    // ---- 终端连接管理 ----
    function connectTerminal() {
        showConnectingOverlay('正在连接终端...');
        updateStatus('connecting');
        sseTerminal.connect();
    }

    function hideConnectingOverlay() {
        if (connectingOverlay) {
            connectingOverlay.classList.add('hidden');
        }
    }

    function showConnectingOverlay(message) {
        if (!connectingOverlay) return;
        connectingOverlay.classList.remove('hidden');
        const msgEl = connectingOverlay.querySelector('div:nth-child(2)');
        if (msgEl) msgEl.textContent = message || '正在连接...';
    }

    // ---- 会话重置 ----
    function resetSession() {
        sseTerminal.disconnect();
        buffer.clear();
        updateStatus('connecting');
        showConnectingOverlay('正在重置会话...');
        updateSessionInfo('重置中...');

        fetch('/admin/script/terminal/reset', { method: 'POST' })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.success) {
                    connectTerminal();
                } else {
                    buffer.appendLine('[重置失败] ' + (data.message || '未知错误'), 'error');
                    updateStatus('error');
                    hideConnectingOverlay();
                }
            })
            .catch(function (err) {
                buffer.appendLine('[重置失败] ' + err.message, 'error');
                updateStatus('error');
                hideConnectingOverlay();
            });
    }

    // ---- SSE 事件处理 ----
    function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        var data = msg.data || {};

        switch (msg.type) {
            case 'connected':
                updateStatus('connected');
                hideConnectingOverlay();
                updateSessionInfo('会话已连接');
                break;
            case 'output':
                buffer.handleOutput(data.text || '');
                break;
            case 'closed':
                buffer.appendLine('[会话已结束，正在重连…]', 'system');
                updateStatus('disconnected');
                showConnectingOverlay('会话已结束，正在重连...');
                connectTerminal();
                break;
            case 'heartbeat':
                break;
            case 'error':
                buffer.appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
        }
    }

    // ---- 命令执行 ----
    function executeCommand(command) {
        if (!command || !command.trim()) return;
        history.add(command);
        // 输入交由 PTY 终端驱动回显，前端不再重复插入命令文本
        sendText(command + '\n');
        input.focus();
    }

    function sendText(text) {
        if (sseTerminal) sseTerminal.send(text);
    }

    function sendInterrupt() {
        // 发送 SIGINT；^C 回显由 PTY 终端驱动负责
        sendText('\x03');
    }

    // ---- 窗口尺寸同步 ----
    function sendResize() {
        const geometry = buffer.getGeometry ? buffer.getGeometry() : { rows: 24, cols: 120 };
        fetch('/admin/script/terminal/resize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cols: geometry.cols, rows: geometry.rows }),
        }).catch(function () { /* 忽略：无 PTY 时不重要 */ });
    }

    window.addEventListener('resize', sendResize);

    // ---- 清屏 ----
    function clearTerminal() {
        buffer.clear();
        if (sseTerminal.isConnected()) {
            // 向 shell 发送 Ctrl+L，触发其真正清屏并重绘
            sendText('\x0c');
        }
    }

    // ---- 状态指示 ----
    function updateStatus(state) {
        if (!statusDot || !statusText) return;
        var dotClasses = 'terminal-status-dot w-2 h-2 rounded-full ';
        switch (state) {
            case 'connected':
                statusDot.className = dotClasses + 'bg-emerald-400';
                statusText.textContent = '就绪';
                hideInterruptButton();
                break;
            case 'connecting':
                statusDot.className = dotClasses + 'bg-gold-400 animate-pulse';
                statusText.textContent = '连接中...';
                hideInterruptButton();
                break;
            case 'running':
                statusDot.className = dotClasses + 'bg-gold-400 animate-pulse';
                statusText.textContent = '执行中...';
                showInterruptButton();
                break;
            case 'disconnected':
                statusDot.className = dotClasses + 'bg-red-400';
                statusText.textContent = '已断开';
                hideInterruptButton();
                break;
            case 'error':
                statusDot.className = dotClasses + 'bg-red-500';
                statusText.textContent = '错误';
                hideInterruptButton();
                break;
        }
    }

    function updateSessionInfo(info) {
        if (sessionInfo) sessionInfo.textContent = info;
    }

    function showInterruptButton() {
        if (interruptBtn) interruptBtn.style.display = '';
    }

    function hideInterruptButton() {
        if (interruptBtn) interruptBtn.style.display = 'none';
    }

    // ---- 暴露公共 API ----
    window.TerminalPage = {
        executeCommand: executeCommand,
        clearTerminal: clearTerminal,
        resetSession: resetSession,
        isConnected: function () { return sseTerminal.isConnected(); },
        sendText: sendText,
    };

    // Lucide 图标
    if (window.lucide) lucide.createIcons();
});