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
 * 依赖：terminal-core.js（window.TerminalCore）
 * 暴露：window.TerminalPanel
 */
window.TerminalPanel = (function () {
    'use strict';

    const TC = window.TerminalCore;

    // ---- DOM 元素 ----
    let outputEl = null;
    let inputEl = null;
    let wrapperEl = null;

    // ---- 子模块 ----
    let buffer = null;
    let history = null;
    let sseTerminal = null;

    // ---- 状态 ----
    let scriptRunning = false;

    // ============================================================
    // 初始化
    // ============================================================
    function init() {
        outputEl = document.getElementById('editor-output');
        inputEl = document.getElementById('terminal-input');
        wrapperEl = document.getElementById('editor-output-wrapper');

        if (!outputEl || !inputEl) return;

        TC.ensureBlinkStyle();

        buffer = new TC.TerminalBuffer(outputEl, { scroller: wrapperEl || outputEl });
        history = new TC.CommandHistory('terminal_history');
        sseTerminal = new TC.SseTerminal({
            url: '/admin/script/terminal/stream',
            inputUrl: '/admin/script/terminal/input',
            onEvent: handleSseEvent,
            onConnected: function () {
                clearLastLineIf('正在连接终端…');
            },
            onDisconnected: function () {
                appendLine('[连接断开，正在重连…]', 'warning');
            },
            shouldConnect: function () {
                return isPanelVisible();
            },
        });

        inputEl.addEventListener('keydown', onInputKeydown);

        if (wrapperEl) {
            wrapperEl.addEventListener('click', function () { focusInput(); });
        }

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            if (sseTerminal.isConnected()) return;
            reconnect();
        });

        connectStream();
    }

    // ============================================================
    // SSE 连接
    // ============================================================
    function connectStream() {
        if (!isPanelVisible()) return;
        appendLine('正在连接终端…', 'dim');
        sseTerminal.connect();
    }

    function reconnect() {
        if (!isPanelVisible()) return;
        if (sseTerminal.isConnected()) return;
        sseTerminal.connect();
    }

    function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};

        switch (msg.type) {
            case 'connected':
                clearLastLineIf('正在连接终端…');
                break;
            case 'output':
                buffer.handleOutput(data.text || '');
                break;
            case 'heartbeat':
                break;
            case 'closed':
                appendLine('[会话已结束，正在重连…]', 'warning');
                sseTerminal.connect();
                break;
            case 'error':
                appendLine('[终端错误] ' + (data.message || ''), 'error');
                break;
        }
    }

    // ============================================================
    // 输入处理
    // ============================================================
    function onInputKeydown(e) {
        const input = e.target;
        if (e.key === 'Enter') {
            e.preventDefault();
            runCommand(input.value);
            input.value = '';
            history.resetIndex();
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            history.navigate(-1, input);
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            history.navigate(1, input);
            return;
        }
        if (e.key === 'l' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            clearTerminal();
            return;
        }
        if (e.key === 'c' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            sendInterrupt();
            return;
        }
        if (e.key === 'Tab') {
            e.preventDefault();
            sendText('\t');
            return;
        }
    }

    function runCommand(cmd) {
        if (!cmd || !cmd.trim()) return;
        history.add(cmd);
        // 输入回显由 PTY 终端驱动负责，前端不重复插入
        sendText(cmd + '\n');
    }

    function sendText(text) {
        sseTerminal.send(text);
    }

    function sendInterrupt() {
        sendText('\x03');
    }

    // ============================================================
    // 输出辅助
    // ============================================================
    function appendLine(text, type) {
        if (buffer) buffer.appendLine(text, type);
    }

    function appendCommandLine(cmd) {
        if (buffer) buffer.appendLine(cmd, 'input');
    }

    function appendOutput(text) {
        if (buffer) buffer.handleOutput((text || '') + '\n');
    }

    function clearTerminal() {
        if (buffer) buffer.clear();
        if (sseTerminal.isConnected()) {
            sseTerminal.send('\x0c');
        }
    }

    function clearLastLineIf(text) {
        if (!outputEl) return;
        const last = outputEl.lastElementChild;
        if (last && last.textContent.trim() === text.trim()) {
            last.remove();
        }
    }

    function scrollToBottom() {
        if (buffer) buffer.scrollToBottom();
    }

    function focusInput() {
        if (inputEl) inputEl.focus();
    }

    function isPanelVisible() {
        const panel = document.getElementById('output-panel');
        if (!panel) return false;
        return !panel.classList.contains('collapsed');
    }

    function getRunning() {
        return sseTerminal ? sseTerminal.isConnected() : false;
    }

    // ============================================================
    // Public API
    // ============================================================
    return {
        init: init,
        sendCommand: runCommand,
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
