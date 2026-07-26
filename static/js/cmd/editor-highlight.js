/**
 * editor-highlight.js — Monaco Editor 语法高亮 / 代码补全 / 悬浮提示配置
 *
 * 由 editor.js 拆分而来，提供：
 *   - 内置函数元数据（BUILTINS，与后端 builtins.py 对齐）
 *   - Python 关键字（KEYWORDS）
 *   - 示例代码（EXAMPLES）
 *   - 自定义深色主题 pythonDark
 *   - 代码补全与悬浮提示注册
 *   - 状态栏错误标记
 *
 * 暴露：window.ScriptEditorHighlight
 * 依赖：Monaco Editor（由 admin_cmd_editor.html 通过 require 加载）
 *      必须在 editor.js 之前加载
 */
window.ScriptEditorHighlight = (function () {

    // ==================================================================
    // 内置函数元数据（用于补全与悬浮提示，与后端 builtins.py 对齐）
    // ==================================================================
    const BUILTINS = [
        { name: 'echo', sig: 'echo(*args)', doc: '输出消息到终端（拼接所有参数）。' },
        { name: 'print', sig: 'print(*args, sep=" ", end="\\n")', doc: '标准 print 输出。' },
        { name: 'alert', sig: 'alert(title, message="")', doc: '弹窗提示（前端交互模式有效，定时模式静默跳过）。' },
        { name: 'prompt', sig: 'prompt(title, message="", default="")', doc: '弹窗输入框，返回字符串（定时模式返回 default）。' },
        { name: 'confirm', sig: 'confirm(title, message="")', doc: '确认弹窗，返回 True/False（定时模式返回 True）。' },
        { name: 'cmd', sig: 'cmd(command)', doc: '执行 shell 命令，返回输出字符串。' },
        { name: 'sleep', sig: 'sleep(seconds)', doc: '延时指定秒数。' },
        { name: 'now', sig: 'now()', doc: '返回当前时间戳（秒，float）。' },
        { name: 'set_timeout', sig: 'set_timeout(seconds)', doc: '设定本次执行超时（上限 300s）。' },
        { name: 'file_read', sig: 'file_read(path)', doc: '读取文件内容，返回字符串。' },
        { name: 'file_write', sig: 'file_write(path, content)', doc: '写入文件，返回 True/False。' },
        { name: 'file_append', sig: 'file_append(path, content)', doc: '追加写入文件，返回 True/False。' },
        { name: 'file_list', sig: 'file_list(dir_path)', doc: '列出目录文件，返回文件名列表。' },
        { name: 'file_exists', sig: 'file_exists(path)', doc: '判断文件/目录是否存在，返回 True/False。' },
        { name: 'db_query', sig: 'db_query(sql, params=None)', doc: '执行 SQL 查询，返回字典列表。' },
        { name: 'db_execute', sig: 'db_execute(sql, params=None)', doc: '执行 SQL 语句，返回影响行数。' },
    ];

    // Python 关键字（用于补全，高亮由 Monaco 内置 Python 词法器处理）
    const KEYWORDS = [
        'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
        'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
        'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
        'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
        'while', 'with', 'yield', 'match', 'case'
    ];

    // 示例代码（供工具栏"示例"下拉使用）
    const EXAMPLES = {
        'Hello World': '# 第一个脚本\necho("Hello, World!")',
        '循环与列表': 'nums = [1, 2, 3, 4, 5]\ntotal = 0\nfor n in nums:\n    total += n\necho(f"总和: {total}")',
        '条件判断': 'age = 18\nif age >= 18:\n    echo("成年人")\nelif age >= 13:\n    echo("青少年")\nelse:\n    echo("儿童")',
        '交互输入': 'name = prompt("用户信息", "请输入你的名字：", "匿名")\nalert("欢迎", f"你好, {name}!")',
        '执行 CMD': '# 执行服务端命令并获取输出\noutput = cmd("ls -la")\necho(output)',
        '读取文件': 'content = file_read("/etc/hostname")\necho(content)',
        '数据库查询': 'rows = db_query("SELECT id, name FROM users LIMIT 5")\nfor row in rows:\n    echo(row)',
    };

    // ----------------------------------------------------------------
    // 自定义深色主题（与站点深绿金色风格匹配），语言沿用内置 python
    // ----------------------------------------------------------------
    function registerTheme() {
        monaco.editor.defineTheme('pythonDark', {
            base: 'vs-dark',
            inherit: true,
            rules: [
                { token: 'comment', foreground: '6b7280', fontStyle: 'italic' },
                { token: 'string', foreground: 'a3e635' },
                { token: 'string.escape', foreground: 'facc15' },
                { token: 'number', foreground: 'fbbf24' },
                { token: 'keyword', foreground: 'c084fc' },
                { token: 'identifier', foreground: 'e8e4d9' },
                { token: 'operator', foreground: 'f4d03f' },
                { token: 'delimiter', foreground: '94a3b8' },
                { token: 'type', foreground: '67e8f9' },
                { token: 'type.identifier', foreground: '67e8f9' },
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
    // 注册代码补全（针对 python 语言追加内置函数）
    // ----------------------------------------------------------------
    function registerCompletion() {
        monaco.languages.registerCompletionItemProvider('python', {
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

                // 后端内置函数
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
    // 注册悬浮提示（针对 python 语言）
    // ----------------------------------------------------------------
    function registerHover() {
        monaco.languages.registerHoverProvider('python', {
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
    // 状态栏错误标记（前端不再做实时语法诊断，状态恒为"语法正确"）
    // 后端执行时会通过 SSE error 事件回传错误，由 editor-sse.js 处理
    // ----------------------------------------------------------------
    function updateStatusBadge(errorCount) {
        const badge = document.getElementById('editor-status-errors');
        if (!badge) return;
        if (!errorCount || errorCount === 0) {
            badge.textContent = '语法检查由后端执行';
            badge.className = 'px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/20';
        } else {
            badge.textContent = errorCount + ' 个错误';
            badge.className = 'px-2.5 py-1 rounded-md text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/20';
        }
    }

    return {
        BUILTINS: BUILTINS,
        KEYWORDS: KEYWORDS,
        EXAMPLES: EXAMPLES,
        registerTheme: registerTheme,
        registerCompletion: registerCompletion,
        registerHover: registerHover,
        updateStatusBadge: updateStatusBadge,
    };
})();
