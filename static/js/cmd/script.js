/**
 * MiniScript - 极简前端脚本语言解释器
 *
 * 语法类似 Python，支持：
 *   - 变量赋值: x = 1, name = "hello"
 *   - 算术运算: + - * / % ( )
 *   - 字符串拼接: "hello " + name
 *   - 比较运算: == != > < >= <=
 *   - 逻辑运算: && || !（短路求值）
 *   - 条件判断: if / elif / else（缩进块）
 *   - 循环: while / for...in / break / continue（带迭代保护 + 中止检测）
 *   - 列表: [1, 2, 3]，支持索引访问 list[0]、负索引 list[-1]
 *   - 注释: # 这是注释
 *   - 函数调用: func(arg1, arg2)
 *
 * 安全保护：
 *   - 循环最大 100,000 次迭代，每 100 次让出 UI 执行权
 *   - 脚本最大执行 30 秒，超时自动中止（Promise.race 机制）
 *   - 脚本可被外部中止（MiniScript.abort()）
 *   - set_interval 最小间隔 100ms
 *   - 定时器在终端关闭 / 新脚本启动时自动清理
 *   - 定时器代码在独立上下文执行，不干扰主脚本全局状态
 *   - 使用 run ID 防止旧 Promise 的 finally 干扰新脚本
 *
 * 内置函数：
 *   - alert(title, message)   弹窗提示
 *   - prompt(title, message)  弹窗获取输入，返回字符串
 *   - confirm(title, message) 确认弹窗，返回 true/false
 *   - cmd(command)            流式执行服务端 CMD（输出到终端，返回完整输出）
 *   - cmd_sync(command)       同步执行 CMD（一次性返回输出）
 *   - echo(message)           输出到终端（脚本标识）
 *   - print(...args)          输出到控制台
 *   - regex(str, pattern)     正则匹配，返回匹配数组或 null
 *   - regex_test(str, pattern) 正则测试，返回 true/false
 *   - sleep(ms)               等待毫秒
 *   - set_interval(fn, ms)    定时重复执行，返回 id（最小 100ms）
 *   - set_timeout(fn, ms)     延迟执行，返回 id
 *   - clear_timer(id)         取消定时器
 *   - range(start, end, step) 生成范围迭代器（for...in 使用）
 *   - append(list, ...items)  向列表追加元素
 *   - pop(list, index)        弹出元素（默认末尾）
 *   - push(list, item)        追加元素，返回新长度
 *   - slice(list, start, end) 切片
 *   - join(list, sep)         列表转字符串
 *   - len(obj)                获取长度
 *   - parseInt(str)           字符串转整数
 *   - parseFloat(str)         字符串转浮点数
 *   - str(val)                转字符串
 *   - now()                    返回当前时间戳(秒)
 */

window.MiniScript = (function () {

    // ==================================================================
    // 错误类型（带行号）
    // ==================================================================
    class MiniScriptError extends Error {
        constructor(message, line, column) {
            const prefix = (line != null ? '第 ' + line + ' 行' + (column != null ? ':' + column : '') + '：' : '');
            super(prefix + message);
            this.name = 'MiniScriptError';
            this.line = line;
            this.column = column;
            this.rawMessage = message;
        }
    }

    function makeError(message, line, column) {
        return new MiniScriptError(message, line, column);
    }

    // ==================================================================
    // Tokenizer（缩进感知，Python 风格）—— 带 token 行号追踪
    // ==================================================================
    function tokenize(code) {
        const tokens = [];
        const lines = code.split('\n');
        const indentStack = [0];
        let currentLine = 1;  // 当前处理的源码行号（1-based）

        // ---- 行内 tokenizer（所有 token 携带 line/column）----
        function tokenizeLine(str, lineNum) {
            let i = 0;
            while (i < str.length) {
                const ch = str[i];

                // 跳过行内空白与 Windows 行尾残留的 \r
                if (ch === ' ' || ch === '\t' || ch === '\r') { i++; continue; }

                // 行内注释
                if (ch === '#') break;

                const startCol = i + 1;  // 1-based column

                // 字符串
                if (ch === '"' || ch === "'") {
                    const quote = ch;
                    i++;
                    let val = '';
                    let closed = false;
                    while (i < str.length) {
                        if (str[i] === quote) { closed = true; break; }
                        if (str[i] === '\\' && i + 1 < str.length) {
                            const next = str[i + 1];
                            if (next === 'n') val += '\n';
                            else if (next === 't') val += '\t';
                            else if (next === '\\') val += '\\';
                            else if (next === quote) val += quote;
                            else val += next;
                            i += 2;
                        } else {
                            val += str[i];
                            i++;
                        }
                    }
                    if (!closed) {
                        throw makeError('字符串未闭合（缺少 ' + quote + '）', lineNum, startCol);
                    }
                    i++;
                    tokens.push({ type: 'string', value: val, line: lineNum, column: startCol });
                    continue;
                }

                // 数字
                if (/[0-9]/.test(ch) || (ch === '.' && i + 1 < str.length && /[0-9]/.test(str[i + 1]))) {
                    let num = '';
                    while (i < str.length && /[0-9.]/.test(str[i])) {
                        num += str[i];
                        i++;
                    }
                    tokens.push({ type: 'number', value: parseFloat(num), line: lineNum, column: startCol });
                    continue;
                }

                // 标识符 / 关键字
                if (/[a-zA-Z_]/.test(ch)) {
                    let name = '';
                    while (i < str.length && /[a-zA-Z0-9_]/.test(str[i])) {
                        name += str[i];
                        i++;
                    }
                    let tok;
                    if (name === 'true') tok = { type: 'boolean', value: true };
                    else if (name === 'false') tok = { type: 'boolean', value: false };
                    else if (name === 'null' || name === 'None') tok = { type: 'null', value: null };
                    else if (name === 'if' || name === 'elif' || name === 'else' || name === 'while' || name === 'for' || name === 'in' || name === 'break' || name === 'continue') tok = { type: 'keyword', value: name };
                    else tok = { type: 'ident', value: name };
                    tok.line = lineNum;
                    tok.column = startCol;
                    tokens.push(tok);
                    continue;
                }

                // 多字符运算符
                if (ch === '=' && str[i + 1] === '=') { tokens.push({ type: 'op', value: '==', line: lineNum, column: startCol }); i += 2; continue; }
                if (ch === '!' && str[i + 1] === '=') { tokens.push({ type: 'op', value: '!=', line: lineNum, column: startCol }); i += 2; continue; }
                if (ch === '>' && str[i + 1] === '=') { tokens.push({ type: 'op', value: '>=', line: lineNum, column: startCol }); i += 2; continue; }
                if (ch === '<' && str[i + 1] === '=') { tokens.push({ type: 'op', value: '<=', line: lineNum, column: startCol }); i += 2; continue; }
                if (ch === '&' && str[i + 1] === '&') { tokens.push({ type: 'op', value: '&&', line: lineNum, column: startCol }); i += 2; continue; }
                if (ch === '|' && str[i + 1] === '|') { tokens.push({ type: 'op', value: '||', line: lineNum, column: startCol }); i += 2; continue; }

                // 冒号（用于 if/else）
                if (ch === ':') { tokens.push({ type: 'punct', value: ':', line: lineNum, column: startCol }); i++; continue; }

                // 单字符运算符
                if ('+-*/%=<>!'.indexOf(ch) !== -1) {
                    tokens.push({ type: 'op', value: ch, line: lineNum, column: startCol });
                    i++;
                    continue;
                }

                // 括号
                if (ch === '(' || ch === ')') { tokens.push({ type: 'punct', value: ch, line: lineNum, column: startCol }); i++; continue; }

                // 分隔符
                if (ch === ',' || ch === '{' || ch === '}' || ch === '[' || ch === ']' || ch === ';') {
                    tokens.push({ type: 'punct', value: ch, line: lineNum, column: startCol });
                    i++;
                    continue;
                }

                throw makeError('未知字符: ' + JSON.stringify(ch), lineNum, startCol);
            }
        }

        // ---- 逐行处理 ----
        for (let lineNum = 0; lineNum < lines.length; lineNum++) {
            const line = lines[lineNum];
            const trimmed = line.trim();
            const sourceLine = lineNum + 1;  // 1-based
            currentLine = sourceLine;

            // 跳过空行和注释行
            if (trimmed === '' || trimmed.startsWith('#')) continue;

            // 计算缩进
            let indent = 0;
            for (let j = 0; j < line.length; j++) {
                if (line[j] === ' ') indent++;
                else if (line[j] === '\t') indent += 4;
                else break;
            }

            // 缩进出错检查 + INDENT/DEDENT
            const top = indentStack[indentStack.length - 1];
            if (indent > top) {
                indentStack.push(indent);
                tokens.push({ type: 'indent', line: sourceLine });
            } else if (indent < top) {
                while (indentStack.length > 1 && indentStack[indentStack.length - 1] > indent) {
                    indentStack.pop();
                    tokens.push({ type: 'dedent', line: sourceLine });
                }
                if (indentStack[indentStack.length - 1] !== indent) {
                    throw makeError('缩进错误（与上方代码块的缩进不匹配，期望对齐到 ' + indent + ' 个空格）', sourceLine, 1);
                }
            }

            // tokenize 本行内容
            tokenizeLine(line, sourceLine);
            tokens.push({ type: 'newline', line: sourceLine });
        }

        // 收尾 DEDENT
        while (indentStack.length > 1) {
            indentStack.pop();
            tokens.push({ type: 'dedent', line: currentLine });
        }

        tokens.push({ type: 'eof', line: currentLine });
        return tokens;
    }

    // ==================================================================
    // Parser（递归下降）
    // ==================================================================
    class Parser {
        constructor(tokens) {
            this.tokens = tokens;
            this.pos = 0;
        }

        peek(offset) { return this.tokens[this.pos + (offset || 0)]; }
        next() { return this.tokens[this.pos++]; }

        consume(type, value) {
            const t = this.tokens[this.pos];
            if (t.type !== type || (value !== undefined && t.value !== value)) {
                throw makeError(
                    '语法错误：期望 ' + type + (value ? ' "' + value + '"' : '') +
                    '，实际得到 ' + t.type + (t.value !== undefined ? ' "' + t.value + '"' : ''),
                    t.line, t.column
                );
            }
            this.pos++;
            return t;
        }
        match(type, value) {
            const t = this.tokens[this.pos];
            if (t.type === type && (value === undefined || t.value === value)) {
                this.pos++;
                return t;
            }
            return null;
        }
        skipNewlines() {
            while (this.peek().type === 'newline') this.pos++;
        }

        // ---- 顶层 ----
        parseAll() {
            const stmts = [];
            this.skipNewlines();
            while (this.peek().type !== 'eof') {
                // 防御：跳过顶层残留的 DEDENT（不应出现，但避免无限循环）
                if (this.peek().type === 'dedent') {
                    this.pos++;
                    this.skipNewlines();
                    continue;
                }
                const s = this.parseStatement();
                if (s) stmts.push(s);
                this.skipNewlines();
            }
            return stmts;
        }

        // ---- 语句 ----
        parseStatement() {
            if (this.peek().type === 'eof' || this.peek().type === 'dedent') return null;

            // if / elif / else 语句
            if (this.peek().type === 'keyword' && this.peek().value === 'if') {
                return this.parseIf();
            }

            // while 循环
            if (this.peek().type === 'keyword' && this.peek().value === 'while') {
                return this.parseWhile();
            }

            // for 循环
            if (this.peek().type === 'keyword' && this.peek().value === 'for') {
                return this.parseFor();
            }

            // break / continue
            if (this.peek().type === 'keyword' && (this.peek().value === 'break' || this.peek().value === 'continue')) {
                const kwTok = this.consume('keyword');
                return { type: kwTok.value, line: kwTok.line };
            }

            // 赋值: ident = expr
            if (this.peek().type === 'ident' &&
                this.peek(1) && this.peek(1).type === 'op' && this.peek(1).value === '=') {
                const nameTok = this.consume('ident');
                this.consume('op', '=');
                const val = this.parseExpr();
                return { type: 'assign', name: nameTok.value, value: val, line: nameTok.line };
            }

            // 表达式语句
            return this.parseExpr();
        }

        // ---- if / elif / else 语句 ----
        parseIf() {
            const ifTok = this.consume('keyword', 'if');
            const cond = this.parseExpr();
            this.consume('punct', ':');
            const thenBlock = this.parseBlockOrInline();

            let elseBlock = null;
            this.skipNewlines();
            // elif 链：转换为嵌套 if，使解释器无需修改
            if (this.peek().type === 'keyword' && this.peek().value === 'elif') {
                elseBlock = [this.parseElif()];
            }
            // 普通 else 分支
            else if (this.peek().type === 'keyword' && this.peek().value === 'else') {
                this.consume('keyword', 'else');
                this.consume('punct', ':');
                elseBlock = this.parseBlockOrInline();
            }

            return { type: 'if', cond, then: thenBlock, els: elseBlock, line: ifTok.line };
        }

        // ---- elif 分支（递归支持多个 elif）----
        parseElif() {
            const elifTok = this.consume('keyword', 'elif');
            const cond = this.parseExpr();
            this.consume('punct', ':');
            const thenBlock = this.parseBlockOrInline();

            let elseBlock = null;
            this.skipNewlines();
            // 后续 elif 链
            if (this.peek().type === 'keyword' && this.peek().value === 'elif') {
                elseBlock = [this.parseElif()];
            }
            // 终止 else 分支
            else if (this.peek().type === 'keyword' && this.peek().value === 'else') {
                this.consume('keyword', 'else');
                this.consume('punct', ':');
                elseBlock = this.parseBlockOrInline();
            }

            return { type: 'if', cond, then: thenBlock, els: elseBlock, line: elifTok.line };
        }

        // ---- while 循环 ----
        parseWhile() {
            const whileTok = this.consume('keyword', 'while');
            const cond = this.parseExpr();
            this.consume('punct', ':');
            const body = this.parseBlockOrInline();
            return { type: 'while', cond, body, line: whileTok.line };
        }

        // ---- for 循环（for i in iterable）----
        parseFor() {
            const forTok = this.consume('keyword', 'for');
            const varName = this.consume('ident').value;
            this.consume('keyword', 'in');
            const iter = this.parseExpr();
            this.consume('punct', ':');
            const body = this.parseBlockOrInline();
            return { type: 'for', var: varName, iter, body, line: forTok.line };
        }

        // 解析代码块：内联单语句 或 缩进块
        parseBlockOrInline() {
            // 内联: if x > 5: print("yes")
            if (this.peek().type !== 'newline') {
                const s = this.parseStatement();
                return s ? [s] : [];
            }

            // 缩进块
            this.skipNewlines();
            this.consume('indent');
            const stmts = [];
            this.skipNewlines();
            while (this.peek().type !== 'dedent' && this.peek().type !== 'eof') {
                const s = this.parseStatement();
                if (s) stmts.push(s);
                this.skipNewlines();
            }
            this.match('dedent');
            return stmts;
        }

        // ---- 表达式（优先级从低到高）----
        parseExpr() { return this.parseOr(); }

        parseOr() {
            let left = this.parseAnd();
            while (this.match('op', '||')) {
                const right = this.parseAnd();
                left = { type: 'binop', op: '||', left, right, line: left.line };
            }
            return left;
        }

        parseAnd() {
            let left = this.parseComp();
            while (this.match('op', '&&')) {
                const right = this.parseComp();
                left = { type: 'binop', op: '&&', left, right, line: left.line };
            }
            return left;
        }

        parseComp() {
            const left = this.parseAdd();
            const ops = ['==', '!=', '>', '<', '>=', '<='];
            if (this.peek().type === 'op' && ops.indexOf(this.peek().value) !== -1) {
                const opTok = this.consume('op');
                const right = this.parseAdd();
                return { type: 'binop', op: opTok.value, left, right, line: opTok.line };
            }
            return left;
        }

        parseAdd() {
            let left = this.parseMul();
            while (this.peek().type === 'op' && (this.peek().value === '+' || this.peek().value === '-')) {
                const opTok = this.consume('op');
                const right = this.parseMul();
                left = { type: 'binop', op: opTok.value, left, right, line: opTok.line };
            }
            return left;
        }

        parseMul() {
            let left = this.parseUnary();
            while (this.peek().type === 'op' && (this.peek().value === '*' || this.peek().value === '/' || this.peek().value === '%')) {
                const opTok = this.consume('op');
                const right = this.parseUnary();
                left = { type: 'binop', op: opTok.value, left, right, line: opTok.line };
            }
            return left;
        }

        parseUnary() {
            if (this.match('op', '!')) {
                const opTok = this.tokens[this.pos - 1];
                return { type: 'unary', op: '!', value: this.parseUnary(), line: opTok.line };
            }
            if (this.match('op', '-')) {
                const opTok = this.tokens[this.pos - 1];
                return { type: 'unary', op: '-', value: this.parseUnary(), line: opTok.line };
            }
            return this.parseCall();
        }

        parseCall() {
            let node = this.parsePrimary();
            while (true) {
                if (this.match('punct', '(')) {
                    const parenTok = this.tokens[this.pos - 1];
                    // 函数调用
                    const args = [];
                    if (!this.match('punct', ')')) {
                        args.push(this.parseExpr());
                        while (this.match('punct', ',')) {
                            args.push(this.parseExpr());
                        }
                        this.consume('punct', ')');
                    }
                    node = { type: 'call', callee: node, args, line: parenTok.line };
                } else if (this.match('punct', '[')) {
                    const bracketTok = this.tokens[this.pos - 1];
                    // 索引访问：list[0]、str[1]、dict["key"]
                    const index = this.parseExpr();
                    this.consume('punct', ']');
                    node = { type: 'index', obj: node, index, line: bracketTok.line };
                } else {
                    break;
                }
            }
            return node;
        }

        parsePrimary() {
            const t = this.peek();
            if (t.type === 'number') { this.pos++; return { type: 'literal', value: t.value, line: t.line }; }
            if (t.type === 'string') { this.pos++; return { type: 'literal', value: t.value, line: t.line }; }
            if (t.type === 'boolean') { this.pos++; return { type: 'literal', value: t.value, line: t.line }; }
            if (t.type === 'null') { this.pos++; return { type: 'literal', value: null, line: t.line }; }
            if (t.type === 'ident') { this.pos++; return { type: 'var', name: t.value, line: t.line }; }
            if (this.match('punct', '(')) {
                const parenTok = this.tokens[this.pos - 1];
                const e = this.parseExpr();
                this.consume('punct', ')');
                e.line = e.line || parenTok.line;
                return e;
            }
            // 列表字面量：[a, b, c]
            if (this.match('punct', '[')) {
                const bracketTok = this.tokens[this.pos - 1];
                const elements = [];
                if (!this.match('punct', ']')) {
                    elements.push(this.parseExpr());
                    while (this.match('punct', ',')) {
                        // 支持尾随逗号 [a, b,]
                        if (this.peek().type === 'punct' && this.peek().value === ']') break;
                        elements.push(this.parseExpr());
                    }
                    this.consume('punct', ']');
                }
                return { type: 'list', elements, line: bracketTok.line };
            }
            throw makeError(
                '语法错误：意外的 token ' + t.type + (t.value !== undefined ? ' "' + t.value + '"' : ''),
                t.line, t.column
            );
        }
    }

    // ==================================================================
    // Interpreter
    // ==================================================================
    class Interpreter {
        constructor(buildins) {
            this.vars = {};
            this.buildins = buildins || {};
            this.outputLines = [];
            // 循环最大迭代次数（防止无限循环卡死浏览器）
            this.MAX_LOOP_ITER = 100000;
            // 中止标志：外部可设置此标志来中断脚本执行
            this._aborted = false;
        }

        log(msg) { this.outputLines.push(String(msg)); }

        // 让出执行权，避免长时间循环阻塞 UI
        yieldToUI() {
            return new Promise(resolve => setTimeout(resolve, 0));
        }

        // 中止脚本执行
        abort() {
            this._aborted = true;
        }

        // 检查是否已中止，如果已中止则抛出错误
        checkAbort() {
            if (this._aborted) {
                throw makeError('脚本已被手动中止', null);
            }
        }

        async run(code) {
            this.outputLines = [];
            this._aborted = false;
            const tokens = tokenize(code);
            const parser = new Parser(tokens);
            const stmts = parser.parseAll();
            for (const stmt of stmts) {
                this.checkAbort();
                await this.eval(stmt);
            }
            return this.outputLines.join('\n');
        }

        async eval(node) {
            try {
                return await this._evalInner(node);
            } catch (err) {
                // 如果错误尚未携带行号，则用当前节点的行号补全
                if (err && err.line == null && node && node.line != null) {
                    // 如果已经是 MiniScriptError，仅补充行号
                    if (err instanceof MiniScriptError) {
                        err.line = node.line;
                        // 重建 message
                        err.message = '第 ' + node.line + ' 行：' + err.rawMessage;
                    } else {
                        const wrapped = makeError(err.message || String(err), node.line);
                        wrapped.stack = err.stack;
                        throw wrapped;
                    }
                }
                throw err;
            }
        }

        async _evalInner(node) {
            switch (node.type) {
                case 'literal': return node.value;

                case 'var':
                    if (node.name in this.buildins) return this.buildins[node.name];
                    if (node.name in this.vars) return this.vars[node.name];
                    throw makeError('未定义的变量: ' + node.name, node.line);

                case 'assign':
                    this.vars[node.name] = await this.eval(node.value);
                    return this.vars[node.name];

                case 'list': {
                    // 列表字面量：[1, 2, 3]
                    const items = [];
                    for (const e of node.elements) {
                        items.push(await this.eval(e));
                    }
                    return items;
                }

                case 'index': {
                    // 索引访问：list[0]、str[1]
                    const obj = await this.eval(node.obj);
                    const idx = await this.eval(node.index);
                    if (obj == null) {
                        throw makeError('不能对 null 进行索引', node.line);
                    }
                    // 负索引支持：-1 表示最后一个
                    if (typeof idx === 'number' && Array.isArray(obj) && idx < 0) {
                        const realIdx = obj.length + idx;
                        if (realIdx < 0) throw makeError('列表索引越界: ' + idx, node.line);
                        return obj[realIdx];
                    }
                    if (typeof idx === 'number' && typeof obj === 'string' && idx < 0) {
                        const realIdx = obj.length + idx;
                        if (realIdx < 0) throw makeError('字符串索引越界: ' + idx, node.line);
                        return obj[realIdx];
                    }
                    // 正数索引越界检查
                    if (typeof idx === 'number' && Array.isArray(obj) && idx >= obj.length) {
                        throw makeError('列表索引越界: ' + idx + '（列表长度 ' + obj.length + '）', node.line);
                    }
                    if (typeof idx === 'number' && typeof obj === 'string' && idx >= obj.length) {
                        throw makeError('字符串索引越界: ' + idx + '（字符串长度 ' + obj.length + '）', node.line);
                    }
                    if (typeof idx !== 'number' && typeof idx !== 'string') {
                        throw makeError('索引必须是数字或字符串，实际为 ' + typeof idx, node.line);
                    }
                    return obj[idx];
                }

                case 'unary': {
                    const v = await this.eval(node.value);
                    if (node.op === '!') return !v;
                    if (node.op === '-') return -v;
                    throw makeError('未知一元运算符: ' + node.op, node.line);
                }

                case 'binop': {
                    const l = await this.eval(node.left);
                    if (node.op === '||') return l || await this.eval(node.right);
                    if (node.op === '&&') return l && await this.eval(node.right);
                    const r = await this.eval(node.right);
                    switch (node.op) {
                        case '+':
                            // 列表拼接：[1,2] + [3,4] => [1,2,3,4]
                            if (Array.isArray(l) && Array.isArray(r)) return l.concat(r);
                            return typeof l === 'string' || typeof r === 'string' ? String(l) + String(r) : l + r;
                        case '-': return l - r;
                        case '*': return l * r;
                        case '/':
                            if (r === 0) throw makeError('除零错误', node.line);
                            return l / r;
                        case '%':
                            if (r === 0) throw makeError('对零取模错误', node.line);
                            return l % r;
                        case '==': return l === r;
                        case '!=': return l !== r;
                        case '>': return l > r;
                        case '<': return l < r;
                        case '>=': return l >= r;
                        case '<=': return l <= r;
                        default: throw makeError('未知运算符: ' + node.op, node.line);
                    }
                }

                case 'call': {
                    const callee = await this.eval(node.callee);
                    if (typeof callee !== 'function') {
                        // 友好描述不是函数的情况
                        let desc;
                        if (callee == null) desc = 'null';
                        else if (typeof callee === 'object') desc = JSON.stringify(callee).slice(0, 50);
                        else desc = JSON.stringify(callee);
                        throw makeError('尝试调用非函数值: ' + desc, node.line);
                    }
                    const args = [];
                    for (const a of node.args) args.push(await this.eval(a));
                    try {
                        return await callee.apply(null, args);
                    } catch (err) {
                        // 内置函数抛出的错误可能没有行号
                        if (err && err.line == null) {
                            throw makeError(err.message || String(err), node.line);
                        }
                        throw err;
                    }
                }

                // ---- if / else ----
                case 'if': {
                    const condVal = await this.eval(node.cond);
                    if (condVal) {
                        const r = await this.runBlock(node.then);
                        if (r && r.flow) return r;
                    } else if (node.els) {
                        const r = await this.runBlock(node.els);
                        if (r && r.flow) return r;
                    }
                    return null;
                }

                // ---- while 循环（带迭代上限保护 + 中止检测）----
                case 'while': {
                    let iterCount = 0;
                    while (true) {
                        this.checkAbort();
                        const condVal = await this.eval(node.cond);
                        if (!condVal) break;
                        const r = await this.runBlock(node.body);
                        if (r && r.flow === 'break') break;
                        if (r && r.flow === 'continue') continue;
                        // 防止无限循环卡死浏览器
                        if (++iterCount > this.MAX_LOOP_ITER) {
                            throw makeError('while 循环超过最大迭代次数 ' + this.MAX_LOOP_ITER + '，可能存在无限循环', node.line);
                        }
                        // 每隔 100 次让出执行权，避免阻塞 UI
                        if (iterCount % 100 === 0) {
                            await this.yieldToUI();
                        }
                    }
                    return null;
                }

                // ---- for 循环（带迭代上限保护 + 中止检测）----
                case 'for': {
                    const iterVal = await this.eval(node.iter);
                    const items = this.toIterable(iterVal);
                    let iterCount = 0;
                    for (const item of items) {
                        this.checkAbort();
                        this.vars[node.var] = item;
                        const r = await this.runBlock(node.body);
                        if (r && r.flow === 'break') break;
                        if (r && r.flow === 'continue') continue;
                        if (++iterCount > this.MAX_LOOP_ITER) {
                            throw makeError('for 循环超过最大迭代次数 ' + this.MAX_LOOP_ITER + '，可能存在无限循环', node.line);
                        }
                        if (iterCount % 100 === 0) {
                            await this.yieldToUI();
                        }
                    }
                    return null;
                }

                // ---- break / continue ----
                case 'break': return { flow: 'break' };
                case 'continue': return { flow: 'continue' };

                default:
                    throw makeError('未知节点类型: ' + node.type, node && node.line);
            }
        }

        // 执行语句块，返回 flow 控制（break/continue）或 null
        async runBlock(stmts) {
            for (const s of stmts) {
                const r = await this.eval(s);
                if (r && r.flow) return r;
            }
            return null;
        }

        // 将值转换为可迭代对象
        toIterable(val) {
            if (val == null) return [];
            // range 对象（带 __iter__ 标记）
            if (val && typeof val === 'object' && val.__isRange) {
                return val.values;
            }
            // 数组
            if (Array.isArray(val)) return val;
            // 字符串
            if (typeof val === 'string') return val.split('');
            // 对象的 key
            if (typeof val === 'object') return Object.keys(val);
            return [val];
        }
    }

    // ==================================================================
    // 值格式化（用于 print 显示）
    // ==================================================================
    function formatValue(v) {
        if (v === null || v === undefined) return 'null';
        if (typeof v === 'boolean') return v ? 'true' : 'false';
        if (typeof v === 'string') return v;
        if (typeof v === 'number') return String(v);
        if (Array.isArray(v)) {
            return '[' + v.map(formatValue).join(', ') + ']';
        }
        if (typeof v === 'object') {
            // range 对象
            if (v.__isRange && v.values) return formatValue(v.values);
            // 普通对象
            const pairs = Object.keys(v).map(k => k + ': ' + formatValue(v[k]));
            return '{' + pairs.join(', ') + '}';
        }
        return String(v);
    }

    // ==================================================================
    // 默认内置函数
    // ==================================================================
    function createDefaultBuildins(extra) {
        const b = {
            print: function (...args) {
                const formatted = args.map(formatValue);
                console.log('[MiniScript]', ...formatted);
                return formatted.join(' ');
            },
            alert: function (title, msg) {
                return window.CmdModal.alert(title || '', msg || '');
            },
            prompt: function (title, msg) {
                return window.CmdModal.prompt(title || '', msg || '', '');
            },
            confirm: function (title, msg) {
                return window.CmdModal.confirm(title || '', msg || '');
            },
            regex_test: function (str, pattern) {
                try {
                    return new RegExp(pattern).test(str || '');
                } catch (e) {
                    throw new Error('正则表达式错误: ' + e.message);
                }
            },
            regex: function (str, pattern) {
                try {
                    const m = (str || '').match(new RegExp(pattern));
                    return m || null;
                } catch (e) {
                    throw new Error('正则表达式错误: ' + e.message);
                }
            },
            sleep: function (ms) {
                return new Promise(resolve => setTimeout(resolve, Math.max(0, parseInt(ms) || 0)));
            },
            range: function (start, end, step) {
                // range(end) or range(start, end, step?)
                let s = 0, e = 0, st = 1;
                if (end === undefined) {
                    e = parseInt(start) || 0;
                    s = 0;
                } else {
                    s = parseInt(start) || 0;
                    e = parseInt(end) || 0;
                    st = step === undefined ? 1 : parseInt(step) || 1;
                }
                if (st === 0) st = 1;
                const values = [];
                if (st > 0) {
                    for (let i = s; i < e; i += st) values.push(i);
                } else {
                    for (let i = s; i > e; i += st) values.push(i);
                }
                return { __isRange: true, values, length: values.length };
            },
            set_interval: function (code, ms) {
                // 最小 100ms 间隔，防止淹没浏览器
                const delay = Math.max(100, parseInt(ms) || 0);
                // 继承当前脚本的 buildins，使 echo/cmd 等可用
                const savedBuildins = _lastBuildins || null;
                const timerCode = typeof code === 'string' ? code : String(code);
                const runner = function () {
                    _runInTimerContext(timerCode, savedBuildins || undefined);
                };
                const id = setInterval(runner, delay);
                // 记录到跟踪集合，便于清理
                _activeTimers.add(id);
                return id;
            },
            set_timeout: function (code, ms) {
                const delay = Math.max(0, parseInt(ms) || 0);
                const savedBuildins = _lastBuildins || null;
                const timerCode = typeof code === 'string' ? code : String(code);
                var id;
                const runner = function () {
                    _activeTimers.delete(id);
                    _runInTimerContext(timerCode, savedBuildins || undefined);
                };
                id = setTimeout(runner, delay);
                _activeTimers.add(id);
                return id;
            },
            clear_timer: function (id) {
                if (id == null) return;
                clearInterval(id);
                clearTimeout(id);
                _activeTimers.delete(id);
            },
            // ---- 列表函数 ----
            append: function (list, ...items) {
                if (!Array.isArray(list)) throw new Error('append 第一个参数必须是列表');
                list.push(...items);
                return list;
            },
            pop: function (list, index) {
                if (!Array.isArray(list)) throw new Error('pop 第一个参数必须是列表');
                if (index === undefined || index === null) return list.pop();
                const idx = parseInt(index);
                if (idx < 0) {
                    return list.splice(list.length + idx, 1)[0];
                }
                return list.splice(idx, 1)[0];
            },
            push: function (list, item) {
                if (!Array.isArray(list)) throw new Error('push 第一个参数必须是列表');
                list.push(item);
                return list.length;
            },
            slice: function (obj, start, end) {
                if (Array.isArray(obj) || typeof obj === 'string') {
                    return obj.slice(start, end);
                }
                throw new Error('slice 第一个参数必须是列表或字符串');
            },
            join: function (list, sep) {
                if (!Array.isArray(list)) throw new Error('join 第一个参数必须是列表');
                return list.map(formatValue).join(sep === undefined ? ',' : String(sep));
            },
            reverse: function (list) {
                if (!Array.isArray(list)) throw new Error('reverse 第一个参数必须是列表');
                return list.slice().reverse();
            },
            sort: function (list) {
                if (!Array.isArray(list)) throw new Error('sort 第一个参数必须是列表');
                return list.slice().sort(function (a, b) {
                    if (typeof a === 'number' && typeof b === 'number') return a - b;
                    return String(a) < String(b) ? -1 : 1;
                });
            },
            contains: function (obj, item) {
                if (Array.isArray(obj)) return obj.indexOf(item) !== -1;
                if (typeof obj === 'string') return obj.indexOf(String(item)) !== -1;
                if (obj && typeof obj === 'object') return item in obj;
                return false;
            },
            len: function (obj) {
                if (obj == null) return 0;
                if (typeof obj.length === 'number') return obj.length;
                if (typeof obj === 'object') return Object.keys(obj).length;
                return 0;
            },
            parseInt: function (s) { return parseInt(s, 10); },
            parseFloat: function (s) { return parseFloat(s); },
            str: function (v) { return formatValue(v); },
            now: function () { return Math.floor(Date.now() / 1000); },
        };
        if (extra) Object.assign(b, extra);
        return b;
    }

    // ==================================================================
    // Public API
    // ==================================================================
    const _activeTimers = new Set();
    let _currentInterpreter = null;
    let _lastBuildins = null;
    let _runCounter = 0;         // 递增计数器，防止旧 Promise 干扰新脚本
    let _currentRunId = 0;       // 当前正在运行的 run ID
    const SCRIPT_TIMEOUT = 30000; // 脚本最大执行时间 30 秒

    function clearAllTimers() {
        _activeTimers.forEach(function (id) {
            clearInterval(id);
            clearTimeout(id);
        });
        _activeTimers.clear();
    }

    function abort() {
        if (_currentInterpreter) {
            _currentInterpreter.abort();
        }
    }

    /**
     * 在定时器上下文中执行代码（不影响全局 _currentInterpreter）
     */
    function _runInTimerContext(code, buildins) {
        const b = createDefaultBuildins(buildins);
        const interp = new Interpreter(b);
        // 定时器代码不走全局 _currentInterpreter，避免干扰主脚本
        // 同时对定时器代码也设置超时
        const runPromise = interp.run(code);
        const timerTimeout = setTimeout(function () {
            interp.abort();
        }, SCRIPT_TIMEOUT);
        runPromise.catch(function (err) {
            // 定时器脚本出错时，输出到终端（如果可用）
            if (window.CmdTerminal && window.CmdTerminal.appendLine) {
                window.CmdTerminal.appendLine('[定时器错误] ' + err.message, 'error');
            }
        }).finally(function () {
            clearTimeout(timerTimeout);
        });
    }

    function hasActiveTimers() {
        return _activeTimers.size > 0;
    }

    return {
        tokenize: tokenize,
        Parser: Parser,
        Interpreter: Interpreter,
        createDefaultBuildins: createDefaultBuildins,
        formatValue: formatValue,
        _activeTimers: _activeTimers,
        // 使用 getter 确保 _lastBuildins 始终返回最新值
        get _lastBuildins() { return _lastBuildins; },
        clearAllTimers: clearAllTimers,
        abort: abort,
        hasActiveTimers: hasActiveTimers,
        isRunning: function () { return _currentInterpreter !== null; },
        async run(code, buildins) {
            // 递增 run ID，用于防止旧 Promise 的 finally 干扰新脚本
            _runCounter++;
            const myRunId = _runCounter;
            _currentRunId = myRunId;

            const b = createDefaultBuildins(buildins);
            _lastBuildins = b;
            const interp = new Interpreter(b);
            _currentInterpreter = interp;

            // 脚本超时保护：使用 Promise.race 强制中断
            let timeoutTid = null;
            const scriptPromise = interp.run(code);
            // 防止超时后 scriptPromise reject 变成 unhandled rejection
            scriptPromise.catch(function () {});

            const timeoutPromise = new Promise(function (_, reject) {
                timeoutTid = setTimeout(function () {
                    interp.abort();
                    reject(new Error('脚本执行超时（' + (SCRIPT_TIMEOUT / 1000) + '秒），已被自动中止'));
                }, SCRIPT_TIMEOUT);
            });

            try {
                return await Promise.race([scriptPromise, timeoutPromise]);
            } finally {
                if (timeoutTid) clearTimeout(timeoutTid);
                // 仅当本次 run 仍然是当前 run 时，才清除 _currentInterpreter
                if (_currentRunId === myRunId) {
                    _currentInterpreter = null;
                }
            }
        }
    };
})();
