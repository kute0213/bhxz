/**
 * 终端控制台主入口
 *
 * 运行方式（弹窗终端）：
 *   - 快捷命令（Shell）：打开弹窗终端，把命令发送到共享 PTY 会话执行
 *
 * 弹窗终端无独立入口，点击「运行」时自动打开（terminal-modal.js）。
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
        }
    });

    if (window.lucide) lucide.createIcons();
})();