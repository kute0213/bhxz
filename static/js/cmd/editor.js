/**
 * 脚本编辑器核心（Python 后端执行版）
 *
 * 由原 editor.js 拆分而来，本文件负责：
 *   - Monaco Editor 初始化与配置
 *   - 工具栏事件绑定（运行/保存/格式化/清空/示例）
 *   - 快捷键绑定（Ctrl+Enter 运行、Ctrl+S 保存）
 *   - 保存为快捷命令
 *   - 输出面板（appendOutput / clearOutput）
 *   - 运行状态按钮 UI 切换（_updateRunButton，供 editor-sse.js 调用）
 *
 * 暴露：window.ScriptEditor
 *      公共 API：init / appendOutput / clearOutput（与原接口保持兼容）
 *      内部辅助：getEditor / _updateRunButton（供 editor-sse.js 使用）
 *
 * 配套文件（必须在 editor.js 之前加载）：
 *   - editor-highlight.js → window.ScriptEditorHighlight（主题/补全/示例）
 *   - editor-sse.js       → window.ScriptEditorSse（运行/终止）
 *
 * 依赖：Monaco Editor、CmdModal（window.CmdModal）
 */
window.ScriptEditor = (function () {

    // ==================================================================
    // 内部状态
    // ==================================================================
    let editor = null;          // Monaco Editor 实例
    let editingCmdId = null;    // 当前编辑的快捷命令 ID（null=新建）

    // 高亮 / SSE 模块的快捷访问（运行时解析，避免加载顺序耦合）
    function HL() { return window.ScriptEditorHighlight; }
    function SSE() { return window.ScriptEditorSse; }

    // ==================================================================
    // 编辑器初始化
    // ==================================================================
    function init(initialCode, cmdId) {
        editingCmdId = cmdId || null;

        // 注册主题、补全、悬浮（来自 editor-highlight.js）
        const HLmod = HL();
        HLmod.registerTheme();
        HLmod.registerCompletion();
        HLmod.registerHover();

        const container = document.getElementById('monaco-editor');
        editor = monaco.editor.create(container, {
            value: initialCode || '',
            language: 'python',
            theme: 'pythonDark',
            automaticLayout: true,
            fontSize: 14,
            lineHeight: 22,
            fontFamily: '"JetBrains Mono", "Fira Code", "Consolas", monospace',
            fontLigatures: true,
            minimap: { enabled: true, maxColumn: 80 },
            lineNumbers: 'on',
            roundedSelection: true,
            scrollBeyondLastLine: false,
            tabSize: 4,
            insertSpaces: true,
            wordWrap: 'on',
            bracketPairColorization: { enabled: true },
            guides: { bracketPairs: true, indentation: true },
            suggestOnTriggerCharacters: true,
            quickSuggestions: { other: true, comments: false, strings: false },
            formatOnPaste: true,
            formatOnType: true,
            autoIndent: 'full',
            cursorBlinking: 'smooth',
            cursorSmoothCaretAnimation: 'on',
            smoothScrolling: true,
            mouseWheelZoom: true,
            multiCursorModifier: 'ctrlCmd',
            renderWhitespace: 'selection',
            renderLineHighlight: 'all',
            scrollbar: {
                vertical: 'auto',
                horizontal: 'auto',
                verticalScrollbarSize: 10,
                horizontalScrollbarSize: 10,
            },
        });

        bindToolbar();
        bindShortcuts();
        HLmod.updateStatusBadge(0);

        // 状态栏：光标位置
        editor.onDidChangeCursorPosition(function (e) {
            const el = document.getElementById('editor-cursor-pos');
            if (el) el.textContent = '行 ' + e.position.lineNumber + ', 列 ' + e.position.column;
        });

        // 如果是编辑已有命令，更新标题
        if (cmdId) {
            const titleEl = document.getElementById('editor-title');
            if (titleEl) titleEl.textContent = '编辑快捷命令';
        }
    }

    // ==================================================================
    // 工具栏绑定
    // ==================================================================
    function bindToolbar() {
        document.getElementById('editor-run-btn').addEventListener('click', SSE().runScript);
        document.getElementById('editor-save-btn').addEventListener('click', saveAsCommand);
        document.getElementById('editor-clear-output-btn').addEventListener('click', clearOutput);
        document.getElementById('editor-format-btn').addEventListener('click', formatCode);
        document.getElementById('editor-example-btn').addEventListener('click', toggleExamples);

        // 强制终止按钮（运行时显示，默认隐藏）
        const abortBtn = document.getElementById('editor-abort-btn');
        if (abortBtn) {
            abortBtn.addEventListener('click', SSE().abortScript);
            abortBtn.style.display = 'none';
        }

        // 示例列表
        const exList = document.getElementById('editor-example-list');
        if (exList) {
            Object.keys(HL().EXAMPLES).forEach(function (name) {
                const item = document.createElement('button');
                item.className = 'block w-full text-left px-4 py-2 text-sm text-cream/80 hover:bg-gold-400/10 hover:text-gold-400 transition-colors';
                item.textContent = name;
                item.addEventListener('click', function () {
                    if (window.CmdModal && window.CmdModal.confirm) {
                        window.CmdModal.confirm('加载示例', '将用示例代码替换当前内容，确定继续吗？').then(function (ok) {
                            if (ok) {
                                editor.setValue(HL().EXAMPLES[name]);
                                exList.classList.add('hidden');
                            }
                        });
                    } else if (confirm('将用示例代码替换当前内容，确定继续吗？')) {
                        editor.setValue(HL().EXAMPLES[name]);
                        exList.classList.add('hidden');
                    }
                });
                exList.appendChild(item);
            });
        }
    }

    function toggleExamples() {
        const exList = document.getElementById('editor-example-list');
        if (exList) exList.classList.toggle('hidden');
    }

    function bindShortcuts() {
        editor.addAction({
            id: 'run-script',
            label: '运行脚本',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
            run: function () { SSE().runScript(); }
        });

        editor.addAction({
            id: 'save-command',
            label: '保存为快捷命令',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
            run: function () { saveAsCommand(); }
        });
    }

    // ==================================================================
    // 保存为快捷命令
    // ==================================================================
    async function saveAsCommand() {
        const code = editor.getValue();
        if (!code.trim()) {
            appendOutput('[错误] 脚本为空，无法保存', 'error');
            return;
        }

        let name;
        let desc;
        if (window.CmdModal && window.CmdModal.prompt) {
            name = await window.CmdModal.prompt('保存为快捷命令', '请输入命令名称：', '');
            if (!name) return;
            desc = await window.CmdModal.prompt('描述（可选）', '请输入简短描述：', '');
        } else {
            name = prompt('请输入命令名称：', '');
            if (!name) return;
            desc = prompt('描述（可选）：', '') || '';
        }

        // 描述以 [脚本] 开头标记为脚本类型
        let fullDesc = desc || '';
        if (fullDesc.indexOf('[脚本]') !== 0) {
            fullDesc = '[脚本] ' + fullDesc;
        }

        const data = {
            name: name,
            command: code,
            description: fullDesc,
            sort_order: 0
        };

        // 如果是编辑现有命令，则更新
        const url = editingCmdId ? '/admin/cmd/commands/' + editingCmdId : '/admin/cmd/commands';
        const method = editingCmdId ? 'PUT' : 'POST';

        try {
            const resp = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await resp.json();
            if (result.success) {
                appendOutput('[已保存为快捷命令] ' + name, 'info');
                if (result.id) editingCmdId = result.id;
            } else {
                appendOutput('[保存失败] ' + (result.message || '未知错误'), 'error');
            }
        } catch (err) {
            appendOutput('[网络错误] ' + err.message, 'error');
        }
    }

    // ==================================================================
    // 输出面板（供 editor-sse.js 与本模块共用）
    // ==================================================================
    function appendOutput(text, type) {
        const panel = document.getElementById('editor-output');
        if (!panel) return;
        const line = document.createElement('div');
        line.textContent = text;
        const colorMap = {
            'info': '#60a5fa',
            'error': '#f87171',
            'warning': '#fbbf24',
            'script': '#a3e635',
            'exit': '#94a3b8',
            'default': '#4ade80',
        };
        line.style.color = colorMap[type] || colorMap.default;
        line.style.padding = '1px 0';
        panel.appendChild(line);
        panel.scrollTop = panel.scrollHeight;
    }

    function clearOutput() {
        const panel = document.getElementById('editor-output');
        if (panel) panel.innerHTML = '';
    }

    function formatCode() {
        editor.getAction('editor.action.formatDocument').run();
    }

    // ==================================================================
    // 运行状态按钮 UI 切换（供 editor-sse.js 的 setRunning 调用）
    // ==================================================================
    function _updateRunButton(running) {
        const runBtn = document.getElementById('editor-run-btn');
        const abortBtn = document.getElementById('editor-abort-btn');

        if (running) {
            runBtn.classList.add('opacity-50', 'cursor-not-allowed');
            runBtn.disabled = true;
            if (abortBtn) abortBtn.style.display = '';
        } else {
            runBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            runBtn.disabled = false;
            if (abortBtn) abortBtn.style.display = 'none';
        }
        if (window.lucide) lucide.createIcons();
    }

    // ==================================================================
    // 公共 API（保持与原 editor.js 接口兼容）
    // ==================================================================
    return {
        init: init,
        appendOutput: appendOutput,
        clearOutput: clearOutput,
        // 以下为拆分后供 editor-sse.js 使用的内部辅助
        getEditor: function () { return editor; },
        _updateRunButton: _updateRunButton,
    };
})();
