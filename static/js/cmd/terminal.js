/**
 * CMD 终端弹窗模块（优化版）
 *
 * 功能：
 *   - 磨砂玻璃风格弹窗，与页面设计统一
 *   - 淡入淡出 + 缩放动画
 *   - 标题栏拖拽移动
 *   - 实时 SSE 流式输出
 *   - 命令历史（↑↓）
 *   - 终端自动滚动 / 手动滚动锁定
 *   - 运行状态指示灯
 *   - 字体大小自适应
 */

window.CmdTerminal = (function () {
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

    let isRunning = false;
    let isAutoScroll = true;
    let currentEventSource = null;
    let commandHistory = [];
    let historyIndex = -1;
    let onCloseCallback = null;
    let scriptRunning = false;
    let abortBtn = null;

    // 拖拽
    let isDragging = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;

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
        if (titleBar) {
            abortBtn = document.createElement('button');
            abortBtn.className = 'px-2.5 py-1 bg-red-500/80 text-white text-xs font-bold rounded-lg hover:bg-red-500 transition-colors flex items-center gap-1';
            abortBtn.style.display = 'none';
            abortBtn.innerHTML = '<i data-lucide="square" class="w-3 h-3"></i> 中止';
            abortBtn.addEventListener('click', function () {
                if (window.MiniScript) {
                    if (window.MiniScript.abort) MiniScript.abort();
                    if (window.MiniScript.clearAllTimers) MiniScript.clearAllTimers();
                }
                scriptRunning = false;
                if (abortBtn) abortBtn.style.display = 'none';
                if (!isRunning) updateStatus('done');
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

        // 背景点击关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) close();
        });

        // ESC 关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                close();
            }
        });

        // 输入框快捷键
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                runCommand(input.value);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (historyIndex > 0) {
                    historyIndex--;
                    input.value = commandHistory[historyIndex];
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (historyIndex < commandHistory.length - 1) {
                    historyIndex++;
                    input.value = commandHistory[historyIndex];
                } else {
                    historyIndex = commandHistory.length;
                    input.value = '';
                }
            } else if (e.ctrlKey && e.key === 'l') {
                e.preventDefault();
                clearOutput();
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
    }

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

        updateStatus('idle');
        if (isAutoScroll) output.scrollTop = output.scrollHeight;
        input.focus();
        onCloseCallback = onClose || null;
    }

    function close() {
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }

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

        isRunning = false;
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

    function updateStatus(state) {
        if (!statusDot || !statusText) return;
        if (state === 'idle') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-emerald-400';
            statusText.textContent = '就绪';
        } else if (state === 'running') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-gold-400 animate-pulse';
            statusText.textContent = '执行中...';
        } else if (state === 'done') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-emerald-400';
            statusText.textContent = '完成';
        } else if (state === 'error') {
            statusDot.className = 'terminal-status-dot w-2.5 h-2.5 rounded-full bg-red-400';
            statusText.textContent = '错误';
        }
    }

    function appendLine(text, type) {
        const div = document.createElement('div');
        div.style.cssText = 'line-height:1.6;';

        if (type === 'input') {
            div.className = 'text-gold-400';
            const prompt = document.createElement('span');
            prompt.className = 'text-emerald-400';
            prompt.textContent = '$ ';
            const cmd = document.createElement('span');
            cmd.textContent = text;
            div.appendChild(prompt);
            div.appendChild(cmd);
        } else if (type === 'error') {
            div.className = 'text-red-400';
            const prefix = document.createElement('span');
            prefix.textContent = '✗ ';
            div.appendChild(prefix);
            div.appendChild(document.createTextNode(text));
        } else if (type === 'exit') {
            div.className = 'text-cream/400 italic';
            div.textContent = '\n[进程退出，返回码: ' + text + ']';
        } else if (type === 'script') {
            div.className = 'text-purple-400';
            const tag = document.createElement('span');
            tag.className = 'inline-block px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 text-xs mr-1';
            tag.textContent = '脚本';
            div.appendChild(tag);
            div.appendChild(document.createTextNode(text));
        } else {
            div.textContent = text;
        }

        output.appendChild(div);
        if (isAutoScroll) output.scrollTop = output.scrollHeight;
    }

    function clearOutput() {
        output.innerHTML = '';
        updateStatus('idle');
    }

    function setRunning(running) {
        isRunning = running;
        runBtn.disabled = running;
        input.disabled = running;
        runBtn.classList.toggle('opacity-50', running);
        runBtn.classList.toggle('cursor-not-allowed', running);
        if (running) {
            updateStatus('running');
        } else {
            updateStatus('done');
        }
    }

    function setScriptRunning(running) {
        scriptRunning = running;
        if (abortBtn) {
            abortBtn.style.display = running ? '' : 'none';
            if (running && window.lucide) lucide.createIcons();
        }
        if (running) {
            updateStatus('running');
        } else if (!isRunning) {
            updateStatus('done');
        }
    }

    function setOnClose(callback) {
        onCloseCallback = callback || null;
    }

    function runCommand(command) {
        if (!command.trim() || isRunning) return;

        appendLine(command, 'input');
        commandHistory.push(command);
        historyIndex = commandHistory.length;
        input.value = '';
        setRunning(true);

        const url = '/admin/cmd/run-stream?command=' + encodeURIComponent(command);

        const es = new EventSource(url);
        currentEventSource = es;

        es.onmessage = function (e) {
            if (e.data === '[DONE]') {
                es.close();
                currentEventSource = null;
                setRunning(false);
                setTimeout(() => updateStatus('idle'), 1500);
                return;
            }
            try {
                const evt = JSON.parse(e.data);
                if (evt.type === 'output') {
                    appendLine(evt.line);
                } else if (evt.type === 'exit') {
                    appendLine(evt.code, 'exit');
                } else if (evt.type === 'error') {
                    appendLine('[错误] ' + evt.message, 'error');
                }
            } catch (err) {
                appendLine(e.data);
            }
        };

        es.onerror = function () {
            es.close();
            currentEventSource = null;
            appendLine('[连接断开]', 'error');
            setRunning(false);
            updateStatus('error');
        };
    }

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
