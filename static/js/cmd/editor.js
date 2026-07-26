/**
 * 脚本编辑器核心（Python 后端执行版 + 文件系统脚本管理）
 *
 * 功能：
 *   - Monaco Editor 初始化与配置
 *   - 工具栏事件绑定（运行/保存/格式化/清空）
 *   - 快捷键绑定（Ctrl+Enter 运行、Ctrl+S 保存）
 *   - 输出面板可折叠（展开/收起，localStorage 记忆）
 *   - 脚本自动保存（防抖 2 秒）
 *   - 脚本文件保存到文件系统
 *   - 输出面板
 *
 * 暴露：window.ScriptEditor
 *      公共 API：init / appendOutput / clearOutput
 *      内部辅助：getEditor / _updateRunButton（供 editor-sse.js 使用）
 *
 * 配套文件（必须在 editor.js 之前加载）：
 *   - editor-highlight.js → window.ScriptEditorHighlight
 *   - editor-sse.js       → window.ScriptEditorSse
 *
 * 依赖：Monaco Editor、CmdModal（window.CmdModal）
 */
window.ScriptEditor = (function () {

    // ==================================================================
    // 内部状态
    // ==================================================================
    let editor = null;          // Monaco Editor 实例
    let editingCmdId = null;    // 当前编辑的数据库快捷命令 ID（兼容旧模式）
    let editingFilename = null; // 当前编辑的脚本文件名（文件系统模式）

    // 自动保存相关
    let autoSaveTimer = null;   // 防抖定时器
    let autoSaveEnabled = false; // 是否启用自动保存

    // 高亮 / SSE 模块的快捷访问（运行时解析，避免加载顺序耦合）
    function HL() { return window.ScriptEditorHighlight; }
    function SSE() { return window.ScriptEditorSse; }

    // ==================================================================
    // 编辑器初始化
    // ==================================================================
    function init(initialCode, options) {
        options = options || {};
        editingCmdId = options.cmdId || null;
        editingFilename = options.filename || null;

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
        // 注册前端实时语法诊断：监听内容变化、设置 markers、更新状态栏徽章
        HLmod.registerDiagnostics(editor);

        // 状态栏：光标位置
        editor.onDidChangeCursorPosition(function (e) {
            const el = document.getElementById('editor-cursor-pos');
            if (el) el.textContent = '行 ' + e.position.lineNumber + ', 列 ' + e.position.column;
        });

        // 更新标题
        updateEditorTitle();

        // 初始化输出面板折叠
        initOutputToggle();
        // 初始化自动保存
        initAutoSave();

        // 如果是打开已有文件，启用自动保存
        if (editingFilename) {
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

        if (editingFilename) {
            titleEl.textContent = '编辑脚本：' + editingFilename;
        } else if (editingCmdId) {
            titleEl.textContent = '编辑快捷命令';
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

        // 从 localStorage 恢复折叠状态（默认展开）
        const collapsed = localStorage.getItem('editor-output-collapsed') === 'true';
        if (collapsed) {
            panel.classList.add('collapsed');
        }

        toggleBtn.addEventListener('click', function () {
            panel.classList.toggle('collapsed');
            const isCollapsed = panel.classList.contains('collapsed');
            localStorage.setItem('editor-output-collapsed', isCollapsed ? 'true' : 'false');
            // 通知 Monaco 重新布局（编辑器高度变化）
            setTimeout(function () {
                if (editor) editor.layout();
            }, 260);
        });
    }

    // ==================================================================
    // 自动保存
    // ==================================================================
    function initAutoSave() {
        if (!editor) return;
        editor.onDidChangeModelContent(function () {
            // 只有编辑已有文件且启用自动保存时才触发
            if (editingFilename && autoSaveEnabled) {
                scheduleAutoSave();
            }
        });
    }

    function scheduleAutoSave() {
        // 更新状态指示器为"已修改"
        updateSaveStatus('modified');
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(function () {
            doAutoSave();
        }, 2000);
    }

    async function doAutoSave() {
        if (!editingFilename) return;
        updateSaveStatus('saving');
        appendOutput('[正在保存...]', 'info');
        const code = editor.getValue();
        try {
            const resp = await fetch('/admin/cmd/scripts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: editingFilename, content: code })
            });
            const result = await resp.json();
            if (result.success) {
                updateSaveStatus('saved');
                appendOutput('[已保存] ' + editingFilename, 'info');
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
    // 保存脚本（到文件系统）
    // ==================================================================
    async function saveScript() {
        const code = editor.getValue();
        if (!code.trim()) {
            appendOutput('[错误] 脚本为空，无法保存', 'error');
            return;
        }

        // 已有文件名：直接保存
        if (editingFilename) {
            await doSave(editingFilename, code);
            return;
        }

        // 新脚本：只弹一次 prompt 输入名称
        let name = '';
        if (window.CmdModal && window.CmdModal.prompt) {
            name = await window.CmdModal.prompt('保存脚本', '请输入脚本名称：', '');
        } else {
            name = prompt('请输入脚本名称：', '');
        }
        if (!name) return;
        await doSave(null, code, name);
    }

    async function doSave(filename, content, name, description) {
        const data = {
            content: content,
            name: name || undefined,
            description: description || undefined,
        };
        if (filename) {
            data.filename = filename;
        }

        try {
            const resp = await fetch('/admin/cmd/scripts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await resp.json();
            if (result.success && result.script) {
                editingFilename = result.script.filename;
                editingCmdId = null;
                autoSaveEnabled = true; // 保存成功后启用自动保存
                updateEditorTitle();
                // 更新 URL
                history.replaceState(null, '', '?file=' + encodeURIComponent(result.script.filename));
                updateSaveStatus('saved');
                appendOutput('[已保存] ' + result.script.filename, 'info');
            } else {
                updateSaveStatus('error');
                appendOutput('[保存失败] ' + (result.message || '未知错误'), 'error');
            }
        } catch (err) {
            updateSaveStatus('error');
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
