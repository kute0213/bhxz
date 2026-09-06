/**
 * terminal-stream.js — 风格统一的流式输出终端
 *
 * 替代原有的 xterm.js + PTY 实时终端方案。
 * 通过 SSE 连接 /admin/script/run-stream 端点，流式接收命令执行输出。
 *
 * 设计特点：
 *   - 纯 DOM 实现，无 canvas 依赖
 *   - 风格与页面磨砂玻璃 / 暗色主题统一
 *   - 支持 ANSI 转义序列简单解析（颜色、加粗）
 *   - 自动滚动到底部
 *   - 命令输入 + 一键执行
 *
 * 暴露：window.StreamTerminal.attach(container, opts) -> controller
 */
window.StreamTerminal = (function () {
    'use strict';

    var STREAM_URL = '/admin/script/run-stream';

    // ANSI 颜色映射
    var ANSI_COLORS = {
        '0':  null,  // reset
        '1':  'font-weight:bold;',
        '30': 'color:#000000;',
        '31': 'color:#f87171;',
        '32': 'color:#4ade80;',
        '33': 'color:#f4d03f;',
        '34': 'color:#60a5fa;',
        '35': 'color:#c084fc;',
        '36': 'color:#55c6c6;',
        '37': 'color:#c8d3d5;',
        '90': 'color:#64748b;',
        '91': 'color:#f87171;',
        '92': 'color:#4ade80;',
        '93': 'color:#f4d03f;',
        '94': 'color:#60a5fa;',
        '95': 'color:#c084fc;',
        '96': 'color:#55c6c6;',
        '97': 'color:#ffffff;',
    };

    // ---- 工具函数 ----

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * 简单解析 ANSI 转义序列，返回带样式的 HTML 片段。
     * 支持：颜色（30-37, 90-97）、加粗（1）、重置（0）
     */
    function parseAnsi(text) {
        if (!text) return '';
        // 移除 \r 字符
        text = text.replace(/\r/g, '');
        // 先 HTML 转义
        text = escapeHtml(text);

        // 解析 \x1b[...m 序列
        var parts = text.split(/(\x1b\[[\d;]*m)/);
        var result = '';
        var styles = [];

        for (var i = 0; i < parts.length; i++) {
            var part = parts[i];
            var match = part.match(/^\x1b\[([\d;]*)m$/);
            if (match) {
                var codes = match[1] ? match[1].split(';') : ['0'];
                for (var j = 0; j < codes.length; j++) {
                    var code = codes[j];
                    if (code === '0' || code === '') {
                        styles = [];
                    } else if (ANSI_COLORS[code]) {
                        // 移除旧的颜色样式
                        styles = styles.filter(function (s) {
                            return s.indexOf('color:') === -1;
                        });
                        styles.push(ANSI_COLORS[code]);
                    }
                }
            } else {
                if (styles.length > 0) {
                    result += '<span style="' + styles.join('') + '">' + part + '</span>';
                } else {
                    result += part;
                }
            }
        }
        return result;
    }

    // ---- 终端控制器 ----

    function attach(container, opts) {
        opts = opts || {};
        var onFinish = opts.onFinish || function () {};
        var onStart = opts.onStart || function () {};

        // ---- 构建 DOM ----
        container.innerHTML = '';
        container.style.cssText = 'display:flex;flex-direction:column;height:100%;background:#0b0f14;border-radius:0.75rem;overflow:hidden;';

        // 输出区域
        var outputWrap = document.createElement('div');
        outputWrap.style.cssText = 'flex:1;overflow-y:auto;padding:12px;font-family:\'JetBrains Mono\',Menlo,Consolas,monospace;font-size:13px;line-height:1.5;color:#c8d3d5;background:#0b0f14;';

        var outputEl = document.createElement('div');
        outputEl.style.cssText = 'min-height:100%;white-space:pre-wrap;word-break:break-all;';
        outputWrap.appendChild(outputEl);

        // 状态栏
        var statusBar = document.createElement('div');
        statusBar.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 12px;background:rgba(0,0,0,0.4);border-top:1px solid rgba(255,255,255,0.06);font-size:12px;color:rgba(200,211,213,0.5);flex-shrink:0;';

        var statusDot = document.createElement('span');
        statusDot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:rgba(200,211,213,0.3);flex-shrink:0;';

        var statusText = document.createElement('span');
        statusText.textContent = '就绪';

        var statusCode = document.createElement('span');
        statusCode.style.cssText = 'margin-left:auto;';

        statusBar.appendChild(statusDot);
        statusBar.appendChild(statusText);
        statusBar.appendChild(statusCode);

        // 输入栏
        var inputBar = document.createElement('div');
        inputBar.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 12px;background:rgba(0,0,0,0.3);border-top:1px solid rgba(255,255,255,0.06);flex-shrink:0;';

        var promptSpan = document.createElement('span');
        promptSpan.textContent = '$';
        promptSpan.style.cssText = 'color:#4ade80;font-family:\'JetBrains Mono\',Menlo,Consolas,monospace;font-size:13px;font-weight:bold;flex-shrink:0;';

        var inputEl = document.createElement('input');
        inputEl.type = 'text';
        inputEl.style.cssText = 'flex:1;background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:6px 10px;color:#c8d3d5;font-family:\'JetBrains Mono\',Menlo,Consolas,monospace;font-size:13px;outline:none;';
        inputEl.placeholder = '输入命令...';

        var runBtn = document.createElement('button');
        runBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3" fill="rgba(244,208,63,0.3)" stroke="#f4d03f"/></svg>';
        runBtn.style.cssText = 'display:flex;align-items:center;justify-content:center;width:32px;height:32px;background:rgba(244,208,63,0.15);border:1px solid rgba(244,208,63,0.2);border-radius:6px;cursor:pointer;transition:all 0.15s;flex-shrink:0;';
        runBtn.title = '执行';

        var clearBtn = document.createElement('button');
        clearBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:rgba(200,211,213,0.5);"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
        clearBtn.style.cssText = 'display:flex;align-items:center;justify-content:center;width:32px;height:32px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.06);border-radius:6px;cursor:pointer;transition:all 0.15s;flex-shrink:0;';
        clearBtn.title = '清屏';

        inputBar.appendChild(promptSpan);
        inputBar.appendChild(inputEl);
        inputBar.appendChild(runBtn);
        inputBar.appendChild(clearBtn);

        container.appendChild(outputWrap);
        container.appendChild(statusBar);
        container.appendChild(inputBar);

        // ---- 状态 ----
        var running = false;
        var abortController = null;

        // ---- 内部方法 ----

        function setStatus(state, msg, code) {
            var colors = {
                ready:  'rgba(200,211,213,0.3)',
                running: '#f4d03f',
                success: '#4ade80',
                error:  '#f87171',
                timeout: '#f87171',
            };
            statusDot.style.background = colors[state] || 'rgba(200,211,213,0.3)';
            if (state === 'running') {
                statusDot.style.animation = 'pulse 1s ease-in-out infinite';
            } else {
                statusDot.style.animation = '';
            }
            statusText.textContent = msg || '';
            if (code !== undefined) {
                var color = state === 'success' ? '#4ade80' : (state === 'error' || state === 'timeout' ? '#f87171' : 'rgba(200,211,213,0.5)');
                statusCode.innerHTML = '<span style="color:' + color + ';">退出码: ' + code + '</span>';
            } else {
                statusCode.innerHTML = '';
            }
        }

        function writeOutput(html) {
            outputEl.insertAdjacentHTML('beforeend', html);
            outputWrap.scrollTop = outputWrap.scrollHeight;
        }

        function writeLine(text, className) {
            var cls = className ? ' class="' + className + '"' : '';
            writeOutput('<div' + cls + '>' + text + '</div>');
        }

        function clearOutput() {
            outputEl.innerHTML = '';
        }

        function scrollToBottom() {
            outputWrap.scrollTop = outputWrap.scrollHeight;
        }

        function runCommand(command) {
            if (!command || !command.trim()) return;
            if (running) {
                // 如果正在运行，先中止
                abort();
            }

            running = true;
            clearOutput();
            setStatus('running', '执行中...');
            onStart();

            // 显示执行的命令
            writeOutput(
                '<div style="color:#4ade80;margin-bottom:4px;">$ ' + escapeHtml(command) + '</div>'
            );

            abortController = new AbortController();

            var params = new URLSearchParams();
            params.append('command', command);
            params.append('timeout', '300');

            fetch(STREAM_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: params,
                signal: abortController.signal,
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                var reader = response.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';

                function readChunk() {
                    reader.read().then(function (result) {
                        if (result.done) {
                            // 处理缓冲区剩余内容
                            if (buffer) {
                                processSSEBuffer(buffer);
                            }
                            return;
                        }
                        buffer += decoder.decode(result.value, { stream: true });
                        processSSEBuffer(buffer);
                        // 更新 buffer 为未处理的部分
                        var idx = buffer.lastIndexOf('\n\n');
                        if (idx >= 0) {
                            buffer = buffer.slice(idx + 2);
                        }
                        readChunk();
                    }).catch(function (err) {
                        if (err.name === 'AbortError') return;
                        handleError(err.message);
                    });
                }
                readChunk();
            }).catch(function (err) {
                if (err.name === 'AbortError') return;
                handleError(err.message);
            });
        }

        function processSSEBuffer(buffer) {
            var parts = buffer.split('\n\n');
            for (var i = 0; i < parts.length - 1; i++) {
                var part = parts[i].trim();
                if (!part) continue;
                if (part === 'data: [DONE]') {
                    // 流结束，等待最后一个事件处理
                    continue;
                }
                var match = part.match(/^data: (.+)$/);
                if (!match) continue;
                try {
                    var event = JSON.parse(match[1]);
                    handleStreamEvent(event);
                } catch (_) {
                    // 忽略解析错误
                }
            }
        }

        function handleStreamEvent(event) {
            if (!event || !event.type) return;
            switch (event.type) {
                case 'output':
                    var line = event.line || '';
                    var html = parseAnsi(line);
                    writeOutput(html);
                    // 换行
                    writeOutput('\n');
                    break;
                case 'exit':
                    running = false;
                    var code = event.code;
                    var state = (code === 0) ? 'success' : 'error';
                    setStatus(state, '已完成', code);
                    writeOutput(
                        '<div style="color:' + (code === 0 ? '#4ade80' : '#f87171') + ';margin-top:4px;">' +
                        '进程已退出，退出码: ' + code +
                        '</div>'
                    );
                    onFinish();
                    break;
                case 'error':
                    running = false;
                    var msg = event.message || '未知错误';
                    setStatus('error', '错误', -1);
                    writeOutput(
                        '<div style="color:#f87171;margin-top:4px;">[错误] ' + escapeHtml(msg) + '</div>'
                    );
                    onFinish();
                    break;
            }
        }

        function handleError(msg) {
            running = false;
            setStatus('error', '连接失败', -1);
            writeOutput(
                '<div style="color:#f87171;margin-top:4px;">[连接错误] ' + escapeHtml(msg) + '</div>'
            );
            onFinish();
        }

        function abort() {
            if (abortController) {
                abortController.abort();
                abortController = null;
            }
            running = false;
            writeOutput(
                '<div style="color:#f4d03f;margin-top:4px;">[已中止]</div>'
            );
            setStatus('ready', '已中止');
            onFinish();
        }

        // ---- 事件绑定 ----

        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                var cmd = inputEl.value.trim();
                if (cmd) {
                    inputEl.value = '';
                    runCommand(cmd);
                }
            }
        });

        runBtn.addEventListener('click', function () {
            var cmd = inputEl.value.trim();
            if (cmd) {
                inputEl.value = '';
                runCommand(cmd);
            }
        });

        clearBtn.addEventListener('click', function () {
            clearOutput();
        });

        // ---- 公共 API ----

        return {
            run: runCommand,
            clear: clearOutput,
            abort: abort,
            isRunning: function () { return running; },
            focus: function () { inputEl.focus(); },
            setCommand: function (cmd) { inputEl.value = cmd; },
        };
    }

    // 添加 pulse 动画
    var styleEl = document.createElement('style');
    styleEl.textContent = '@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }';
    document.head.appendChild(styleEl);

    return {
        attach: attach,
    };
})();