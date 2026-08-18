/**
 * editor-sse.js — 脚本 SSE 执行与事件处理
 *
 * 由 editor.js 拆分而来，负责：
 *   - runScript：通过后端 SSE API 流式执行脚本
 *   - consumeSseStream / handleSseRawEvent / handleSseEvent：解析 SSE 事件
 *   - sendScriptResponse：回传 prompt/confirm 交互响应
 *   - abortScript：强制终止脚本
 *   - setRunning：运行状态切换（含运行/终止按钮显隐）
 *
 * 暴露：window.ScriptEditorSse
 * 依赖：window.ScriptEditor（提供 getEditor / appendOutput / clearOutput / _updateRunButton）
 *      必须在 editor.js 之前加载（函数运行时才访问 window.ScriptEditor）
 *      window.ScriptModal（交互弹窗）
 */
window.ScriptEditorSse = (function () {

    // 运行状态与前端 SSE 连接控制器（仅本模块内部使用）
    let isRunning = false;
    let currentFetchController = null;
    const _exitHandlers = {};

    // 页面退出时主动通知后端终止脚本（涵盖刷新、关闭标签页、跳转、意外关闭）
    function setupExitWatching() {
        if (_exitHandlers.installed) return;
        _exitHandlers.installed = true;

        const notifyExit = function () {
            // 页面卸载期间 fetch 可能被取消，用 sendBeacon 最可靠
            if (navigator.sendBeacon) {
                navigator.sendBeacon('/admin/script/abort-script');
            } else {
                fetch('/admin/script/abort-script', { method: 'POST', keepalive: true }).catch(function () {});
            }
        };

        _exitHandlers.pagehide = function () { if (getRunning()) notifyExit(); };
        _exitHandlers.beforeunload = function () { if (getRunning()) notifyExit(); };
        _exitHandlers.visibility = function () {
            // 切到后台（隐含页面不可见）时先尝试终止；回到前台前端已重建也会重新发起
            if (document.visibilityState === 'hidden' && getRunning()) notifyExit();
        };
        _exitHandlers.unload = function () { if (getRunning()) notifyExit(); };

        window.addEventListener('pagehide', _exitHandlers.pagehide);
        window.addEventListener('beforeunload', _exitHandlers.beforeunload);
        window.addEventListener('unload', _exitHandlers.unload);
        document.addEventListener('visibilitychange', _exitHandlers.visibility);
    }

    // ==================================================================
    // 脚本运行：通过后端 SSE API 执行
    // ==================================================================
    async function runScript() {
        if (isRunning) return;  // 运行中点击无效，需通过"强制终止"按钮停止

        const editor = window.ScriptEditor.getEditor();
        const code = editor.getValue();
        if (!code.trim()) {
            window.ScriptEditor.appendOutput('[错误] 脚本为空', 'error');
            return;
        }

        setRunning(true);
        window.ScriptEditor.clearOutput();
        // 注册页面退出监听，确保退出网页即强制终止脚本（幂等，只注册一次）
        setupExitWatching();

        // 显示运行命令行（终端风格）
        const scriptName = window.ScriptEditor.getCurrentFilename
            ? window.ScriptEditor.getCurrentFilename()
            : 'script';
        const runCmd = '▶ 运行: ' + scriptName;
        if (window.TerminalPanel) {
            window.TerminalPanel.appendCommandLine(runCmd);
        } else {
            window.ScriptEditor.appendOutput(runCmd, 'info');
        }

        // 使用 AbortController 以便在用户点击"强制终止"时切断前端连接
        currentFetchController = new AbortController();

        try {
            const resp = await fetch('/admin/script/run-script', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code }),
                signal: currentFetchController.signal,
            });

            if (!resp.ok) {
                let errMsg = 'HTTP ' + resp.status;
                try {
                    const errData = await resp.json();
                    if (errData && errData.message) errMsg = errData.message;
                } catch (_) { /* ignore */ }
                window.ScriptEditor.appendOutput('[错误] ' + errMsg, 'error');
                return;
            }

            // 解析 SSE 流（fetch + ReadableStream，因为 EventSource 不支持 POST）
            await consumeSseStream(resp);
        } catch (err) {
            if (err && err.name === 'AbortError') {
                window.ScriptEditor.appendOutput('[已请求终止脚本]', 'warning');
            } else {
                window.ScriptEditor.appendOutput('[网络错误] ' + (err.message || String(err)), 'error');
            }
        } finally {
            currentFetchController = null;
            setRunning(false);
        }
    }

    // ----------------------------------------------------------------
    // 消费 SSE 流：逐条解析 data: {...}\n\n 事件
    // ----------------------------------------------------------------
    async function consumeSseStream(resp) {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // SSE 事件以双换行分隔
            let idx;
            while ((idx = buffer.indexOf('\n\n')) !== -1) {
                const rawEvent = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                handleSseRawEvent(rawEvent);
            }
        }

        // 处理流结束时缓冲区中残留的最后一个事件
        // （后端可能在最后一个事件后未补 \n\n）
        if (buffer.trim()) {
            handleSseRawEvent(buffer);
        }
    }

    function handleSseRawEvent(rawEvent) {
        // 解析 data: ... 行（忽略 event:/id:/retry: 等）
        const lines = rawEvent.split('\n');
        let dataStr = '';
        for (const line of lines) {
            if (line.indexOf('data:') === 0) {
                dataStr += line.slice(5).replace(/^\s/, '');
            }
        }
        if (!dataStr) return;

        let msg;
        try {
            msg = JSON.parse(dataStr);
        } catch (e) {
            // 非 JSON 数据（如 [DONE] 标记），直接忽略
            return;
        }
        handleSseEvent(msg);
    }

    async function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};
        const appendOutput = window.ScriptEditor.appendOutput;

        switch (msg.type) {
            case 'output':
                appendOutput(data.text != null ? String(data.text) : '', 'script');
                break;
            case 'alert':
                // 显示弹窗，不需要回传响应（后端不等待）
                if (window.ScriptModal && window.ScriptModal.alert) {
                    window.ScriptModal.alert(data.title || '提示', data.message || '');
                }
                break;
            case 'prompt': {
                // 显示输入框，用户输入后回传响应
                let value = data.default || '';
                if (window.ScriptModal && window.ScriptModal.prompt) {
                    value = await window.ScriptModal.prompt(data.title || '输入', data.message || '', data.default || '');
                }
                await sendScriptResponse(value);
                break;
            }
            case 'confirm': {
                // 显示确认框，用户选择后回传响应
                let ok = false;
                if (window.ScriptModal && window.ScriptModal.confirm) {
                    ok = await window.ScriptModal.confirm(data.title || '确认', data.message || '');
                }
                await sendScriptResponse(!!ok);
                break;
            }
            case 'error':
                appendOutput('[错误] ' + (data.message || '未知错误'), 'error');
                break;
            case 'done':
                appendOutput('[脚本执行完毕]', 'info');
                break;
            default:
                // 未知事件类型，原样输出便于调试
                appendOutput('[事件:' + msg.type + '] ' + JSON.stringify(data), 'warning');
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
            window.ScriptEditor.appendOutput('[回传响应失败] ' + err.message, 'error');
        }
    }

    // ----------------------------------------------------------------
    // 强制终止：调用后端 abort API + 切断前端 SSE 连接
    // ----------------------------------------------------------------
    async function abortScript() {
        try {
            const resp = await fetch('/admin/script/abort-script', { method: 'POST' });
            const result = await resp.json();
            if (result.success) {
                window.ScriptEditor.appendOutput('[已发送终止请求]', 'warning');
            } else {
                window.ScriptEditor.appendOutput('[终止失败] ' + (result.message || '没有正在执行的脚本'), 'warning');
            }
        } catch (err) {
            window.ScriptEditor.appendOutput('[终止请求异常] ' + err.message, 'error');
        } finally {
            // 同时切断前端 SSE 连接，避免连接挂起
            if (currentFetchController) {
                currentFetchController.abort();
            }
        }
    }

    // ----------------------------------------------------------------
    // 运行状态切换：更新内部标记 + 通过 editor.js 更新按钮 UI
    // ----------------------------------------------------------------
    function setRunning(running) {
        isRunning = running;
        // 按钮显隐与样式由 editor.js 负责（_updateRunButton）
        if (window.ScriptEditor && window.ScriptEditor._updateRunButton) {
            window.ScriptEditor._updateRunButton(running);
        }
    }

    function getRunning() {
        return isRunning;
    }

    return {
        runScript: runScript,
        abortScript: abortScript,
        getRunning: getRunning,
    };
})();
