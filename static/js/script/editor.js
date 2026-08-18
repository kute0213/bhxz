/**
 * 脚本编辑器核心（统一脚本存储系统）
 *
 * 功能：
 *   - Monaco Editor 初始化与配置
 *   - 工具栏事件绑定（运行/保存/格式化/清空）
 *   - 快捷键绑定（Ctrl+Enter 运行、Ctrl+S 保存）
 *   - 终端面板可折叠（展开/收起，localStorage 记忆）
 *   - 脚本自动保存（防抖 2 秒）
 *   - 统一脚本存储：数据库 + 文件系统，自动命名（日期_序号）
 *
 * 暴露：window.ScriptEditor
 *      公共 API：init / appendOutput / clearOutput
 *      内部辅助：getEditor / _updateRunButton（供 editor-sse.js 使用）
 *
 * 配套文件（必须在 editor.js 之前加载）：
 *   - editor-highlight.js → window.ScriptEditorHighlight
 *   - editor-sse.js       → window.ScriptEditorSse
 *   - editor-terminal.js  → window.TerminalPanel
 *
 * 依赖：Monaco Editor、ScriptModal（window.ScriptModal）
 */
window.ScriptEditor = (function () {

    // ==================================================================
    // 内部状态
    // ==================================================================
    let editor = null;              // Monaco Editor 实例
    let editingScript = null;       // 当前编辑的脚本信息 {id, name, script_type, description}

    // 自动保存相关
    let autoSaveTimer = null;
    let autoSaveEnabled = false;

    // 高亮 / SSE 模块的快捷访问（运行时解析，避免加载顺序耦合）
    function HL() { return window.ScriptEditorHighlight; }
    function SSE() { return window.ScriptEditorSse; }

    // ==================================================================
    // 编辑器初始化
    // ==================================================================
    function init(initialCode, options) {
        options = options || {};
        editingScript = options.script || null;

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
        HLmod.registerDiagnostics(editor);

        // 状态栏：光标位置
        editor.onDidChangeCursorPosition(function (e) {
            const el = document.getElementById('editor-cursor-pos');
            if (el) el.textContent = '行 ' + e.position.lineNumber + ', 列 ' + e.position.column;
        });

        updateEditorTitle();

        // 初始化输出面板折叠
        initOutputToggle();
        // 初始化终端
        if (window.TerminalPanel) {
            window.TerminalPanel.init();
        }
        // 初始化自动保存
        initAutoSave();

        // 如果是打开已有脚本，启用自动保存
        if (editingScript && editingScript.id) {
            autoSaveEnabled = true;
            updateSaveStatus('saved');
        }
    }

    // ==================================================================
    // 标题更新
    // ==================================================================
    function updateEditorTitle() {
        const titleEl = document.getElementById('editor-title');
        if (!titleEl) return;

        if (editingScript && editingScript.name) {
            titleEl.textContent = '编辑：' + editingScript.name;
        } else {
            titleEl.textContent = '脚本编辑器';
        }
    }

    // ==================================================================
    // 工具栏绑定
    // ==================================================================
    function bindToolbar() {
        document.getElementById('editor-run-btn').addEventListener('click', SSE().runScript);
        document.getElementById('editor-save-btn').addEventListener('click', saveScript);
        document.getElementById('editor-clear-output-btn').addEventListener('click', clearOutput);
        document.getElementById('editor-format-btn').addEventListener('click', formatCode);

        // 强制终止按钮（运行时显示，默认隐藏）
        const abortBtn = document.getElementById('editor-abort-btn');
        if (abortBtn) {
            abortBtn.addEventListener('click', SSE().abortScript);
            abortBtn.style.display = 'none';
        }
    }

    function bindShortcuts() {
        editor.addAction({
            id: 'run-script',
            label: '运行脚本',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
            run: function () { SSE().runScript(); }
        });

        editor.addAction({
            id: 'save-script',
            label: '保存脚本',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
            run: function () { saveScript(); }
        });
    }

    // ==================================================================
    // 输出面板折叠
    // ==================================================================
    function initOutputToggle() {
        const panel = document.getElementById('output-panel');
        const toggleBtn = document.getElementById('output-toggle-btn');
        if (!panel || !toggleBtn) return;

        const collapsed = localStorage.getItem('editor-output-collapsed') === 'true';
        if (collapsed) {
            panel.classList.add('collapsed');
        }

        toggleBtn.addEventListener('click', function () {
            panel.classList.toggle('collapsed');
            const isCollapsed = panel.classList.contains('collapsed');
            localStorage.setItem('editor-output-collapsed', isCollapsed ? 'true' : 'false');
            setTimeout(function () {
                if (editor) editor.layout();
            }, 260);
            // 展开时若终端未连接，立即重连
            if (!isCollapsed && window.TerminalPanel && typeof window.TerminalPanel.reconnect === 'function') {
                window.TerminalPanel.reconnect();
            }
        });
    }

    // ==================================================================
    // 自动保存
    // ==================================================================
    function initAutoSave() {
        if (!editor) return;
        editor.onDidChangeModelContent(function () {
            // 只有编辑已有脚本且启用自动保存时才触发
            if (editingScript && editingScript.id && autoSaveEnabled) {
                scheduleAutoSave();
            }
        });
    }

    function scheduleAutoSave() {
        updateSaveStatus('modified');
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(function () {
            doAutoSave();
        }, 2000);
    }

    async function doAutoSave() {
        if (!editingScript || !editingScript.id) return;
        updateSaveStatus('saving');
        const code = editor.getValue();
        try {
            const resp = await fetch('/admin/script/scripts/' + editingScript.id, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: code })
            });
            const result = await resp.json();
            if (result.success) {
                updateSaveStatus('saved');
                if (result.script) {
                    editingScript = result.script;
                }
            } else {
                updateSaveStatus('error');
                appendOutput('[自动保存失败] ' + (result.message || '未知错误'), 'error');
            }
        } catch (err) {
            updateSaveStatus('error');
            appendOutput('[自动保存失败] ' + err.message, 'error');
        }
    }

    function updateSaveStatus(status) {
        const indicator = document.getElementById('save-status-indicator');
        const text = document.getElementById('save-status-text');
        if (!indicator) return;
        const statusMap = {
            'modified': { color: '#fbbf24', text: '已修改' },
            'saving': { color: '#60a5fa', text: '保存中...' },
            'saved': { color: '#4ade80', text: '已保存' },
            'error': { color: '#f87171', text: '保存失败' },
        };
        const s = statusMap[status] || statusMap.saved;
        indicator.style.background = s.color;
        if (text) text.textContent = s.text;
    }

    // ==================================================================
    // 保存脚本（统一存储系统）
    // ==================================================================
    async function saveScript() {
        const code = editor.getValue();
        if (!code.trim()) {
            appendOutput('[错误] 脚本为空，无法保存', 'error');
            return;
        }

        // 已有脚本：直接更新
        if (editingScript && editingScript.id) {
            await doUpdateScript(editingScript.id, code);
            return;
        }

        // 新脚本：弹输入框输入名称和备注
        let name = '';
        if (window.ScriptModal && window.ScriptModal.prompt) {
            name = await window.ScriptModal.prompt('保存脚本', '请输入脚本名称：', '');
        } else {
            name = prompt('请输入脚本名称：', '');
        }
        if (!name) return;

        // 备注可选
        let description = '';
        if (window.ScriptModal && window.ScriptModal.prompt) {
            description = await window.ScriptModal.prompt('保存脚本', '请输入脚本备注（可选）：', '');
        } else {
            description = prompt('请输入脚本备注（可选）：', '') || '';
        }

        await doCreateScript(name, code, description);
    }

    async function doCreateScript(name, content, description) {
        try {
            const resp = await fetch('/admin/script/scripts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    content: content,
                    description: description || '',
                    script_type: 'miniscript',
                })
            });
            const result = await resp.json();
            if (result.success && result.script) {
                editingScript = result.script;
                autoSaveEnabled = true;
                updateEditorTitle();
                history.replaceState(null, '', '?id=' + result.script.id);
                updateSaveStatus('saved');
                appendOutput('[已保存] ' + result.script.name + ' (ID: ' + result.script.id + ')', 'info');
            } else {
                updateSaveStatus('error');
                appendOutput('[保存失败] ' + (result.message || '未知错误'), 'error');
            }
        } catch (err) {
            updateSaveStatus('error');
            appendOutput('[网络错误] ' + err.message, 'error');
        }
    }

    async function doUpdateScript(id, content, name, description) {
        const data = { content: content };
        if (name !== undefined) data.name = name;
        if (description !== undefined) data.description = description;

        try {
            const resp = await fetch('/admin/script/scripts/' + id, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await resp.json();
            if (result.success && result.script) {
                editingScript = result.script;
                updateEditorTitle();
                updateSaveStatus('saved');
                return true;
            } else {
                updateSaveStatus('error');
                appendOutput('[保存失败] ' + (result.message || '未知错误'), 'error');
                return false;
            }
        } catch (err) {
            updateSaveStatus('error');
            appendOutput('[网络错误] ' + err.message, 'error');
            return false;
        }
    }

    // ==================================================================
    // 输出面板（供 editor-sse.js 与本模块共用）
    // 优先使用 TerminalPanel，若无则回退到直接 DOM 操作
    // ==================================================================
    function appendOutput(text, type) {
        if (window.TerminalPanel) {
            if (type === 'script' || type === 'default') {
                window.TerminalPanel.appendOutput(text);
            } else {
                window.TerminalPanel.appendLine(text, type);
            }
            return;
        }
        // 回退：直接 DOM 操作
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
        if (window.TerminalPanel) {
            window.TerminalPanel.clear();
            return;
        }
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
    // 公共 API（保持接口兼容）
    // ==================================================================
    return {
        init: init,
        appendOutput: appendOutput,
        clearOutput: clearOutput,
        getCurrentFilename: function () {
            return (editingScript && editingScript.name) || 'untitled';
        },
        getScriptInfo: function () {
            return editingScript;
        },
        getEditor: function () { return editor; },
        _updateRunButton: _updateRunButton,
    };
})();
