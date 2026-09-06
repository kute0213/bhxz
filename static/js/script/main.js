/**
 * 终端控制台主入口
 *
 * 运行方式（流式输出终端弹窗）：
 *   - 快捷命令（Shell）：打开流式输出终端弹窗，执行命令并通过 SSE 实时接收输出
 *
 * 弹窗终端无独立入口，点击「运行」时自动打开。
 */
(function () {
    'use strict';

    var terminalController = null;
    var modalEl = null;
    var screenEl = null;
    var closeBtn = null;

    function init() {
        modalEl = document.getElementById('term-modal');
        screenEl = document.getElementById('term-modal-screen');
        closeBtn = document.getElementById('term-modal-close');

        if (closeBtn) {
            closeBtn.addEventListener('click', closeModal);
        }
        if (modalEl) {
            modalEl.addEventListener('click', function (e) {
                if (e.target === modalEl) closeModal();
            });
        }
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modalEl && !modalEl.classList.contains('hidden')) {
                closeModal();
            }
        });

        // 初始化终端（但先不挂载到 DOM）
        ScriptPresets.init({
            onRunCommand: function (cmd) {
                openAndRun(cmd.command);
            }
        });

        if (window.lucide) lucide.createIcons();
    }

    function openAndRun(command) {
        if (!modalEl || !screenEl) return;

        // 显示弹窗
        modalEl.classList.remove('hidden');
        document.body.style.overflow = 'hidden';

        // 创建终端（如果尚未创建）
        if (!terminalController) {
            terminalController = StreamTerminal.attach(screenEl, {
                onFinish: function () {
                    // 执行完成后可做额外处理
                },
                onStart: function () {
                    // 开始执行时
                },
            });
        }

        // 聚焦并执行
        setTimeout(function () {
            if (terminalController) {
                terminalController.setCommand(command);
                terminalController.focus();
            }
        }, 100);
    }

    function closeModal() {
        if (!modalEl) return;
        modalEl.classList.add('hidden');
        document.body.style.overflow = '';
    }

    document.addEventListener('DOMContentLoaded', init);
})();