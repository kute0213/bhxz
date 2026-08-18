/**
 * 脚本控制台主入口
 *
 * 弹窗终端已彻底移除，统一跳转到独立实时终端页：
 *   - 快捷命令（Shell）：跳转 /admin/script/terminal-page?cmd=... 自动执行
 *   - 脚本（Python/MiniScript）：跳转 /admin/script/terminal-page?script=... 自动执行
 *
 * 运行/输出均在独立实时终端页完成（terminal-page.js）。
 */

(function () {
    ScriptPresets.init({
        onRunCommand: function (cmd) {
            // 普通 Shell 快捷命令：跳转独立实时终端页并自动执行
            window.location.href = '/admin/script/terminal-page?cmd=' + encodeURIComponent(cmd.command);
        },
        onRunScript: function (cmd) {
            // 脚本：跳转独立实时终端页，加载并执行
            var id = cmd.id || '';
            var name = cmd.name || '匿名脚本';
            window.location.href = '/admin/script/terminal-page?script=' +
                encodeURIComponent(id) + '&name=' + encodeURIComponent(name);
        }
    });

    if (window.lucide) lucide.createIcons();
})();