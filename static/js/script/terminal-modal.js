/**
 * terminal-modal.js — 弹窗终端
 *
 * 无独立入口：直接点击终端控制台的「运行」快捷命令时，
 * 自动打开本弹窗终端并执行命令。
 *
 * 快捷命令（Shell）：把命令发送到共享 PTY 会话执行，输出实时回流。
 *
 * 依赖：terminal-xterm.js（window.TerminalXterm）、modal.js（window.ScriptModal）
 * 暴露：window.ScriptTerminalModal
 */
window.ScriptTerminalModal = (function () {
    'use strict';

    var TX = window.TerminalXterm;

    // ---- DOM ----
    var modalEl, screenEl, statusDot, statusText, titleEl, actionEl;
    var clearBtn, resetBtn, interruptBtn, closeBtn;

    // ---- 状态 ----
    var t = null;                 // xterm controller
    var pendingAction = null;     // 连接就绪后待执行的动作
    var starting = false;

    function init() {
        modalEl = document.getElementById('term-modal');
        if (!modalEl) return;
        screenEl = document.getElementById('term-modal-screen');
        statusDot = document.getElementById('term-modal-status-dot');
        statusText = document.getElementById('term-modal-status-text');
        titleEl = document.getElementById('term-modal-title');
        clearBtn = document.getElementById('term-modal-clear');
        resetBtn = document.getElementById('term-modal-reset');
        interruptBtn = document.getElementById('term-modal-interrupt');
        closeBtn = document.getElementById('term-modal-close');

        if (clearBtn) clearBtn.addEventListener('click', function () { clearTerminal(); });
        if (resetBtn) resetBtn.addEventListener('click', function () { resetSession(); });
        if (interruptBtn) interruptBtn.addEventListener('click', function () { sendCtrlC(); });
        if (closeBtn) closeBtn.addEventListener('click', close);
        if (modalEl) {
            modalEl.addEventListener('click', function (e) {
                if (e.target === modalEl) close();
            });
        }
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modalEl && !isHidden()) close();
        });
    }

    function isHidden() {
        return modalEl.classList.contains('hidden');
    }

    // ---- 挂载并连接 ----
    function mountIfNeeded() {
        // 返回 true 表示本次调用完成了挂载
        if (t) return false;
        if (starting) return false;
        starting = true;
        setStatus('connecting', '连接中...');
        setAction('正在连接终端...');
        t = TX.attach(screenEl, {
            onConnected: function () {
                setStatus('connected', '就绪');
                setAction('');
                if (pendingAction) {
                    var a = pendingAction;
                    pendingAction = null;
                    setTimeout(a, 0);
                }
            },
            onDisconnected: function () {
                setStatus('disconnected', '重连中...');
            },
        });
        t.connect();
        setTimeout(function () { if (t) t.focus(); }, 60);
        return true;
    }

    // ---- 打开 / 关闭 ----
    function show() {
        if (!modalEl) return;
        modalEl.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        mountIfNeeded();
        // 每次显示都重新 fit：确保 xterm 画布尺寸跟随容器，避免黑屏/尺寸为 0
        requestAnimationFrame(function () {
            if (t) { t.fit(); t.focus(); }
        });
    }

    function close() {
        if (!modalEl) return;
        modalEl.classList.add('hidden');
        document.body.style.overflow = '';
    }

    // ---- 执行快捷命令（Shell，走共享 PTY） ----
    function runCommand(line) {
        if (!line || !line.trim()) return;
        var doIt = function () {
            t.send(line + '\r');
            setAction('$ ' + line);
            t.focus();
        };
        if (t && t.isConnected()) { show(); doIt(); }
        else { pendingAction = doIt; show(); }
    }

    // ---- 其它操作 ----
    function clearTerminal() {
        if (t) t.clear();
    }
    function resetSession() {
        if (!t) return;
        setStatus('connecting', '重置中...');
        t.reset();
        setStatus('connected', '就绪');
    }
    function sendCtrlC() {
        if (t) t.send('\x03');
    }

    // ---- 状态 UI ----
    function setStatus(state, text) {
        if (!statusDot) return;
        var cls = 'w-2 h-2 rounded-full ';
        switch (state) {
            case 'connecting': statusDot.className = cls + 'bg-gold-400 animate-pulse'; break;
            case 'connected': statusDot.className = cls + 'bg-emerald-400'; break;
            case 'disconnected': statusDot.className = cls + 'bg-red-400'; break;
            default: statusDot.className = cls + 'bg-cream/40';
        }
        if (statusText) statusText.textContent = text || '';
    }
    function setAction(text) {
        if (titleEl) titleEl.textContent = text || '弹窗终端';
    }

    document.addEventListener('DOMContentLoaded', init);

    return {
        init: init,
        open: show,
        close: close,
        runCommand: runCommand,
        isConnected: function () { return !!(t && t.isConnected()); },
    };
})();