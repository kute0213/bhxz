/**
 * terminal-page.js — 独立实时终端页
 *
 * 基于 xterm.js（terminal-xterm.js）渲染，输出/输入/自适应全部由共享模块处理。
 * 独立页面无独立入口（弹窗终端已接管运行），本页仍支持 URL 直接访问：连接即用，
 * 在 xterm 屏幕内直接键入命令回车执行即可（输入交由 PTY 驱动回显与执行）。
 *
 * 依赖：terminal-xterm.js（window.TerminalXterm）
 */

document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    const TX = window.TerminalXterm;
    if (!TX) {
        console.error('[TerminalPage] terminal-xterm.js 未加载');
        return;
    }

    const screen = document.getElementById('terminal-screen');
    const clearBtn = document.getElementById('term-clear-btn');
    const resetBtn = document.getElementById('term-reset-btn');
    const statusDot = document.getElementById('term-status-dot');
    const statusText = document.getElementById('term-status-text');
    const sessionInfo = document.getElementById('term-session-info');
    const connectingOverlay = document.getElementById('term-connecting-overlay');

    if (!screen) return;

    let tx = null;

    // ---- 状态 UI ----
    function setStatus(state, text) {
        if (!statusDot) return;
        const cls = 'terminal-status-dot w-2 h-2 rounded-full ';
        switch (state) {
            case 'connected': statusDot.className = cls + 'bg-emerald-400'; break;
            case 'connecting': statusDot.className = cls + 'bg-gold-400 animate-pulse'; break;
            case 'disconnected': statusDot.className = cls + 'bg-red-400'; break;
            default: statusDot.className = cls + 'bg-cream/40';
        }
        if (statusText) statusText.textContent = text || '';
    }
    function hideOverlay() {
        if (connectingOverlay) connectingOverlay.classList.add('hidden');
    }
    function showOverlay(msg) {
        if (!connectingOverlay) return;
        const msgEl = connectingOverlay.querySelector('div:nth-child(2)');
        if (msgEl) msgEl.textContent = msg || '正在连接...';
        connectingOverlay.classList.remove('hidden');
    }

    // ---- 挂载 ----
    showOverlay('正在连接终端...');
    setStatus('connecting', '连接中...');
    tx = TX.attach(screen, {
        onConnected: function () {
            hideOverlay();
            setStatus('connected', '就绪');
            if (sessionInfo) sessionInfo.textContent = '会话已连接';
            tx.focus();
        },
        onDisconnected: function () {
            if (statusText && statusText.textContent === '就绪') return;
            setStatus('disconnected', '重连中...');
            showOverlay('连接断开，正在重连...');
        },
    });
    tx.connect();

    // ---- 工具栏 ----
    if (clearBtn) clearBtn.addEventListener('click', function () { if (tx) tx.clear(); });
    if (resetBtn) resetBtn.addEventListener('click', function () {
        if (!tx) return;
        showOverlay('正在重置会话...');
        setStatus('connecting', '重置中...');
        if (sessionInfo) sessionInfo.textContent = '重置中...';
        tx.reset();
        // 服务端重启 shell 后旧 SSE 结束并重连，onConnected 会隐藏遮罩
    });

    // 页面切换回来时重新 fit 确保尺寸正确
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible' && tx) {
            tx.fit();
            tx.focus();
        }
    });

    if (window.lucide) lucide.createIcons();
});