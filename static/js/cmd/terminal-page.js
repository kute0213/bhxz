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

    // ---- 初始化核心组件 ----
    TC.ensureBlinkStyle();

    const buffer = new TC.TerminalBuffer(output, {
        scroller: output,
        lineClass: 'term-line',
    });

    const history = new TC.CommandHistory('cmd_terminal_history');

    const sseTerminal = new TC.SseTerminal({
        url: '/admin/cmd/terminal/stream',
        inputUrl: '/admin/cmd/terminal/input',
        onEvent: handleSseEvent,
        onConnected: function () {
            updateStatus('connected');
            hideConnectingOverlay();
            updateSessionInfo('会话已连接');
        },
        onDisconnected: function () {
            updateStatus('disconnected');
            showConnectingOverlay('连接已断开，正在重连...');
            updateSessionInfo('已断开');
        },
        shouldConnect: function () { return true; },
    });

    // ---- 状态 ----
    let isRunning = false;

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
        sendInterrupt();
    });

    // 页面可见性：切回时检查连接
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            if (!sseTerminal.isConnected()) {
                connectTerminal();
            }
        }
    });

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

        fetch('/admin/cmd/terminal/reset', { method: 'POST' })
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
        buffer.appendLine(command, 'input');
        sendText(command + '\n');
        input.focus();
    }

    function sendText(text) {
        if (sseTerminal) sseTerminal.send(text);
    }

    function sendInterrupt() {
        sendText('\x03');
        buffer.appendLine('^C', 'system');
    }

    // ---- 清屏 ----
    function clearTerminal() {
        buffer.clear();
        if (sseTerminal.isConnected()) {
            sseTerminal.send('\x0c');
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

    // ---- 输入事件监听（用于检测运行状态） ----
    // 通过监听 output 事件中的文本变化来检测是否正在运行
    // 如果输出包含 shell 提示符，则认为命令已执行完毕
    var _origHandleOutput = buffer.handleOutput;
    if (_origHandleOutput) {
        buffer.handleOutput = function (text) {
            _origHandleOutput.call(buffer, text);
            // 检测是否包含 shell 提示符（简单启发式）
            if (text && text.includes('$') && isRunning) {
                // 可能命令已执行完毕，延迟检测
                setTimeout(function () {
                    // 检查最后几行是否有提示符
                    isRunning = false;
                    updateStatus('connected');
                }, 300);
            }
        };
    }

    // 重写 appendLine 以跟踪运行状态
    var _origAppendLine = buffer.appendLine;
    if (_origAppendLine) {
        buffer.appendLine = function (text, type) {
            _origAppendLine.call(buffer, text, type);
            if (type === 'input') {
                isRunning = true;
                updateStatus('running');
            }
        };
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