/**
 * CMD 控制台主入口
 *
 * 整合各模块：终端弹窗 + 快捷命令 + MiniScript 脚本引擎
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
            // 普通 CMD：打开终端并执行
            CmdTerminal.open();
            setTimeout(() => CmdTerminal.runCommand(cmd.command), 100);
        },
        onRunScript: function (cmd) {
            // 脚本：直接在前端解释执行
            runScript(cmd.command, cmd.name);
        }
    });

    function runScript(code, name) {
        // 如果有正在运行的脚本，先中止它
        if (window.MiniScript && window.MiniScript.isRunning()) {
            MiniScript.abort();
        }

        // 清理所有旧的定时器，防止上一个脚本的定时器继续运行
        if (window.MiniScript && window.MiniScript.clearAllTimers) {
            MiniScript.clearAllTimers();
        }

        // 确保终端是打开的（用于显示输出）
        if (!CmdTerminal.isOpen()) {
            CmdTerminal.open(function () {
                // 终端关闭时：中止脚本 + 清理所有定时器
                if (window.MiniScript) {
                    if (window.MiniScript.abort) MiniScript.abort();
                    if (window.MiniScript.clearAllTimers) MiniScript.clearAllTimers();
                }
            });
        } else {
            // 终端已打开时，更新关闭回调
            CmdTerminal.setOnClose(function () {
                if (window.MiniScript) {
                    if (window.MiniScript.abort) MiniScript.abort();
                    if (window.MiniScript.clearAllTimers) MiniScript.clearAllTimers();
                }
            });
        }

        CmdTerminal.appendLine('运行脚本: ' + (name || '匿名'), 'script');

        // 标记终端为"脚本运行中"（显示中止按钮）
        CmdTerminal.setScriptRunning(true);

        // 注入 cmd / cmd_sync 内置函数
        const buildins = {
            cmd_sync: function (command) {
                return new Promise((resolve) => {
                    // 10 秒超时保护
                    const controller = new AbortController();
                    const cmdTimeout = setTimeout(function () {
                        controller.abort();
                        resolve('[cmd_sync 超时]');
                    }, 10000);

                    fetch('/admin/cmd/run', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ command: command }),
                        signal: controller.signal
                    }).then(r => r.json()).then(data => {
                        clearTimeout(cmdTimeout);
                        resolve(data.output || data.error || '');
                    }).catch(err => {
                        clearTimeout(cmdTimeout);
                        if (err.name === 'AbortError') return; // 已被超时处理
                        resolve('[网络错误] ' + err.message);
                    });
                });
            },
            cmd: function (command) {
                // cmd() 直接在终端流式执行并等待完成
                return new Promise((resolve) => {
                    let fullOutput = '';
                    const url = '/admin/cmd/run-stream?command=' + encodeURIComponent(command);
                    const es = new EventSource(url);

                    // 15 秒超时保护，防止 EventSource 连接挂起
                    const cmdTimeout = setTimeout(function () {
                        es.close();
                        CmdTerminal.appendLine('[cmd 超时，已自动断开]', 'error');
                        resolve(fullOutput);
                    }, 15000);

                    es.onmessage = function (e) {
                        if (e.data === '[DONE]') {
                            es.close();
                            clearTimeout(cmdTimeout);
                            resolve(fullOutput);
                            return;
                        }
                        try {
                            const evt = JSON.parse(e.data);
                            if (evt.type === 'output') {
                                fullOutput += evt.line + '\n';
                                CmdTerminal.appendLine(evt.line);
                            } else if (evt.type === 'exit') {
                                CmdTerminal.appendLine(evt.code, 'exit');
                            } else if (evt.type === 'error') {
                                CmdTerminal.appendLine('[错误] ' + evt.message, 'error');
                            }
                        } catch (err) {
                            fullOutput += e.data + '\n';
                            CmdTerminal.appendLine(e.data);
                        }
                    };

                    es.onerror = function () {
                        es.close();
                        clearTimeout(cmdTimeout);
                        resolve(fullOutput);
                    };
                });
            },
            echo: function (msg) {
                const formatted = window.MiniScript.formatValue ? window.MiniScript.formatValue(msg) : String(msg);
                CmdTerminal.appendLine(formatted, 'script');
                return msg;
            }
        };

        MiniScript.run(code, buildins).then(() => {
            CmdTerminal.appendLine('[脚本执行完毕]', 'script');
        }).catch(err => {
            // 区分手动中止、超时中止和其他错误
            if (err.message && err.message.indexOf('手动中止') !== -1) {
                CmdTerminal.appendLine('[脚本已中止]', 'script');
            } else {
                CmdTerminal.appendLine('[脚本错误] ' + err.message, 'error');
            }
        }).finally(() => {
            // 脚本结束后，仅在没有活跃定时器时隐藏中止按钮
            if (window.MiniScript && window.MiniScript.hasActiveTimers && MiniScript.hasActiveTimers()) {
                CmdTerminal.appendLine('[脚本已结束，但有定时器仍在运行，点击中止可停止]', 'script');
            } else {
                CmdTerminal.setScriptRunning(false);
            }
        });
    }

    // --------------------------------------------------------
    // Lucide 图标
    // --------------------------------------------------------
    if (window.lucide) lucide.createIcons();
})();
