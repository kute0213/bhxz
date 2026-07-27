/**
 * CMD 控制台主入口
 *
 * 整合各模块：终端弹窗 + 快捷命令 + 后端脚本执行（SSE）
 *
 * 脚本不再在前端解释执行，统一通过后端 SSE API（/admin/cmd/run-script）执行，
 * 输出显示到 CmdTerminal，交互事件（alert/prompt/confirm）使用 CmdModal 弹窗。
 */

(function () {
    const terminalBtn = document.getElementById('open-terminal-btn');

    // --------------------------------------------------------
    // 初始化终端
    // --------------------------------------------------------
    CmdTerminal.init();

    terminalBtn.addEventListener('click', () => {
        CmdTerminal.open();
    });

    // --------------------------------------------------------
    // 初始化快捷命令
    // --------------------------------------------------------
    CmdPresets.init({
        onRunCommand: function (cmd) {
            // 普通 CMD：打开终端并执行（连接未就绪时命令会自动排队）
            if (!CmdTerminal.isOpen()) {
                CmdTerminal.open();
            }
            // runCommand 会显示命令回显并发送（连接未就绪时自动排队）
            CmdTerminal.runCommand(cmd.command);
        },
        onRunScript: function (cmd) {
            // 脚本：通过后端 SSE API 执行
            runScript(cmd.command, cmd.name);
        }
    });

    // --------------------------------------------------------
    // 通过后端 SSE API 执行脚本
    // --------------------------------------------------------
    // 模块级状态：当前正在运行的脚本 SSE 请求控制器
    let currentFetchController = null;

    function runScript(code, name) {
        // 确保终端是打开的（用于显示输出）
        if (!CmdTerminal.isOpen()) {
            CmdTerminal.open(function () {
                // 终端关闭时：调用后端 abort API 终止脚本 + 切断前端 SSE 连接
                abortRunningScript();
            });
        } else {
            // 终端已打开时，更新关闭回调
            CmdTerminal.setOnClose(function () {
                abortRunningScript();
            });
        }

        CmdTerminal.appendLine('运行脚本: ' + (name || '匿名'), 'script');

        // 标记终端为"脚本运行中"（显示中止按钮）
        CmdTerminal.setScriptRunning(true);

        // 启动 SSE 执行
        executeScriptViaSse(code);
    }

    async function executeScriptViaSse(code) {
        // 切断上一次未结束的 SSE 连接
        if (currentFetchController) {
            currentFetchController.abort();
        }
        currentFetchController = new AbortController();

        try {
            const resp = await fetch('/admin/cmd/run-script', {
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
                CmdTerminal.appendLine('[错误] ' + errMsg, 'error');
                CmdTerminal.setScriptRunning(false);
                return;
            }

            await consumeSseStream(resp);
        } catch (err) {
            if (err && err.name === 'AbortError') {
                CmdTerminal.appendLine('[已请求终止脚本]', 'script');
            } else {
                CmdTerminal.appendLine('[网络错误] ' + (err.message || String(err)), 'error');
            }
        } finally {
            currentFetchController = null;
            CmdTerminal.setScriptRunning(false);
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
                await handleSseRawEvent(rawEvent);
            }
        }
    }

    async function handleSseRawEvent(rawEvent) {
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
        await handleSseEvent(msg);
    }

    async function handleSseEvent(msg) {
        if (!msg || !msg.type) return;
        const data = msg.data || {};

        switch (msg.type) {
            case 'output':
                CmdTerminal.appendLine(data.text != null ? String(data.text) : '', 'script');
                break;
            case 'alert':
                // 显示弹窗，不需要回传响应
                if (window.CmdModal && window.CmdModal.alert) {
                    window.CmdModal.alert(data.title || '提示', data.message || '');
                }
                break;
            case 'prompt': {
                let value = data.default || '';
                if (window.CmdModal && window.CmdModal.prompt) {
                    value = await window.CmdModal.prompt(data.title || '输入', data.message || '', data.default || '');
                }
                await sendScriptResponse(value);
                break;
            }
            case 'confirm': {
                let ok = false;
                if (window.CmdModal && window.CmdModal.confirm) {
                    ok = await window.CmdModal.confirm(data.title || '确认', data.message || '');
                }
                await sendScriptResponse(!!ok);
                break;
            }
            case 'error':
                CmdTerminal.appendLine('[错误] ' + (data.message || '未知错误'), 'error');
                break;
            case 'done':
                CmdTerminal.appendLine('[脚本执行完毕]', 'script');
                break;
            default:
                CmdTerminal.appendLine('[事件:' + msg.type + '] ' + JSON.stringify(data), 'error');
        }
    }

    async function sendScriptResponse(value) {
        try {
            await fetch('/admin/cmd/script-response', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: value }),
            });
        } catch (err) {
            CmdTerminal.appendLine('[回传响应失败] ' + err.message, 'error');
        }
    }

    // ----------------------------------------------------------------
    // 终止当前正在执行的脚本：调用后端 abort API + 切断前端 SSE 连接
    // ----------------------------------------------------------------
    async function abortRunningScript() {
        try {
            await fetch('/admin/cmd/abort-script', { method: 'POST' });
        } catch (err) {
            // 忽略网络错误，继续切断前端连接
        }
        if (currentFetchController) {
            currentFetchController.abort();
        }
    }

    // --------------------------------------------------------
    // 暴露给 terminal.js 调用的中止函数（终端弹窗里的中止按钮）
    // --------------------------------------------------------
    window.__abortCmdScript = abortRunningScript;

    // --------------------------------------------------------
    // Lucide 图标
    // --------------------------------------------------------
    if (window.lucide) lucide.createIcons();
})();
