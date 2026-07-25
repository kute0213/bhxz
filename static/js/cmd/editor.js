/**
 * MiniScript 专业脚本编辑器
 *
 * 基于 Monaco Editor（VS Code 核心）实现，提供：
 *   - 语法高亮（自定义 miniscript 语言）
 *   - 代码补全（关键字 + 内置函数 + 文档）
 *   - 实时错误诊断（波浪线 + 行号 + 错误列表）
 *   - 悬浮提示（函数签名与用法）
 *   - 行号标注、代码折叠、括号匹配
 *   - 查找/批量替换（Ctrl+F / Ctrl+H / Ctrl+Shift+L）
 *   - 测试运行（无需保存）+ 中止按钮
 *   - 保存为快捷命令（写入数据库）
 *
 * 依赖：Monaco Editor、MiniScript、CmdModal
 */
window.MiniScriptEditor = (function () {

    // ==================================================================
    // 内置函数元数据（用于补全与悬浮提示）
    // ==================================================================
    const BUILTINS = [
        { name: 'echo', sig: 'echo(message)', doc: '将消息输出到终端/输出面板，并返回原值。' },
        { name: 'print', sig: 'print(...args)', doc: '输出到浏览器控制台（console.log）。' },
        { name: 'alert', sig: 'alert(title, message)', doc: '弹窗提示，返回 Promise<void>。' },
        { name: 'prompt', sig: 'prompt(title, message, default)', doc: '弹窗输入框，返回 Promise<string>。' },
        { name: 'confirm', sig: 'confirm(title, message)', doc: '确认弹窗，返回 Promise<bool>。' },
        { name: 'cmd', sig: 'cmd(command)', doc: '流式执行服务端 CMD 命令，输出到终端，返回完整输出字符串。' },
        { name: 'cmd_sync', sig: 'cmd_sync(command)', doc: '同步执行 CMD 命令，一次性返回输出字符串。' },
        { name: 'sleep', sig: 'sleep(ms)', doc: '等待指定毫秒数，返回 Promise<void>。' },
        { name: 'set_interval', sig: 'set_interval(code, ms)', doc: '定时重复执行（最小间隔 100ms），返回定时器 id。' },
        { name: 'set_timeout', sig: 'set_timeout(code, ms)', doc: '延迟执行一次，返回定时器 id。' },
        { name: 'clear_timer', sig: 'clear_timer(id)', doc: '取消由 set_interval / set_timeout 创建的定时器。' },
        { name: 'range', sig: 'range(start, end, step)', doc: '生成数字范围。range(end) 或 range(start, end, step?)。' },
        { name: 'len', sig: 'len(obj)', doc: '获取列表/字符串/对象的长度。' },
        { name: 'append', sig: 'append(list, ...items)', doc: '向列表追加元素，返回列表。' },
        { name: 'push', sig: 'push(list, item)', doc: '向列表追加元素，返回新长度。' },
        { name: 'pop', sig: 'pop(list, index?)', doc: '弹出元素（默认末尾），返回被弹出的值。' },
        { name: 'slice', sig: 'slice(list, start, end?)', doc: '列表/字符串切片。' },
        { name: 'join', sig: 'join(list, sep)', doc: '列表元素用 sep 连接为字符串。' },
        { name: 'reverse', sig: 'reverse(list)', doc: '反转列表，返回新列表。' },
        { name: 'sort', sig: 'sort(list, cmp?)', doc: '排序列表，返回新列表。' },
        { name: 'parseInt', sig: 'parseInt(str)', doc: '字符串转整数。' },
        { name: 'parseFloat', sig: 'parseFloat(str)', doc: '字符串转浮点数。' },
        { name: 'str', sig: 'str(val)', doc: '将任意值转为字符串。' },
        { name: 'now', sig: 'now()', doc: '返回当前时间戳（秒）。' },
        { name: 'regex', sig: 'regex(str, pattern)', doc: '正则匹配，返回匹配数组或 null。' },
        { name: 'regex_test', sig: 'regex_test(str, pattern)', doc: '正则测试，返回 bool。' },
    ];

    const KEYWORDS = ['if', 'elif', 'else', 'while', 'for', 'in', 'break', 'continue', 'true', 'false', 'null', 'None'];

    const EXAMPLES = {
        'Hello World': '# 第一个脚本\necho("Hello, World!")',
        '循环与列表': 'nums = [1, 2, 3, 4, 5]\ntotal = 0\nfor n in nums:\n    total = total + n\necho("总和: " + str(total))',
        '条件判断': 'age = 18\nif age >= 18:\n    echo("成年人")\nelif age >= 13:\n    echo("青少年")\nelse:\n    echo("儿童")',
        '定时器': '# 每 500ms 输出一次时间\nset_interval("echo(now())", 500)',
        '索引与切片': 'fruits = ["苹果", "香蕉", "橘子"]\necho(fruits[0])\necho(fruits[-1])\necho(slice(fruits, 0, 2))',
        '执行 CMD': '# 执行服务端命令并获取输出\noutput = cmd("ls -la")\necho(output)',
    };

    // ==================================================================
    // Monaco 语言、主题、补全、诊断 注册
    // ==================================================================
    let editor = null;
    let diagnosticsDecoration = [];
    let runAbortBtn = null;
    let isRunning = false;
    let editingCmdId = null;

    // ----------------------------------------------------------------
    // 注册自定义语言 miniscript
    // ----------------------------------------------------------------
    function registerLanguage() {
        // 语言配置：括号、注释、自动配对
        monaco.languages.register({ id: 'miniscript' });

        monaco.languages.setLanguageConfiguration('miniscript', {
            comments: { lineComment: '#' },
            brackets: [
                ['[', ']'],
                ['(', ')'],
            ],
            autoClosingPairs: [
                { open: '"', close: '"' },
                { open: "'", close: "'" },
                { open: '(', close: ')' },
                { open: '[', close: ']' },
            ],
            surroundingPairs: [
                { open: '"', close: '"' },
                { open: "'", close: "'" },
                { open: '(', close: ')' },
                { open: '[', close: ']' },
            ],
            indentationRules: {
                // 增加缩进：以冒号结尾的行
                increaseIndentPattern: /:\s*$/,
                decreaseIndentPattern: /^\s*(elif|else)\b/,
            },
        });

        // 词法分析规则（Monaco monarch）
        monaco.languages.setMonarchTokensProvider('miniscript', {
            defaultToken: 'identifier',
            keywords: KEYWORDS,
            operators: [
                '+', '-', '*', '/', '%', '=', '==', '!=', '>', '<', '>=', '<=', '&&', '||', '!',
            ],
            symbols: /[=><!~?:&|+\-*/^%]+/,
            tokenizer: {
                root: [
                    // 注释
                    [/#.*$/, 'comment'],
                    // 字符串
                    [/"(?:[^"\\]|\\.)*$/, 'string.invalid'],
                    [/'(?:[^'\\]|\\.)*$/, 'string.invalid'],
                    [/"/, 'string', '@string_double'],
                    [/'/, 'string', '@string_single'],
                    // 数字
                    [/\d+\.\d+/, 'number.float'],
                    [/\d+/, 'number'],
                    // 关键字与标识符
                    [/[a-zA-Z_]\w*/, {
                        cases: {
                            '@keywords': 'keyword',
                            '@default': 'identifier',
                        }
                    }],
                    // 运算符
                    [/==|!=|>=|<=|&&|\|\|/, 'operator'],
                    [/[+\-*/%=<>!]/, 'operator'],
                    // 标点
                    [/[(){}\[\],:;]/, 'delimiter'],
                    // 空白
                    [/\s+/, 'white'],
                ],
                string_double: [
                    [/[^"\\]+/, 'string'],
                    [/\\./, 'string.escape'],
                    [/"/, 'string', '@pop'],
                ],
                string_single: [
                    [/[^'\\]+/, 'string'],
                    [/\\./, 'string.escape'],
                    [/'/, 'string', '@pop'],
                ],
            },
        });

        // 自定义主题（与站点深绿金色风格匹配）
        monaco.editor.defineTheme('miniscriptDark', {
            base: 'vs-dark',
            inherit: true,
            rules: [
                { token: 'comment', foreground: '6b7280', fontStyle: 'italic' },
                { token: 'string', foreground: 'a3e635' },
                { token: 'string.escape', foreground: 'facc15' },
                { token: 'number', foreground: 'fbbf24' },
                { token: 'number.float', foreground: 'fbbf24' },
                { token: 'keyword', foreground: 'c084fc' },
                { token: 'identifier', foreground: 'e8e4d9' },
                { token: 'operator', foreground: 'f4d03f' },
                { token: 'delimiter', foreground: '94a3b8' },
            ],
            colors: {
                'editor.background': '#0a1410',
                'editor.foreground': '#e8e4d9',
                'editorLineNumber.foreground': '#4b5563',
                'editorLineNumber.activeForeground': '#f4d03f',
                'editor.selectionBackground': '#1a472a80',
                'editor.lineHighlightBackground': '#1a2f1a40',
                'editorCursor.foreground': '#f4d03f',
                'editorIndentGuide.background': '#1a2f1a',
                'editorIndentGuide.activeBackground': '#2d5a3d',
                'editorWidget.background': '#0d1b0f',
                'editorWidget.border': '#1a472a',
                'editorSuggestWidget.background': '#0d1b0f',
                'editorSuggestWidget.selectedBackground': '#1a472a',
                'editorError.foreground': '#f87171',
                'editorError.background': '#f8717120',
                'editorWarning.foreground': '#fbbf24',
                'editorGutter.background': '#0a1410',
            }
        });
    }

    // ----------------------------------------------------------------
    // 注册代码补全
    // ----------------------------------------------------------------
    function registerCompletion() {
        monaco.languages.registerCompletionItemProvider('miniscript', {
            triggerCharacters: ['.', ' '],
            provideCompletionItems: function (model, position) {
                const word = model.getWordUntilPosition(position);
                const range = {
                    startLineNumber: position.lineNumber,
                    endLineNumber: position.lineNumber,
                    startColumn: word.startColumn,
                    endColumn: word.endColumn,
                };

                const suggestions = [];

                // 关键字
                KEYWORDS.forEach(function (kw) {
                    suggestions.push({
                        label: kw,
                        kind: monaco.languages.CompletionItemKind.Keyword,
                        insertText: kw,
                        detail: '关键字',
                        range: range,
                    });
                });

                // 内置函数
                BUILTINS.forEach(function (fn) {
                    suggestions.push({
                        label: fn.name,
                        kind: monaco.languages.CompletionItemKind.Function,
                        insertText: fn.name + '($0)',
                        insertTextRules: monaco.languages.InsertTextRule.InsertAsSnippet,
                        detail: fn.sig,
                        documentation: { value: fn.doc },
                        range: range,
                    });
                });

                return { suggestions: suggestions };
            }
        });
    }

    // ----------------------------------------------------------------
    // 注册悬浮提示
    // ----------------------------------------------------------------
    function registerHover() {
        monaco.languages.registerHoverProvider('miniscript', {
            provideHover: function (model, position) {
                const word = model.getWordAtPosition(position);
                if (!word) return null;
                const fn = BUILTINS.find(function (f) { return f.name === word.word; });
                if (!fn) return null;
                return {
                    range: new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn),
                    contents: [
                        { value: '**' + fn.sig + '**' },
                        { value: fn.doc },
                    ]
                };
            }
        });
    }

    // ----------------------------------------------------------------
    // 实时语法诊断：调用 MiniScript 的 tokenizer + parser
    // ----------------------------------------------------------------
    function registerDiagnostics() {
        let timer = null;
        editor.onDidChangeModelContent(function () {
            if (timer) clearTimeout(timer);
            timer = setTimeout(runDiagnostics, 250);
        });

        // 初始执行一次
        setTimeout(runDiagnostics, 100);
    }

    function runDiagnostics() {
        const code = editor.getValue();
        const markers = [];

        try {
            const tokens = window.MiniScript.tokenize(code);
            const parser = new window.MiniScript.Parser(tokens);
            parser.parseAll();
        } catch (err) {
            if (err && err.line != null) {
                const line = err.line;
                const col = err.column || 1;
                // 计算该行末尾列
                const codeLines = code.split('\n');
                const lineContent = codeLines[line - 1] || '';
                const endCol = lineContent.length + 1;
                markers.push({
                    startLineNumber: line,
                    startColumn: col,
                    endLineNumber: line,
                    endColumn: Math.max(endCol, col + 1),
                    message: err.rawMessage || err.message,
                    severity: monaco.MarkerSeverity.Error,
                });
            }
        }

        monaco.editor.setModelMarkers(editor.getModel(), 'miniscript', markers);
        updateStatusBadge(markers.length);
    }

    function updateStatusBadge(errorCount) {
        const badge = document.getElementById('editor-status-errors');
        if (!badge) return;
        if (errorCount === 0) {
            badge.textContent = '语法正确';
            badge.className = 'px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/20';
        } else {
            badge.textContent = errorCount + ' 个错误';
            badge.className = 'px-2.5 py-1 rounded-md text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/20';
        }
    }

    // ==================================================================
    // 编辑器初始化
    // ==================================================================
    function init(initialCode, cmdId) {
        editingCmdId = cmdId || null;
        registerLanguage();
        registerCompletion();
        registerHover();

        const container = document.getElementById('monaco-editor');
        editor = monaco.editor.create(container, {
            value: initialCode || '',
            language: 'miniscript',
            theme: 'miniscriptDark',
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

        registerDiagnostics();
        bindToolbar();
        bindShortcuts();

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
        document.getElementById('editor-run-btn').addEventListener('click', runScript);
        document.getElementById('editor-save-btn').addEventListener('click', saveAsCommand);
        document.getElementById('editor-clear-output-btn').addEventListener('click', clearOutput);
        document.getElementById('editor-format-btn').addEventListener('click', formatCode);
        document.getElementById('editor-example-btn').addEventListener('click', toggleExamples);

        runAbortBtn = document.getElementById('editor-run-btn');

        // 示例列表
        const exList = document.getElementById('editor-example-list');
        if (exList) {
            Object.keys(EXAMPLES).forEach(function (name) {
                const item = document.createElement('button');
                item.className = 'block w-full text-left px-4 py-2 text-sm text-cream/80 hover:bg-gold-400/10 hover:text-gold-400 transition-colors';
                item.textContent = name;
                item.addEventListener('click', function () {
                    if (window.CmdModal && window.CmdModal.confirm) {
                        window.CmdModal.confirm('加载示例', '将用示例代码替换当前内容，确定继续吗？').then(function (ok) {
                            if (ok) {
                                editor.setValue(EXAMPLES[name]);
                                exList.classList.add('hidden');
                            }
                        });
                    } else if (confirm('将用示例代码替换当前内容，确定继续吗？')) {
                        editor.setValue(EXAMPLES[name]);
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
            run: function () { runScript(); }
        });

        editor.addAction({
            id: 'save-command',
            label: '保存为快捷命令',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
            run: function () { saveAsCommand(); }
        });
    }

    // ==================================================================
    // 脚本运行（测试，不保存）
    // ==================================================================
    async function runScript() {
        if (isRunning) {
            // 当前正在运行，则中止
            if (window.MiniScript && window.MiniScript.abort) MiniScript.abort();
            if (window.MiniScript && window.MiniScript.clearAllTimers) MiniScript.clearAllTimers();
            return;
        }

        const code = editor.getValue();
        if (!code.trim()) {
            appendOutput('[错误] 脚本为空', 'error');
            return;
        }

        // 中止旧脚本和定时器
        if (window.MiniScript && window.MiniScript.isRunning && MiniScript.isRunning()) {
            MiniScript.abort();
        }
        if (window.MiniScript && window.MiniScript.clearAllTimers) {
            MiniScript.clearAllTimers();
        }

        setRunning(true);
        clearOutput();
        appendOutput('[开始运行]', 'info');

        const buildins = {
            cmd_sync: function (command) {
                return new Promise(function (resolve) {
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
                    }).then(function (r) { return r.json(); }).then(function (data) {
                        clearTimeout(cmdTimeout);
                        resolve(data.output || data.error || '');
                    }).catch(function (err) {
                        clearTimeout(cmdTimeout);
                        if (err.name === 'AbortError') return;
                        resolve('[网络错误] ' + err.message);
                    });
                });
            },
            cmd: function (command) {
                return new Promise(function (resolve) {
                    let fullOutput = '';
                    const url = '/admin/cmd/run-stream?command=' + encodeURIComponent(command);
                    const es = new EventSource(url);
                    const cmdTimeout = setTimeout(function () {
                        es.close();
                        appendOutput('[cmd 超时，已自动断开]', 'error');
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
                                appendOutput(evt.line);
                            } else if (evt.type === 'exit') {
                                appendOutput('[退出码] ' + evt.code, 'exit');
                            } else if (evt.type === 'error') {
                                appendOutput('[错误] ' + evt.message, 'error');
                            }
                        } catch (err) {
                            fullOutput += e.data + '\n';
                            appendOutput(e.data);
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
                appendOutput(formatted, 'script');
                return msg;
            }
        };

        try {
            await window.MiniScript.run(code, buildins);
            appendOutput('[脚本执行完毕]', 'info');
        } catch (err) {
            if (err && err.message && err.message.indexOf('手动中止') !== -1) {
                appendOutput('[脚本已中止]', 'warning');
            } else if (err && err.message && err.message.indexOf('超时') !== -1) {
                appendOutput('[脚本超时，已自动中止]', 'warning');
            } else {
                appendOutput('[错误] ' + (err.message || String(err)), 'error');
                // 如果错误带行号，跳转到该行
                if (err && err.line) {
                    editor.revealLineInCenter(err.line);
                    editor.setPosition({ lineNumber: err.line, column: err.column || 1 });
                    editor.focus();
                }
            }
        } finally {
            // 检查是否有活跃定时器
            if (window.MiniScript && window.MiniScript.hasActiveTimers && MiniScript.hasActiveTimers()) {
                appendOutput('[脚本已结束，但有定时器仍在运行，点击中止可停止]', 'warning');
            } else {
                setRunning(false);
            }
        }
    }

    function setRunning(running) {
        isRunning = running;
        const btn = document.getElementById('editor-run-btn');
        const btnText = document.getElementById('editor-run-btn-text');
        const btnIcon = document.getElementById('editor-run-btn-icon');
        if (running) {
            btn.classList.remove('bg-gold-400', 'hover:bg-gold-500', 'text-forest-900');
            btn.classList.add('bg-red-500/80', 'hover:bg-red-500', 'text-white');
            if (btnText) btnText.textContent = '中止';
            if (btnIcon) btnIcon.setAttribute('data-lucide', 'square');
        } else {
            btn.classList.add('bg-gold-400', 'hover:bg-gold-500', 'text-forest-900');
            btn.classList.remove('bg-red-500/80', 'hover:bg-red-500', 'text-white');
            if (btnText) btnText.textContent = '运行';
            if (btnIcon) btnIcon.setAttribute('data-lucide', 'play');
        }
        if (window.lucide) lucide.createIcons();
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
    // 输出面板
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

    return {
        init: init,
        appendOutput: appendOutput,
        clearOutput: clearOutput,
    };
})();
