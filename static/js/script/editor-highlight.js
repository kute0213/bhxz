/**
 * editor-highlight.js — Monaco Editor 语法高亮 / 代码补全 / 悬浮提示配置
 *
 * 由 editor.js 拆分而来，提供：
 *   - 内置函数元数据（BUILTINS，与后端 builtins.py 对齐）
 *   - Python 关键字（KEYWORDS）
 *   - 自定义深色主题 pythonDark
 *   - 代码补全与悬浮提示注册
 *   - 状态栏错误标记
 *
 * 暴露：window.ScriptEditorHighlight
 * 依赖：Monaco Editor（由 admin_script_editor.html 通过 require 加载）
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
    // 状态栏错误标记：根据前端实时诊断结果展示「语法正确」或「N 个错误」
    // 后端执行时仍会通过 SSE error 事件回传运行时错误，由 editor-sse.js 处理
    // ----------------------------------------------------------------
    function updateStatusBadge(errorCount) {
        const badge = document.getElementById('editor-status-errors');
        if (!badge) return;
        if (!errorCount || errorCount === 0) {
            badge.textContent = '语法正确';
            badge.className = 'px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/20';
        } else {
            badge.textContent = errorCount + ' 个错误';
            badge.className = 'px-2.5 py-1 rounded-md text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/20';
        }
    }

    // ----------------------------------------------------------------
    // 注册实时语法诊断：监听编辑器内容变化，使用 Monaco markers 系统
    // 在编辑器内显示错误波浪线与悬停提示，并同步更新状态栏徽章
    // ----------------------------------------------------------------
    function registerDiagnostics(editor) {
        const model = editor.getModel();
        let checkTimeout = null;

        function runCheck() {
            const markers = checkPythonSyntax(model.getValue());
            monaco.editor.setModelMarkers(model, 'python-lint', markers);
            updateStatusBadge(markers.length);
        }

        model.onDidChangeContent(function () {
            if (checkTimeout) clearTimeout(checkTimeout);
            // 防抖：避免连续输入时频繁触发，300ms 静默后检查一次
            checkTimeout = setTimeout(runCheck, 300);
        });

        // 初始检查
        runCheck();
    }

    // ----------------------------------------------------------------
    // 轻量级 Python 语法检查器
    // 仅检查常见语法错误，不做完整解析：
    //   1. 括号匹配（()、[]、{}）
    //   2. 缩进错误（同一行混合使用空格与 Tab）
    //   3. 复合语句（if/for/while/def/class 等）后冒号缺失
    //   4. 行尾续行符错误（反斜杠后非空）
    //   5. 未闭合的字符串（单/双引号、三引号）
    // 注意：字符串字面量内的内容不会被检查；多行括号表达式中的冒号检查会跳过
    // ----------------------------------------------------------------
    function checkPythonSyntax(code) {
        const markers = [];
        if (!code) return markers;

        const lines = code.split('\n');
        // 括号栈：记录未闭合的开括号位置 {char, line, col}
        const bracketStack = [];
        // 字符串状态：null | '"' | "'" | '"""' | "'''"
        let inString = null;
        // 多行字符串起始位置，用于未闭合时报错定位
        let stringStart = null;

        // 复合语句关键字：必须以冒号结尾
        const compoundKeywords = [
            'if', 'elif', 'else', 'for', 'while', 'def',
            'class', 'try', 'except', 'finally', 'with',
        ];

        // 工具：向 markers 推入一条单行错误
        function pushMarker(line, startCol, endCol, msg, severity) {
            markers.push({
                startLineNumber: line,
                startColumn: startCol,
                endLineNumber: line,
                endColumn: endCol,
                message: msg,
                severity: severity,
            });
        }

        // 工具：在已知本行所有字符串均已闭合的前提下，查找行内注释 # 的位置
        function findCommentIndex(line) {
            let str = null;
            let k = 0;
            while (k < line.length) {
                const c = line[k];
                if (str) {
                    if (c === '\\') { k += 2; continue; }
                    if (line.substring(k, k + 3) === str) { str = null; k += 3; continue; }
                    if (c === str) { str = null; k++; continue; }
                    k++;
                    continue;
                }
                if (c === '"' || c === "'") {
                    const triple = line.substring(k, k + 3);
                    if (triple === '"""' || triple === "'''") { str = triple; k += 3; continue; }
                    str = c; k++; continue;
                }
                if (c === '#') return k;
                k++;
            }
            return -1;
        }

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const lineNum = i + 1;
            // 本行起始时是否处于多行字符串内
            const wasInString = !!inString;

            // ---- 字符级扫描：括号 / 字符串 / 续行符 ----
            let j = 0;
            while (j < line.length) {
                const ch = line[j];

                if (inString) {
                    // 三引号字符串内：仅查找结束三引号
                    if (inString === '"""' || inString === "'''") {
                        if (line.substring(j, j + 3) === inString) {
                            inString = null;
                            j += 3;
                            continue;
                        }
                        j++;
                        continue;
                    }
                    // 单/双引号字符串内：处理转义与结束符
                    if (ch === '\\') { j += 2; continue; }
                    if (ch === inString) { inString = null; j++; continue; }
                    j++;
                    continue;
                }

                // 注释开始：跳过本行剩余内容
                if (ch === '#') break;

                // 字符串开始
                if (ch === '"' || ch === "'") {
                    const triple = line.substring(j, j + 3);
                    if (triple === '"""' || triple === "'''") {
                        inString = triple;
                        stringStart = { line: lineNum, col: j + 1 };
                        j += 3;
                        continue;
                    }
                    inString = ch;
                    stringStart = { line: lineNum, col: j + 1 };
                    j++;
                    continue;
                }

                // 开括号入栈
                if (ch === '(' || ch === '[' || ch === '{') {
                    bracketStack.push({ char: ch, line: lineNum, col: j + 1 });
                    j++;
                    continue;
                }
                // 闭括号匹配
                if (ch === ')' || ch === ']' || ch === '}') {
                    const top = bracketStack.length ? bracketStack[bracketStack.length - 1] : null;
                    const expected = top ? { '(': ')', '[': ']', '{': '}' }[top.char] : null;
                    if (top && expected === ch) {
                        bracketStack.pop();
                    } else {
                        pushMarker(
                            lineNum, j + 1, j + 2,
                            '语法错误：括号不匹配，发现多余的 "' + ch + '"',
                            monaco.MarkerSeverity.Error
                        );
                    }
                    j++;
                    continue;
                }

                // 行尾续行符：反斜杠后必须紧跟行尾（仅空白）
                if (ch === '\\') {
                    const rest = line.substring(j + 1);
                    if (rest.trim() === '') {
                        j = line.length;  // 正常续行，结束本行扫描
                        continue;
                    }
                    pushMarker(
                        lineNum, j + 1, j + 2,
                        '语法错误：续行符 "\\" 后面必须紧跟行尾',
                        monaco.MarkerSeverity.Error
                    );
                    j++;
                    continue;
                }

                j++;
            }

            // 处于多行字符串内的行：跳过缩进与冒号检查
            if (wasInString) continue;
            // 本行开始了未闭合的多行字符串：跳过冒号检查（字符串内容不参与语法判断）
            if (inString) continue;
            // 行尾有未闭合括号：可能在多行表达式中，跳过冒号检查
            if (bracketStack.length > 0) continue;

            // ---- 缩进检查：行首是否同时包含空格和 Tab ----
            let indent = '';
            for (let k = 0; k < line.length; k++) {
                if (line[k] === ' ' || line[k] === '\t') indent += line[k];
                else break;
            }
            if (indent.indexOf(' ') !== -1 && indent.indexOf('\t') !== -1) {
                pushMarker(
                    lineNum, 1, indent.length + 1,
                    '缩进警告：同一行混合使用了空格和 Tab',
                    monaco.MarkerSeverity.Warning
                );
            }

            // ---- 冒号缺失检查 ----
            // 截取行内注释之前的代码部分
            const commentIdx = findCommentIndex(line);
            const codeEnd = commentIdx >= 0 ? commentIdx : line.length;
            const codePart = line.substring(indent.length, codeEnd).replace(/\s+$/, '');
            if (!codePart) continue;
            // 续行结尾：跳过冒号检查
            if (codePart.charAt(codePart.length - 1) === '\\') continue;

            // 提取首个单词（按空白或左括号分割，兼容 if(x): 形式）
            const firstWord = codePart.split(/[\s(]/)[0];
            if (compoundKeywords.indexOf(firstWord) === -1) continue;

            if (codePart.charAt(codePart.length - 1) !== ':') {
                const col = indent.length + codePart.length;
                pushMarker(
                    lineNum, col + 1, col + 2,
                    '语法错误：' + firstWord + ' 语句末尾缺少冒号 ":"',
                    monaco.MarkerSeverity.Error
                );
            }
        }

        // ---- 文件结束：未闭合的括号 ----
        bracketStack.forEach(function (b) {
            const closeChar = { '(': ')', '[': ']', '{': '}' }[b.char];
            pushMarker(
                b.line, b.col, b.col + 1,
                '语法错误：未闭合的 "' + b.char + '"，缺少对应的 "' + closeChar + '"',
                monaco.MarkerSeverity.Error
            );
        });

        // ---- 文件结束：未闭合的字符串 ----
        if (inString && stringStart) {
            const endLine = lines.length;
            const endCol = (lines[lines.length - 1] || '').length + 1;
            markers.push({
                startLineNumber: stringStart.line,
                startColumn: stringStart.col,
                endLineNumber: endLine,
                endColumn: endCol,
                message: '语法错误：未闭合的字符串 ' + inString,
                severity: monaco.MarkerSeverity.Error,
            });
        }

        return markers;
    }

    return {
        BUILTINS: BUILTINS,
        KEYWORDS: KEYWORDS,
        registerTheme: registerTheme,
        registerCompletion: registerCompletion,
        registerHover: registerHover,
        registerDiagnostics: registerDiagnostics,
        updateStatusBadge: updateStatusBadge,
    };
})();
