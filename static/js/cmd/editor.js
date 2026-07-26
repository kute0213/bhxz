/**
 * 脚本编辑器核心（Python 后端执行版 + 文件系统脚本管理）
 *
 * 功能：
 *   - Monaco Editor 初始化与配置
 *   - 工具栏事件绑定（运行/保存/格式化/清空/示例）
 *   - 快捷键绑定（Ctrl+Enter 运行、Ctrl+S 保存）
 *   - 侧边栏脚本列表（可展开/收起）
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
    let scriptsCache = [];      // 脚本列表缓存
    let sidebarCollapsed = false; // 侧边栏收起状态

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

        // 初始化侧边栏
        initSidebar();
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
            id: 'save-script',
            label: '保存脚本',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
            run: function () { saveScript(); }
        });
    }

    // ==================================================================
    // 侧边栏功能
    // ==================================================================
    function initSidebar() {
        // 从 localStorage 恢复收起状态
        const savedState = localStorage.getItem('editor-sidebar-collapsed');
        if (savedState === 'true') {
            sidebarCollapsed = true;
        }

        // 应用初始状态
        applySidebarState();

        // 绑定折叠按钮
        const toggleBtn = document.getElementById('sidebar-toggle-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleSidebar);
        }

        // 绑定新建按钮
        const newBtn = document.getElementById('sidebar-new-btn');
        if (newBtn) {
            newBtn.addEventListener('click', createNewScript);
        }

        // 加载脚本列表
        loadScriptList();
    }

    function toggleSidebar() {
        sidebarCollapsed = !sidebarCollapsed;
        applySidebarState();
        // 保存到 localStorage
        localStorage.setItem('editor-sidebar-collapsed', sidebarCollapsed ? 'true' : 'false');
        // 通知 Monaco 重新布局
        setTimeout(function () {
            if (editor) editor.layout();
        }, 260);
    }

    function applySidebarState() {
        const sidebar = document.getElementById('sidebar');
        const toggleBtn = document.getElementById('sidebar-toggle-btn');
        if (!sidebar) return;

        if (sidebarCollapsed) {
            sidebar.classList.add('sidebar-collapsed');
            sidebar.classList.remove('sidebar-expanded');
            if (toggleBtn) {
                toggleBtn.title = '展开侧边栏';
            }
        } else {
            sidebar.classList.remove('sidebar-collapsed');
            sidebar.classList.add('sidebar-expanded');
            if (toggleBtn) {
                toggleBtn.title = '收起侧边栏';
            }
        }
    }

    function loadScriptList() {
        fetch('/admin/cmd/scripts')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                scriptsCache = data.scripts || [];
                renderScriptList();
            })
            .catch(function (err) {
                console.error('加载脚本列表失败:', err);
            });
    }

    function renderScriptList() {
        const listEl = document.getElementById('sidebar-script-list');
        if (!listEl) return;

        if (!scriptsCache || scriptsCache.length === 0) {
            listEl.innerHTML = '<div class="sidebar-empty">暂无脚本<br>点击下方新建</div>';
            return;
        }

        listEl.innerHTML = scriptsCache.map(function (s) {
            const isActive = s.filename === editingFilename;
            return `
                <div class="sidebar-script-item ${isActive ? 'active' : ''}" data-filename="${escapeHtml(s.filename)}" title="${escapeHtml(s.description || s.name)}">
                    <i data-lucide="file-code" class="w-4 h-4 script-icon"></i>
                    <span class="script-name">${escapeHtml(s.name)}</span>
                    <button class="delete-btn" data-filename="${escapeHtml(s.filename)}" title="删除脚本">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `;
        }).join('');

        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }

        // 绑定点击事件
        listEl.querySelectorAll('.sidebar-script-item').forEach(function (item) {
            item.addEventListener('click', function (e) {
                // 如果点击的是删除按钮，不触发打开
                if (e.target.closest('.delete-btn')) return;
                const filename = item.dataset.filename;
                if (filename) openScript(filename);
            });
        });

        // 绑定删除按钮
        listEl.querySelectorAll('.delete-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                const filename = btn.dataset.filename;
                if (filename) deleteScript(filename);
            });
        });
    }

    function openScript(filename) {
        // 检查是否有未保存的更改（简单提示）
        // TODO: 可以用 Monaco 的 isDirty 来更精确判断

        fetch('/admin/cmd/scripts/' + encodeURIComponent(filename))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.script && data.script.content != null) {
                    editor.setValue(data.script.content);
                    editingFilename = filename;
                    editingCmdId = null;
                    updateEditorTitle();
                    // 更新列表高亮
                    renderScriptList();
                    // 更新 URL（不刷新页面）
                    history.replaceState(null, '', '?file=' + encodeURIComponent(filename));
                } else {
                    appendOutput('[加载失败] ' + (data.message || '未知错误'), 'error');
                }
            })
            .catch(function (err) {
                appendOutput('[网络错误] ' + err.message, 'error');
            });
    }

    function deleteScript(filename) {
        const confirmMsg = '确定删除脚本 "' + filename + '" 吗？此操作不可恢复。';
        let doDelete = false;

        if (window.CmdModal && window.CmdModal.confirm) {
            window.CmdModal.confirm('删除脚本', confirmMsg).then(function (ok) {
                if (ok) doDeleteRequest();
            });
        } else if (confirm(confirmMsg)) {
            doDeleteRequest();
        }

        function doDeleteRequest() {
            fetch('/admin/cmd/scripts/' + encodeURIComponent(filename), {
                method: 'DELETE',
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.success) {
                        appendOutput('[已删除] ' + filename, 'info');
                        // 如果删除的是当前编辑的文件，清空状态
                        if (editingFilename === filename) {
                            editingFilename = null;
                            updateEditorTitle();
                            history.replaceState(null, '', window.location.pathname);
                        }
                        loadScriptList();
                    } else {
                        appendOutput('[删除失败] ' + (data.message || '未知错误'), 'error');
                    }
                })
                .catch(function (err) {
                    appendOutput('[网络错误] ' + err.message, 'error');
                });
        }
    }

    function createNewScript() {
        let name = '';
        let description = '';

        if (window.CmdModal && window.CmdModal.prompt) {
            window.CmdModal.prompt('新建脚本', '请输入脚本名称：', '')
                .then(function (n) {
                    if (!n) return;
                    name = n;
                    return window.CmdModal.prompt('描述（可选）', '请输入简短描述：', '');
                })
                .then(function (d) {
                    description = d || '';
                    doCreate();
                });
        } else {
            name = prompt('请输入脚本名称：', '');
            if (!name) return;
            description = prompt('描述（可选）：', '') || '';
            doCreate();
        }

        function doCreate() {
            const content = '# ' + name + '\n# ' + description + '\n\necho("Hello, MiniScript!")\n';
            editor.setValue(content);
            editingFilename = null;
            editingCmdId = null;
            updateEditorTitle();
            appendOutput('[新建脚本] ' + name + '（编辑后按 Ctrl+S 保存）', 'info');
        }
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

        // 如果已有文件名，直接保存
        if (editingFilename) {
            await doSave(editingFilename, code);
            return;
        }

        // 新脚本：需要输入名称
        let name;
        let description;

        if (window.CmdModal && window.CmdModal.prompt) {
            name = await window.CmdModal.prompt('保存脚本', '请输入脚本名称：', '');
            if (!name) return;
            description = await window.CmdModal.prompt('描述（可选）', '请输入简短描述：', '');
        } else {
            name = prompt('请输入脚本名称：', '');
            if (!name) return;
            description = prompt('描述（可选）：', '') || '';
        }

        await doSave(null, code, name, description);
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
                updateEditorTitle();
                // 更新 URL
                history.replaceState(null, '', '?file=' + encodeURIComponent(result.script.filename));
                // 刷新列表
                loadScriptList();
                appendOutput('[已保存] ' + result.script.filename, 'info');
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
    // 工具函数
    // ==================================================================
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
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
        // 侧边栏相关
        loadScriptList: loadScriptList,
        openScript: openScript,
        toggleSidebar: toggleSidebar,
        saveCurrentScript: saveScript,
        createNewScript: createNewScript,
    };
})();
