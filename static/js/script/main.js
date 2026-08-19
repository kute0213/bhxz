/**
 * 脚本控制台主入口
 *
 * 运行方式（弹窗终端）：
 *   - 快捷命令（Shell）：打开弹窗终端，把命令发送到共享 PTY 会话执行
 *   - 脚本（Python/MiniScript）：打开弹窗终端，后端 SSE 独立子进程执行
 *
 * 弹窗终端无独立入口，点击「运行」时自动打开（terminal-modal.js）。
 * 页面跳转逻辑已移除（原跳转独立实时终端页 terminal-page）。
 */
(function () {
    if (!window.ScriptTerminalModal) {
        console.error('[main.js] terminal-modal.js 未加载');
        return;
    }

    ScriptPresets.init({
        onRunCommand: function (cmd) {
            // 普通 Shell 快捷命令：在弹窗终端执行
            ScriptTerminalModal.runCommand(cmd.command);
        },
        onRunScript: function (cmd) {
            // 脚本：在弹窗终端加载并执行
            ScriptTerminalModal.runScript(cmd.id, cmd.name || '匿名脚本');
        }
    });

    if (window.lucide) lucide.createIcons();
})();