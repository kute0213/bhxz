/**
 * terminal-modal.js — 弹窗终端
 *
 * 无独立入口：直接点击脚本控制台的「运行」快捷命令 /「运行」脚本时，
 * 自动打开本弹窗终端并执行。
 *   - 快捷命令（Shell）：把命令发送到共享 PTY 会话执行，输出实时回流。
 *   - 脚本（Python/MiniScript）：通过后端 SSE API 在独立子进程执行，输出
 *     实时写入弹窗终端；alert/prompt/confirm 复用 ScriptModal。
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
    var scriptRunning = false;
    var scriptController = null;

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
        if (interruptBtn) interruptBtn.addEventListener('click', function () {
            if (scriptRunning) abortScript();
            else sendCtrlC();
        });
        if (closeBtn) closeBtn.addEventListener('click', close);
        if (modalEl) {
            modalEl.addEventListener('click', function (e) {
                if (e.target === modalEl) close();
            });
        }
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modalEl && !isHidden()) close();
        });
        // 关闭弹窗时若脚本仍在跑，一并终止，避免后台孤儿进程
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'hidden' && scriptRunning) abortScript();
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
                if (scriptRunning) return;
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
        setTimeout(function () {
            if (t) { t.fit(); t.focus(); }
        }, 80);
    }

    function close() {
        if (!modalEl) return;
        modalEl.classList.add('hidden');
        document.body.style.overflow = '';
        if (scriptRunning) abortScript();
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

    // ---- 执行脚本（后端 SSE 独立子进程） ----
    function runScript(id, name) {
        var label = name || '脚本';
        var doIt = function () {
            setStatus('running', '执行中...');
            setAction('正在运行：' + label);
            if (interruptBtn) interruptBtn.style.display = '';
            executeScript(id, label);
        };
        if (t && t.isConnected()) { show(); doIt(); }
        else { pendingAction = doIt; show(); }
    }

    function executeScript(id, label) {
        scriptRunning = true;
        fetch('/admin/script/scripts/' + encodeURIComponent(id))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.script && data.script.content) {
                    runScriptSse(data.script.content, data.script.name || label);
                } else {
                    writeError('加载脚本失败: ' + (data && data.message ? data.message : '未知错误'));
                    finishRun();
                }
            })
            .catch(function (err) {
                writeError('加载脚本失败: ' + err.message);
                finishRun();
            });
    }

    function runScriptSse(code, name) {
        if (scriptController) { try { scriptController.abort(); } catch (_) {} }
        scriptController = new AbortController();

        fetch('/admin/script/run-script', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code }),
            signal: scriptController.signal,
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.json().then(function (d) {
                    writeError('[错误] ' + (d && d.message ? d.message : 'HTTP ' + resp.status));
                    finishRun();
                }).catch(function () {
                    writeError('[错误] HTTP ' + resp.status);
                    finishRun();
                });
            }
            return consumeSse(resp);
        }).then(function () {
            finishRun();
        }).catch(function (err) {
            if (err && err.name === 'AbortError') {
                writeLabel('[已请求终止脚本]');
            } else {
                writeError('[网络错误] ' + (err && err.message ? err.message : String(err)));
            }
            finishRun();
        }).finally(function () {
            scriptController = null;
        });
    }

    async function consumeSse(resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder('utf-8');
        var buf = '';
        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buf += decoder.decode(chunk.value, { stream: true });
            var idx;
            while ((idx = buf.indexOf('\n\n')) !== -1) {
                var raw = buf.slice(0, idx);
                buf = buf.slice(idx + 2);
                await handleScriptEvent(raw);
            }
        }
    }

    async function handleScriptEvent(raw) {
        var lines = raw.split('\n');
        var dataStr = '';
        for (var i = 0; i < lines.length; i++) {
            if (lines[i].indexOf('data:') === 0) {
                dataStr += lines[i].slice(5).replace(/^\s/, '');
            }
        }
        if (!dataStr) return;
        var msg;
        try { msg = JSON.parse(dataStr); } catch (_) { return; }
        if (!msg || !msg.type) return;
        var data = msg.data || {};

        switch (msg.type) {
            case 'output':
                if (t) t.write(data.text != null ? String(data.text) : '');
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
                await scriptResponse(value);
                break;
            }
            case 'confirm': {
                var ok = false;
                if (window.ScriptModal && window.ScriptModal.confirm) {
                    ok = await window.ScriptModal.confirm(data.title || '确认', data.message || '');
                }
                await scriptResponse(!!ok);
                break;
            }
            case 'error':
                writeError('[错误] ' + (data.message || '未知错误'));
                break;
            case 'done':
                writeLabel('[脚本执行完毕]');
                break;
            default:
                break;
        }
    }

    function scriptResponse(value) {
        return fetch('/admin/script/script-response', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: value }),
        }).catch(function () {});
    }

    function abortScript() {
        try {
            fetch('/admin/script/abort-script', { method: 'POST' }).catch(function () {});
        } catch (_) {}
        if (scriptController) {
            try { scriptController.abort(); } catch (_) {}
        }
    }

    function finishRun() {
        scriptRunning = false;
        if (interruptBtn) interruptBtn.style.display = 'none';
        setStatus(t && t.isConnected() ? 'connected' : 'disconnected', '就绪');
        setAction('');
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
            case 'running': statusDot.className = cls + 'bg-gold-400 animate-pulse'; break;
            case 'connected': statusDot.className = cls + 'bg-emerald-400'; break;
            case 'disconnected': statusDot.className = cls + 'bg-red-400'; break;
            default: statusDot.className = cls + 'bg-cream/40';
        }
        if (statusText) statusText.textContent = text || '';
    }
    function setAction(text) {
        if (titleEl) titleEl.textContent = text || '弹窗终端';
    }
    function writeError(text) {
        if (t) t.write('\r\n\x1b[31m' + text + '\x1b[0m\r\n');
    }
    function writeLabel(text) {
        if (t) t.write('\r\n\x1b[2m' + text + '\x1b[0m\r\n');
    }

    document.addEventListener('DOMContentLoaded', init);

    return {
        init: init,
        open: show,
        close: close,
        runCommand: runCommand,
        runScript: runScript,
        isConnected: function () { return !!(t && t.isConnected()); },
    };
})();