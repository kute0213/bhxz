// 统一 Markdown / 富文本编辑器引擎
// —— 默认「富文本（所见即所得）」模式，底层数据与保存内容始终是 Markdown；
//    可无缝切换到「Markdown 源码 + 实时预览」模式。
// 依赖：lib/marked/marked.min.js、lib/purify/purify.min.js
// 结构见 templates/macros/markdown_editor.html（全站唯一实现）
(function () {
    'use strict';

    /* ============================================================
     * 常量
     * ============================================================ */

    // Markdown 表格分隔行每列至少的破折号数量
    var DASH_MIN = 3;
    // 列宽百分比 → 破折号数量的比例（同时决定表格可细分的粒度）
    var DASH_PER_PERCENT = 0.4;
    // 拖拽调整列宽时每列的最小宽度（%）
    var COL_MIN_PERCENT = 8;

    // 序列化时按「块级」处理的标签
    var BLOCK_EL = {
        P: 1, DIV: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1,
        UL: 1, OL: 1, BLOCKQUOTE: 1, PRE: 1, TABLE: 1, HR: 1,
        SECTION: 1, ARTICLE: 1, HEADER: 1, FOOTER: 1, MAIN: 1,
        ASIDE: 1, NAV: 1, FIGURE: 1, ADDRESS: 1, DL: 1, DT: 1, DD: 1
    };

    // 原样保留为内联 HTML 的标签（Markdown 不支持的常见内联语义）
    var RAW_INLINE_EL = { SUB: 1, SUP: 1, MARK: 1, U: 1, KBD: 1, ABBR: 1, SMALL: 1 };

    /* ============================================================
     * 通用工具
     * ============================================================ */

    function repeat(s, n) {
        var out = '';
        for (var i = 0; i < n; i++) out += s;
        return out;
    }

    function sum(arr) {
        var t = 0;
        for (var i = 0; i < arr.length; i++) t += arr[i];
        return t;
    }

    function closestTag(node, names) {
        var list = names.split(' ');
        while (node && node.nodeType !== 1) node = node.parentNode;
        while (node) {
            if (node.nodeType === 1 && list.indexOf(node.tagName) !== -1) return node;
            node = node.parentNode;
        }
        return null;
    }

    function cellIndex(cell) {
        var i = 0, c = cell;
        while ((c = c.previousElementSibling)) i++;
        return i;
    }

    function rowCells(row) {
        return Array.prototype.slice.call(row.cells || []);
    }

    function columnCount(table) {
        var n = 0, rows = table.rows;
        for (var i = 0; i < rows.length; i++) n = Math.max(n, rows[i].cells.length);
        return n;
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // 列宽百分比的「默认破折号数组」（等宽）
    function defaultCols(n) {
        var d = Math.max(DASH_MIN, Math.round((100 / Math.max(n, 1)) * DASH_PER_PERCENT));
        var arr = [];
        for (var i = 0; i < n; i++) arr.push(d);
        return arr;
    }

    /* ============================================================
     * Markdown 表格解析（供 MD → HTML 时恢复列宽 / 对齐）
     * 表格列宽编码规则：分隔行中每列的破折号数量 ∝ 该列宽度。
     * ============================================================ */

    function isDelimCell(cell) {
        return /^\s*:?-+:?\s*$/.test(cell);
    }

    function countDashes(cell) {
        var m = String(cell).match(/-+/);
        return m ? Math.max(DASH_MIN, m[0].length) : DASH_MIN;
    }

    function cellAlign(cell) {
        var s = String(cell).trim();
        var left = s.charAt(0) === ':';
        var right = s.charAt(s.length - 1) === ':';
        if (left && right) return 'center';
        if (left) return 'left';
        if (right) return 'right';
        return '';
    }

    // 按未转义的 | 拆分表格行
    function splitRow(line) {
        var s = String(line).trim();
        if (s.charAt(0) === '|') s = s.slice(1);
        if (s.charAt(s.length - 1) === '|' && s.charAt(s.length - 2) !== '\\') s = s.slice(0, -1);
        var cells = [], cur = '';
        for (var i = 0; i < s.length; i++) {
            var ch = s.charAt(i);
            if (ch === '\\' && i + 1 < s.length) { cur += ch + s.charAt(i + 1); i++; continue; }
            if (ch === '|') { cells.push(cur.trim()); cur = ''; continue; }
            cur += ch;
        }
        cells.push(cur.trim());
        return cells;
    }

    function isTableRow(line) {
        return String(line).indexOf('|') !== -1 && /^\s*\|?.*\|\s*$/.test(line);
    }

    // 扫描整篇 Markdown，按出现顺序收集表格的列宽 / 对齐信息
    function scanTables(md) {
        var lines = String(md || '').split('\n');
        var out = [];
        var inFence = false;
        var fenceChar = '';
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var fence = line.match(/^\s*(```+|~~~+)/);
            if (fence) {
                var ch = fence[1].charAt(0);
                if (!inFence) { inFence = true; fenceChar = ch; }
                else if (ch === fenceChar) { inFence = false; }
                continue;
            }
            if (inFence) continue;
            if (/^( {4,}|\t)/.test(line)) continue; // 缩进代码块
            var next = lines[i + 1];
            if (line.indexOf('|') === -1 || next == null || next.indexOf('|') === -1) continue;
            if (!isTableRow(line) || !isTableRow(next)) continue;
            var header = splitRow(line);
            var delim = splitRow(next);
            if (!delim.length || !delim.every(isDelimCell)) continue;
            if (header.length !== delim.length) continue;
            out.push({ cols: delim.map(countDashes), aligns: delim.map(cellAlign) });
        }
        return out;
    }

    // 读取表格当前列宽（破折号数组），缺失时按等宽兜底
    function readColDashes(table, n) {
        var raw = String(table.getAttribute('data-cols') || '').split(',');
        var out = [];
        var def = defaultCols(n);
        for (var i = 0; i < n; i++) {
            var v = parseInt(raw[i], 10);
            out.push(v > 0 ? v : def[i]);
        }
        return out;
    }

    function inferAligns(table, n) {
        var out = [];
        var firstRow = table.rows[0];
        for (var i = 0; i < n; i++) {
            var cell = firstRow ? firstRow.cells[i] : null;
            var a = '';
            if (cell) {
                a = cell.getAttribute('align') || (cell.style && cell.style.textAlign) || '';
            }
            a = String(a).toLowerCase();
            out.push(a === 'left' || a === 'center' || a === 'right' ? a : '');
        }
        return out;
    }

    function readColAligns(table, n) {
        if (!table.hasAttribute('data-aligns')) return inferAligns(table, n);
        var raw = String(table.getAttribute('data-aligns')).split(',');
        var out = [];
        for (var i = 0; i < n; i++) {
            var v = String(raw[i] || '').trim().toLowerCase();
            out.push(v === 'left' || v === 'center' || v === 'right' ? v : '');
        }
        return out;
    }

    function delimLine(cols, aligns) {
        var parts = [];
        for (var i = 0; i < cols.length; i++) {
            var n = Math.max(DASH_MIN, cols[i]);
            var a = aligns[i] || '';
            if (a === 'center') parts.push(':' + repeat('-', Math.max(1, n - 2)) + ':');
            else if (a === 'left') parts.push(':' + repeat('-', n - 1));
            else if (a === 'right') parts.push(repeat('-', n - 1) + ':');
            else parts.push(repeat('-', n));
        }
        return '| ' + parts.join(' | ') + ' |';
    }

    /* ============================================================
     * HTML → Markdown
     * ============================================================ */

    function normalizeInlineText(t) {
        return String(t).replace(/[ \t]*\n[ \t]*/g, ' ');
    }

    function escapeInline(text, inTable) {
        if (!text) return '';
        var out = String(text)
            .replace(/\\/g, '\\\\')
            .replace(/([`*_\[\]~])/g, '\\$1');
        if (inTable) out = out.replace(/\|/g, '\\|');
        return out;
    }

    function inlineCode(text) {
        text = String(text).replace(/\n/g, ' ');
        var ticks = '`';
        if (text.indexOf('`') !== -1) {
            var runs = text.match(/`+/g) || [];
            var max = 1;
            for (var i = 0; i < runs.length; i++) max = Math.max(max, runs[i].length);
            ticks = repeat('`', max + 1);
        }
        var pad = (text.charAt(0) === '`' || text.charAt(text.length - 1) === '`' || text.charAt(0) === ' ' || text.charAt(text.length - 1) === ' ') ? ' ' : '';
        return ticks + pad + text + pad + ticks;
    }

    function inlineOf(el, ctx) {
        var s = '';
        var nodes = el.childNodes;
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            if (n.nodeType === 3) {
                s += escapeInline(normalizeInlineText(n.nodeValue), ctx.inTable);
            } else if (n.nodeType === 1) {
                if (BLOCK_EL[n.tagName]) {
                    s += '\n\n' + serializeBlock(n, ctx);
                } else {
                    s += serializeInline(n, ctx);
                }
            }
        }
        return s;
    }

    function serializeInline(el, ctx) {
        switch (el.tagName) {
            case 'STRONG': case 'B':
                return '**' + inlineOf(el, ctx).trim() + '**';
            case 'EM': case 'I':
                return '*' + inlineOf(el, ctx).trim() + '*';
            case 'DEL': case 'S': case 'STRIKE':
                return '~~' + inlineOf(el, ctx).trim() + '~~';
            case 'CODE':
                return inlineCode(el.textContent);
            case 'A': {
                var href = el.getAttribute('href') || '';
                var text = inlineOf(el, ctx).trim() || href;
                var title = el.getAttribute('title');
                return '[' + text + '](' + href + (title ? ' "' + String(title).replace(/"/g, '\\"') + '"' : '') + ')';
            }
            case 'IMG': {
                var src = el.getAttribute('src') || '';
                var alt = el.getAttribute('alt') || '';
                var t = el.getAttribute('title');
                return '![' + alt + '](' + src + (t ? ' "' + String(t).replace(/"/g, '\\"') + '"' : '') + ')';
            }
            case 'BR':
                return ctx.inTable ? '<br>' : '\\\n';
            case 'INPUT':
                return ''; // 任务列表复选框由列表序列化统一处理
            case 'SPAN':
                return inlineOf(el, ctx);
            default:
                if (RAW_INLINE_EL[el.tagName]) return el.outerHTML;
                return inlineOf(el, ctx);
        }
    }

    // 列表项内容（复选框由外层统一输出，这里跳过）
    function serializeListItem(li, ctx) {
        var arr = [];
        serializeBlocks(li, arr, ctx);
        return arr.join('\n').replace(/^\s+/, '');
    }

    function directCheckbox(li) {
        var nodes = li.children;
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].tagName === 'INPUT' && (nodes[i].type || '').toLowerCase() === 'checkbox') return nodes[i];
        }
        var cb = li.querySelector('input[type="checkbox"]');
        return cb || null;
    }

    function serializeList(list, ctx) {
        var ordered = list.tagName === 'OL';
        var start = parseInt(list.getAttribute('start') || '1', 10);
        if (!(start > 0)) start = 1;
        var items = [];
        for (var i = 0; i < list.children.length; i++) {
            if (list.children[i].tagName === 'LI') items.push(list.children[i]);
        }
        var lines = [];
        for (var k = 0; k < items.length; k++) {
            var li = items[k];
            var body = serializeListItem(li, ctx);
            var prefix = ordered ? (start + k) + '. ' : '- ';
            var marker = '';
            var cb = ordered ? null : directCheckbox(li);
            if (cb) marker = cb.checked ? '[x] ' : '[ ] ';
            var indent = repeat(' ', prefix.length);
            var bodyLines = body.split('\n');
            var first = bodyLines.shift() || '';
            lines.push(prefix + marker + first);
            for (var j = 0; j < bodyLines.length; j++) {
                lines.push(bodyLines[j] ? indent + bodyLines[j] : '');
            }
        }
        return lines.join('\n');
    }

    function serializeBlockquote(bq, ctx) {
        var arr = [];
        serializeBlocks(bq, arr, ctx);
        var inner = arr.join('\n\n');
        var ls = inner.split('\n');
        var out = [];
        for (var i = 0; i < ls.length; i++) out.push(ls[i] ? '> ' + ls[i] : '>');
        return out.join('\n');
    }

    function serializeCodeBlock(pre) {
        var code = pre.querySelector('code');
        var text = code ? code.textContent : pre.textContent;
        var lang = '';
        if (code) {
            var m = String(code.className || '').match(/language-([\w+#.-]+)/);
            if (m) lang = m[1];
        }
        var fence = '```';
        while (text.indexOf(fence) !== -1) fence += '`';
        return fence + lang + '\n' + String(text).replace(/\n+$/, '') + '\n' + fence;
    }

    function tableRowLine(cells, n, ctx) {
        var parts = [];
        for (var i = 0; i < n; i++) {
            var cell = cells[i];
            var text = cell ? inlineOf(cell, { inTable: true }) : '';
            text = text.replace(/^\s+|\s+$/g, '');
            if (/^(<br\s*\/?>)+$/i.test(text)) text = '';
            text = text.replace(/\n+/g, '<br>');
            parts.push(text);
        }
        return '| ' + parts.join(' | ') + ' |';
    }

    function serializeTable(table) {
        var allRows = Array.prototype.slice.call(table.rows);
        if (!allRows.length) return '';
        var headerRow = table.tHead && table.tHead.rows[0] ? table.tHead.rows[0] : allRows[0];
        var bodyRows = allRows.filter(function (r) { return r !== headerRow; });
        var headerCells = rowCells(headerRow);
        var n = headerCells.length;
        for (var i = 0; i < bodyRows.length; i++) n = Math.max(n, bodyRows[i].cells.length);
        if (n === 0) return '';
        var cols = readColDashes(table, n);
        var aligns = readColAligns(table, n);
        var lines = [tableRowLine(headerCells, n)];
        lines.push(delimLine(cols, aligns));
        for (var r = 0; r < bodyRows.length; r++) lines.push(tableRowLine(rowCells(bodyRows[r]), n));
        return lines.join('\n');
    }

    function serializeBlock(el, ctx) {
        switch (el.tagName) {
            case 'H1': case 'H2': case 'H3': case 'H4': case 'H5': case 'H6':
                return repeat('#', parseInt(el.tagName.charAt(1), 10)) + ' ' + inlineOf(el, ctx).trim();
            case 'P':
                return inlineOf(el, ctx).trim();
            case 'UL': case 'OL':
                return serializeList(el, ctx);
            case 'BLOCKQUOTE':
                return serializeBlockquote(el, ctx);
            case 'PRE':
                return serializeCodeBlock(el);
            case 'HR':
                return '---';
            case 'TABLE':
                return serializeTable(el);
            default: {
                var arr = [];
                serializeBlocks(el, arr, ctx);
                return arr.join('\n\n');
            }
        }
    }

    function serializeBlocks(parent, out, ctx) {
        var inlineBuf = [];
        function flush() {
            var t = inlineBuf.join('');
            inlineBuf = [];
            t = t.replace(/[ \t]+$/, '');
            if (t.trim()) out.push(t);
        }
        var nodes = parent.childNodes;
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            if (n.nodeType === 3) {
                var v = n.nodeValue;
                if (!v) continue;
                if (!/\S/.test(v)) {
                    if (inlineBuf.length) inlineBuf.push(' ');
                    continue;
                }
                inlineBuf.push(escapeInline(normalizeInlineText(v), ctx.inTable));
            } else if (n.nodeType === 1) {
                if (BLOCK_EL[n.tagName]) {
                    flush();
                    var b = serializeBlock(n, ctx);
                    if (b !== '') out.push(b);
                } else if (n.tagName === 'BR') {
                    inlineBuf.push(ctx.inTable ? '<br>' : '\\\n');
                } else if (n.tagName === 'INPUT') {
                    // 顶层游离复选框：忽略
                } else {
                    inlineBuf.push(serializeInline(n, ctx));
                }
            }
        }
        flush();
    }

    function htmlToMarkdown(root) {
        var out = [];
        serializeBlocks(root, out, { inTable: false });
        return out.join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
    }

    /* ============================================================
     * Markdown → HTML
     * ============================================================ */

    function sanitizeHtml(html) {
        if (typeof window.DOMPurify === 'undefined') return html;
        try {
            return window.DOMPurify.sanitize(html, {
                ADD_TAGS: ['col', 'colgroup'],
                ADD_ATTR: ['align', 'colspan', 'rowspan', 'start', 'type', 'checked', 'disabled', 'target', 'rel'],
                ALLOW_DATA_ATTR: true
            });
        } catch (e) {
            return html;
        }
    }

    // 写入表格的列宽 / 对齐元信息并生成 colgroup
    function applyTableMeta(table, cols, aligns) {
        var n = cols.length;
        table.setAttribute('data-cols', cols.join(','));
        table.setAttribute('data-aligns', aligns.join(','));

        var old = table.querySelector('colgroup');
        if (old && old.parentNode) old.parentNode.removeChild(old);

        var total = sum(cols) || 1;
        var cg = document.createElement('colgroup');
        for (var i = 0; i < n; i++) {
            var col = document.createElement('col');
            col.style.width = (cols[i] / total * 100).toFixed(2) + '%';
            cg.appendChild(col);
        }
        table.insertBefore(cg, table.firstChild);

        var rows = table.rows;
        for (var r = 0; r < rows.length; r++) {
            var cells = rows[r].cells;
            for (var c = 0; c < cells.length; c++) {
                var a = aligns[c] || '';
                cells[c].style.textAlign = a;
                cells[c].removeAttribute('align');
            }
        }
    }

    function enableTaskCheckboxes(container) {
        var lists = container.querySelectorAll('ul, ol');
        for (var i = 0; i < lists.length; i++) {
            var list = lists[i];
            var items = list.children;
            var hasTask = false;
            for (var j = 0; j < items.length; j++) {
                if (items[j].tagName !== 'LI') continue;
                var cb = directCheckbox(items[j]);
                if (!cb) continue;
                hasTask = true;
                cb.disabled = false;
                cb.removeAttribute('disabled');
                cb.setAttribute('contenteditable', 'false');
                items[j].classList.add('mre-task-item');
            }
            if (hasTask) list.classList.add('mre-task-list');
        }
    }

    function ensureMarked() {
        if (!window.marked) return;
        try { window.marked.use({ gfm: true, breaks: false, pedantic: false }); } catch (e) { /* 忽略 */ }
    }

    function mdToHtml(md) {
        var infos = scanTables(md);
        var raw;
        if (window.marked && window.marked.parse) {
            try { raw = window.marked.parse(md || ''); } catch (e) { raw = ''; }
        } else {
            raw = md ? '<p>' + escapeHtml(md) + '</p>' : '';
        }
        var wrap = document.createElement('div');
        wrap.innerHTML = sanitizeHtml(raw);

        var tables = wrap.querySelectorAll('table');
        for (var i = 0; i < tables.length; i++) {
            var table = tables[i];
            var n = columnCount(table);
            var info = infos[i];
            var cols = (info && info.cols.length === n) ? info.cols : defaultCols(n);
            var aligns = (info && info.aligns.length === n) ? info.aligns : inferAligns(table, n);
            applyTableMeta(table, cols, aligns);
        }
        enableTaskCheckboxes(wrap);
        return wrap.innerHTML;
    }

    /* ============================================================
     * Markdown 源码模式下的表格定位 / 读写
     * ============================================================ */

    function readMdTableAt(text, pos) {
        var lines = String(text || '').split('\n');
        var starts = [];
        var acc = 0;
        for (var i = 0; i < lines.length; i++) { starts.push(acc); acc += lines[i].length + 1; }

        var li = lines.length - 1;
        for (var k = 0; k < lines.length; k++) {
            if (pos <= starts[k] + lines[k].length) { li = k; break; }
        }
        if (!/\|/.test(lines[li] || '')) return null;

        var s = li, e = li;
        while (s - 1 >= 0 && lines[s - 1].trim() !== '' && /\|/.test(lines[s - 1])) s--;
        while (e + 1 < lines.length && lines[e + 1].trim() !== '' && /\|/.test(lines[e + 1])) e++;
        if (e - s < 1) return null;

        var rows = [];
        for (var r = s; r <= e; r++) rows.push(splitRow(lines[r]));
        if (rows.length < 2 || !rows[1].every(isDelimCell)) return null;

        var header = rows[0];
        var aligns = rows[1].map(cellAlign);
        var cols = rows[1].map(countDashes);
        var body = rows.slice(2);
        var n = Math.max(header.length, cols.length);
        for (var b = 0; b < body.length; b++) n = Math.max(n, body[b].length);
        while (header.length < n) header.push('');
        for (var b2 = 0; b2 < body.length; b2++) { while (body[b2].length < n) body[b2].push(''); }
        while (cols.length < n) cols.push(defaultCols(n)[cols.length]);
        while (aligns.length < n) aligns.push('');

        var offset = pos - starts[li];
        var lineText = lines[li];
        var pipes = 0;
        for (var p = 0; p < offset && p < lineText.length; p++) {
            if (lineText.charAt(p) === '|' && lineText.charAt(p - 1) !== '\\') pipes++;
        }
        var curCol = Math.max(0, Math.min(pipes - 1, n - 1));
        var allRow = (li === s) ? 0 : (li - s - 1); // 0 = 表头，其余为 body 下标 +1

        return {
            lines: lines, start: s, end: e, n: n,
            header: header, body: body, cols: cols, aligns: aligns,
            curRow: allRow, curCol: curCol, lineIndex: li
        };
    }

    function renderMdTable(model) {
        var lines = [];
        lines.push('| ' + model.header.join(' | ') + ' |');
        lines.push(delimLine(model.cols, model.aligns));
        for (var i = 0; i < model.body.length; i++) {
            lines.push('| ' + model.body[i].join(' | ') + ' |');
        }
        return lines;
    }

    /* ============================================================
     * 编辑器实例
     * ============================================================ */

    function Editor(root) {
        this.root = root;
        this.rich = root.querySelector('[data-mre-rich]');
        this.scroll = root.querySelector('[data-mre-scroll]');
        this.overlay = root.querySelector('[data-mre-overlay]');
        this.richWrap = root.querySelector('[data-mre-rich-wrap]');
        this.mdWrap = root.querySelector('[data-mre-md]');
        this.textarea = root.querySelector('textarea');
        this.preview = root.querySelector('[data-md-preview]');
        this.counts = root.querySelectorAll('[data-md-count]');
        this.mode = 'rich';
        this.activeTable = null;
        this.savedRange = null;
        this.syncTimer = null;
        this.pop = null;
    }

    Editor.prototype.init = function () {
        if (!this.rich || !this.textarea) return;
        var self = this;

        try {
            document.execCommand('defaultParagraphSeparator', false, 'p');
            document.execCommand('styleWithCSS', false, false);
        } catch (e) { /* 忽略 */ }

        ensureMarked();
        this.renderRich(this.textarea.value || '');
        this.applyMode('rich');

        // 编辑区输入
        this.rich.addEventListener('input', function () { self.scheduleSync(); self.updateToolbar(); self.refreshActiveTable(); });
        this.rich.addEventListener('keyup', function () { self.updateToolbar(); });
        this.rich.addEventListener('mouseup', function () { self.updateToolbar(); self.refreshActiveTable(); });
        this.rich.addEventListener('blur', function () { self.syncNow(); });
        this.rich.addEventListener('change', function (e) {
            var t = e.target;
            if (t && t.tagName === 'INPUT' && (t.type || '').toLowerCase() === 'checkbox') self.syncNow();
        });
        this.rich.addEventListener('mouseover', function (e) {
            var t = closestTag(e.target, 'TABLE');
            if (t && self.rich.contains(t)) self.setActiveTable(t);
        });
        this.rich.addEventListener('mouseleave', function () { self.setActiveTable(null); });
        this.rich.addEventListener('mousedown', function (e) {
            if (!closestTag(e.target, 'TABLE')) self.setActiveTable(null);
        });

        // Markdown 源码区
        this.textarea.addEventListener('input', function () { self.onMdChange(); });
        this.textarea.addEventListener('keyup', function () { self.updateToolbar(); });
        this.textarea.addEventListener('click', function () { self.updateToolbar(); });
        this.textarea.addEventListener('mouseup', function () { self.updateToolbar(); });
        this.textarea.addEventListener('select', function () { self.updateToolbar(); });

        // 标签页
        this.root.querySelectorAll('[data-mre-tab]').forEach(function (btn) {
            btn.addEventListener('click', function () { self.selectTab(btn.getAttribute('data-mre-tab')); });
        });
        // 模式切换
        this.root.querySelectorAll('[data-mre-mode]').forEach(function (btn) {
            btn.addEventListener('click', function () { self.setMode(btn.getAttribute('data-mre-mode')); });
        });
        // 工具栏：mousedown 阻止默认，保持编辑区选区不丢
        this.root.querySelectorAll('.mre-btn').forEach(function (btn) {
            btn.addEventListener('mousedown', function (e) { e.preventDefault(); });
            btn.addEventListener('click', function () { self.runCommand(btn.getAttribute('data-mre-cmd')); });
        });

        // 全局选区变化
        document.addEventListener('selectionchange', function () {
            if (self.mode === 'rich') { self.updateToolbar(); self.refreshActiveTable(); }
            else self.updateToolbar();
        });

        // 滚动 / 尺寸变化时刷新拖拽手柄
        if (this.scroll) this.scroll.addEventListener('scroll', function () { self.updateGrips(); });
        window.addEventListener('resize', function () { self.updateGrips(); });

        // 表单提交前强制把富文本同步为 Markdown
        var form = this.root.closest('form');
        if (form) {
            form.addEventListener('submit', function () { self.syncNow(); }, true);
        }

        this.onMdChange();
        this.updateToolbar();
        this.refreshIcons();
    };

    Editor.prototype.refreshIcons = function () {
        if (typeof window.lucide !== 'undefined' && window.lucide.createIcons) {
            try { window.lucide.createIcons({ root: this.root }); } catch (e) { /* 忽略 */ }
        }
    };

    /* ---------- 模式 ---------- */

    Editor.prototype.applyMode = function (mode) {
        this.mode = mode;
        var richOn = mode === 'rich';
        if (this.richWrap) this.richWrap.hidden = !richOn;
        if (this.mdWrap) this.mdWrap.hidden = richOn;
        this.root.querySelectorAll('[data-mre-mode]').forEach(function (btn) {
            btn.classList.toggle('is-active', btn.getAttribute('data-mre-mode') === mode);
        });
        if (!richOn) this.setActiveTable(null);
    };

    Editor.prototype.setMode = function (mode) {
        if (!mode || mode === this.mode) return;
        if (mode === 'markdown') {
            // 富文本 → Markdown：序列化并保留大致光标位置
            var offset = this.richCaretOffset();
            this.syncNow();
            this.applyMode('markdown');
            this.setMdCaret(this.mdOffsetOf(this.textarea, offset));
            this.textarea.focus();
        } else {
            // Markdown → 富文本：重新渲染并还原大致光标位置
            var md = this.textarea.value || '';
            var sel = this.textarea.selectionStart;
            this.mdCharOffset = sel;
            this.renderRich(md);
            this.applyMode('rich');
            this.setRichCaret(this.mdCharOffset);
            this.rich.focus();
        }
        this.onMdChange();
        this.updateToolbar();
    };

    Editor.prototype.selectTab = function (name) {
        this.root.querySelectorAll('[data-mre-tab]').forEach(function (btn) {
            btn.classList.toggle('is-active', btn.getAttribute('data-mre-tab') === name);
        });
        this.root.querySelectorAll('[data-mre-panel]').forEach(function (p) {
            p.hidden = p.getAttribute('data-mre-panel') !== name;
        });
    };

    /* ---------- 内容同步 ---------- */

    Editor.prototype.serializeRich = function () {
        if (!this.rich) return '';
        return htmlToMarkdown(this.rich);
    };

    Editor.prototype.renderRich = function (md) {
        if (!this.rich) return;
        this.rich.innerHTML = mdToHtml(md || '');
    };

    Editor.prototype.scheduleSync = function () {
        var self = this;
        clearTimeout(this.syncTimer);
        this.syncTimer = setTimeout(function () { self.syncNow(); }, 160);
    };

    Editor.prototype.syncNow = function () {
        if (this.mode !== 'rich') { this.updateCount(); return; }
        clearTimeout(this.syncTimer);
        var md = this.serializeRich();
        this.textarea.value = md;
        this.updateCount();
        this.updateGrips();
    };

    Editor.prototype.onMdChange = function () {
        this.updateCount();
        this.updatePreview();
        this.updateGrips();
    };

    Editor.prototype.updateCount = function () {
        var n = (this.textarea.value || '').length;
        for (var i = 0; i < this.counts.length; i++) this.counts[i].textContent = n + ' 字';
    };

    Editor.prototype.updatePreview = function () {
        if (!this.preview) return;
        this.preview.innerHTML = mdToHtml(this.textarea.value || '');
    };

    /* ---------- 光标工具 ---------- */

    Editor.prototype.getRichRange = function () {
        var sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return null;
        var r = sel.getRangeAt(0);
        if (!this.rich.contains(r.startContainer)) return null;
        return r;
    };

    Editor.prototype.richCaretOffset = function () {
        var r = this.getRichRange();
        if (!r) return 0;
        var pre = r.cloneRange();
        pre.selectNodeContents(this.rich);
        try { pre.setEnd(r.endContainer, r.endOffset); } catch (e) { return 0; }
        return pre.toString().length;
    };

    Editor.prototype.mdOffsetOf = function (ta, plainOffset) {
        // 富文本纯文本偏移 → Markdown 偏移：按字符近似映射
        var md = ta.value || '';
        var plain = this.rich ? this.rich.textContent : '';
        if (!plain || plainOffset >= plain.length) return md.length;
        var ratio = plainOffset / plain.length;
        return Math.min(md.length, Math.round(ratio * md.length));
    };

    Editor.prototype.setMdCaret = function (offset) {
        try { this.textarea.setSelectionRange(offset, offset); } catch (e) { /* 忽略 */ }
    };

    Editor.prototype.setRichCaret = function (mdOffset) {
        var md = this.textarea.value || '';
        var ratio = md.length ? Math.min(1, mdOffset / md.length) : 0;
        var walker = document.createTreeWalker(this.rich, NodeFilter.SHOW_TEXT, null);
        var total = this.rich.textContent.length;
        var target = Math.round(ratio * total);
        var acc = 0, node, last = null;
        while ((node = walker.nextNode())) {
            last = node;
            if (acc + node.nodeValue.length >= target) {
                this.placeCaret(node, target - acc);
                return;
            }
            acc += node.nodeValue.length;
        }
        if (last) this.placeCaret(last, last.nodeValue.length);
    };

    Editor.prototype.placeCaret = function (node, offset) {
        try {
            var r = document.createRange();
            r.setStart(node, Math.max(0, Math.min(offset, node.nodeValue.length)));
            r.collapse(true);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(r);
        } catch (e) { /* 忽略 */ }
    };

    function placeCaretAtStart(el) {
        try {
            var r = document.createRange();
            r.selectNodeContents(el);
            r.collapse(true);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(r);
        } catch (e) { /* 忽略 */ }
    }

    /* ---------- 工具栏可用态 / 激活态 ---------- */

    Editor.prototype.updateToolbar = function () {
        var mode = this.mode;
        var focusedRich = this.rich && (document.activeElement === this.rich || this.rich.contains(document.activeElement));
        var range = mode === 'rich' ? this.getRichRange() : null;
        var cell = mode === 'rich' ? closestTag(range ? range.startContainer : null, 'TD TH') : null;

        var caret, sel, inTable;
        if (mode === 'rich') {
            caret = focusedRich || !!range;
            sel = !!range && !range.collapsed;
            inTable = !!cell;
        } else {
            caret = document.activeElement === this.textarea;
            sel = caret && this.textarea.selectionStart !== this.textarea.selectionEnd;
            inTable = caret && !!readMdTableAt(this.textarea.value, this.textarea.selectionStart);
        }

        var btns = this.root.querySelectorAll('[data-mre-need]');
        for (var i = 0; i < btns.length; i++) {
            var need = btns[i].getAttribute('data-mre-need');
            var ok;
            if (need === 'sel') ok = sel;
            else if (need === 'table') ok = caret && inTable;
            else ok = caret;
            btns[i].disabled = !ok;
        }
        this.updateActiveStates(cell);
    };

    Editor.prototype.updateActiveStates = function (cell) {
        var state = {};
        if (this.mode === 'rich') {
            try {
                state.bold = document.queryCommandState('bold');
                state.italic = document.queryCommandState('italic');
                state.strike = document.queryCommandState('strikeThrough');
                state.ul = document.queryCommandState('insertUnorderedList');
                state.ol = document.queryCommandState('insertOrderedList');
            } catch (e) { /* 忽略 */ }
            var range = this.getRichRange();
            var node = range ? range.startContainer : null;
            state.h1 = !!closestTag(node, 'H1');
            state.h2 = !!closestTag(node, 'H2');
            state.h3 = !!closestTag(node, 'H3');
            state.h4 = !!closestTag(node, 'H4');
            state.quote = !!closestTag(node, 'BLOCKQUOTE');
            state.code = !!closestTag(node, 'CODE');
            state.link = !!closestTag(node, 'A');
            state.image = !!closestTag(node, 'IMG');
            var li = closestTag(node, 'LI');
            state.task = !!(li && directCheckbox(li));
            if (cell) {
                var table = closestTag(cell, 'TABLE');
                var idx = cellIndex(cell);
                var a = readColAligns(table, columnCount(table))[idx] || '';
                if (a === 'left') state['align-left'] = true;
                if (a === 'center') state['align-center'] = true;
                if (a === 'right') state['align-right'] = true;
            }
        } else {
            state = this.mdActiveStates();
        }

        var btns = this.root.querySelectorAll('.mre-btn[data-mre-cmd]');
        for (var i = 0; i < btns.length; i++) {
            var cmd = btns[i].getAttribute('data-mre-cmd');
            btns[i].classList.toggle('is-active', !!state[cmd]);
        }
    };

    Editor.prototype.mdActiveStates = function () {
        var st = {};
        var ta = this.textarea;
        var v = ta.value || '';
        var pos = ta.selectionStart;
        var ls = v.lastIndexOf('\n', pos - 1) + 1;
        var le = v.indexOf('\n', pos);
        if (le === -1) le = v.length;
        var line = v.slice(ls, le);
        st.h1 = /^#\s/.test(line);
        st.h2 = /^##\s/.test(line) && !/^###/.test(line);
        st.h3 = /^###\s/.test(line) && !/^####/.test(line);
        st.h4 = /^####\s/.test(line);
        st.quote = /^>\s?/.test(line);
        st.ul = /^[-*+]\s/.test(line) && !/^[-*+]\s\[[ xX]\]/.test(line);
        st.ol = /^\d+\.\s/.test(line);
        st.task = /^[-*+]\s\[[ xX]\]/.test(line);
        st.hr = /^---+\s*$/.test(line);
        return st;
    };

    /* ---------- 命令执行 ---------- */

    Editor.prototype.runCommand = function (cmd) {
        if (!cmd) return;
        if (this.mode === 'rich') this.execRich(cmd);
        else this.execMd(cmd);
        this.updateToolbar();
    };

    Editor.prototype.afterRichChange = function () {
        this.syncNow();
        this.updateToolbar();
    };

    Editor.prototype.execRich = function (cmd) {
        this.rich.focus();
        var cell;
        switch (cmd) {
            case 'bold': document.execCommand('bold'); break;
            case 'italic': document.execCommand('italic'); break;
            case 'strike': document.execCommand('strikeThrough'); break;
            case 'code': this.toggleInlineCode(); break;
            case 'clear': this.clearFormat(); break;
            case 'h1': this.toggleBlock('H1'); break;
            case 'h2': this.toggleBlock('H2'); break;
            case 'h3': this.toggleBlock('H3'); break;
            case 'h4': this.toggleBlock('H4'); break;
            case 'quote': this.toggleBlock('BLOCKQUOTE'); break;
            case 'ul': document.execCommand('insertUnorderedList'); break;
            case 'ol': document.execCommand('insertOrderedList'); break;
            case 'task': this.insertTaskList(); break;
            case 'hr': {
                var hr = document.createElement('hr');
                this.insertBlock(hr);
                break;
            }
            case 'indent': document.execCommand('indent'); break;
            case 'outdent': document.execCommand('outdent'); break;
            case 'link': this.askUrl('link'); return;
            case 'image': this.askUrl('image'); return;
            case 'codeblock': this.insertCodeBlock(); break;
            case 'table-create': this.insertTable(3, 3); break;
            case 'row-above': case 'row-below': case 'row-delete':
            case 'col-left': case 'col-right': case 'col-delete':
            case 'table-delete': case 'align-left': case 'align-center': case 'align-right':
                cell = this.currentCell();
                if (cell) this.tableOp(cmd, cell);
                break;
            default:
                return;
        }
        this.afterRichChange();
    };

    Editor.prototype.currentCell = function () {
        var r = this.getRichRange();
        if (!r) return null;
        return closestTag(r.startContainer, 'TD TH');
    };

    Editor.prototype.toggleBlock = function (tag) {
        var r = this.getRichRange();
        var cur = r ? closestTag(r.startContainer, 'H1 H2 H3 H4 H5 H6 BLOCKQUOTE P') : null;
        var curTag = cur ? cur.tagName : null;
        document.execCommand('formatBlock', false, curTag === tag ? 'P' : tag);
    };

    Editor.prototype.toggleInlineCode = function () {
        var r = this.getRichRange();
        if (!r || r.collapsed) return;
        var code = closestTag(r.startContainer, 'CODE');
        if (code && !closestTag(code, 'PRE')) {
            var parent = code.parentNode;
            while (code.firstChild) parent.insertBefore(code.firstChild, code);
            parent.removeChild(code);
            return;
        }
        var el = document.createElement('code');
        try {
            r.surroundContents(el);
        } catch (e) {
            var frag = r.extractContents();
            el.appendChild(frag);
            r.insertNode(el);
        }
    };

    Editor.prototype.clearFormat = function () {
        var r = this.getRichRange();
        document.execCommand('removeFormat');
        if (r) {
            var code = closestTag(r.startContainer, 'CODE');
            if (code && !closestTag(code, 'PRE') && code.parentNode) {
                while (code.firstChild) code.parentNode.insertBefore(code.firstChild, code);
                code.parentNode.removeChild(code);
            }
        }
    };

    Editor.prototype.insertTaskList = function () {
        var ul = document.createElement('ul');
        ul.className = 'mre-task-list';
        for (var i = 0; i < 2; i++) {
            var li = document.createElement('li');
            li.className = 'mre-task-item';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.setAttribute('contenteditable', 'false');
            li.appendChild(cb);
            li.appendChild(document.createTextNode(' 任务' + (i + 1)));
            ul.appendChild(li);
        }
        this.insertBlock(ul);
    };

    Editor.prototype.insertCodeBlock = function () {
        var pre = document.createElement('pre');
        var code = document.createElement('code');
        var r = this.getRichRange();
        code.textContent = (r && !r.collapsed) ? r.toString() : '代码';
        pre.appendChild(code);
        this.insertBlock(pre);
    };

    Editor.prototype.insertTable = function (rows, cols) {
        var n = Math.max(1, cols);
        var dashes = defaultCols(n);
        var aligns = [];
        for (var i = 0; i < n; i++) aligns.push('');

        var table = document.createElement('table');
        var thead = document.createElement('thead');
        var htr = document.createElement('tr');
        for (var c = 0; c < n; c++) {
            var th = document.createElement('th');
            th.textContent = '表头' + (c + 1);
            htr.appendChild(th);
        }
        thead.appendChild(htr);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        for (var r = 0; r < Math.max(1, rows - 1); r++) {
            var tr = document.createElement('tr');
            for (var c2 = 0; c2 < n; c2++) {
                var td = document.createElement('td');
                td.appendChild(document.createElement('br'));
                tr.appendChild(td);
            }
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        applyTableMeta(table, dashes, aligns);

        this.insertBlock(table);
        var firstTh = table.rows[0] ? table.rows[0].cells[0] : null;
        if (firstTh) placeCaretAtStart(firstTh);
    };

    // 在光标处插入块级元素（自动与上下文段落分离）
    Editor.prototype.insertBlock = function (node) {
        var range = this.getRichRange();
        if (!range) {
            this.rich.appendChild(node);
        } else {
            var top = topLevelChild(this.rich, range.startContainer);
            if (top && top.nodeType === 1 && top.tagName !== 'LI') {
                var isEmpty = !top.textContent.replace(/\s/g, '') && !top.querySelector('img,table,hr,pre');
                if (isEmpty) top.parentNode.replaceChild(node, top);
                else top.parentNode.insertBefore(node, top.nextSibling);
                var p = document.createElement('p');
                p.appendChild(document.createElement('br'));
                node.parentNode.insertBefore(p, node.nextSibling);
                placeCaretAtStart(p);
            } else {
                range.deleteContents();
                range.insertNode(node);
            }
        }
        this.syncNow();
    };

    function topLevelChild(root, node) {
        while (node && node.parentNode && node.parentNode !== root) node = node.parentNode;
        if (!node || node.parentNode !== root) return null;
        return node;
    }

    /* ---------- 富文本表格操作 ---------- */

    Editor.prototype.tableOp = function (cmd, cell) {
        var table = closestTag(cell, 'TABLE');
        if (!table) return;
        var row = cell.parentNode;
        var idx = cellIndex(cell);
        var n = columnCount(table);
        var cols = readColDashes(table, n);
        var aligns = readColAligns(table, n);

        switch (cmd) {
            case 'row-above':
            case 'row-below': {
                var tr = document.createElement('tr');
                for (var c = 0; c < n; c++) {
                    var td = document.createElement('td');
                    td.appendChild(document.createElement('br'));
                    tr.appendChild(td);
                }
                row.parentNode.insertBefore(tr, cmd === 'row-above' ? row : row.nextSibling);
                break;
            }
            case 'row-delete': {
                if (table.rows.length <= 1) { table.parentNode.removeChild(table); this.setActiveTable(null); return; }
                row.parentNode.removeChild(row);
                break;
            }
            case 'col-left':
            case 'col-right': {
                var pos = cmd === 'col-left' ? idx : idx + 1;
                var rows = table.rows;
                for (var i = 0; i < rows.length; i++) {
                    var newCell = rows[i].insertCell(Math.min(pos, rows[i].cells.length));
                    newCell.appendChild(document.createElement('br'));
                }
                var avg = Math.max(DASH_MIN, Math.round(sum(cols) / Math.max(cols.length, 1)));
                cols.splice(pos, 0, avg);
                aligns.splice(pos, 0, '');
                applyTableMeta(table, cols, aligns);
                break;
            }
            case 'col-delete': {
                if (n <= 1) { table.parentNode.removeChild(table); this.setActiveTable(null); return; }
                var rows2 = table.rows;
                for (var j = 0; j < rows2.length; j++) {
                    if (rows2[j].cells.length > idx) rows2[j].deleteCell(idx);
                }
                cols.splice(idx, 1);
                aligns.splice(idx, 1);
                applyTableMeta(table, cols, aligns);
                break;
            }
            case 'table-delete':
                table.parentNode.removeChild(table);
                this.setActiveTable(null);
                return;
            case 'align-left':
            case 'align-center':
            case 'align-right': {
                var a = cmd.replace('align-', '');
                aligns[idx] = aligns[idx] === a ? '' : a;
                applyTableMeta(table, cols, aligns);
                break;
            }
            default:
                return;
        }
        this.setActiveTable(table);
        this.afterRichChange();
    };

    /* ---------- 列宽拖拽 ---------- */

    Editor.prototype.setActiveTable = function (table) {
        if (this.activeTable === table) { this.updateGrips(); return; }
        this.activeTable = table;
        this.updateGrips();
    };

    Editor.prototype.refreshActiveTable = function () {
        var cell = this.currentCell();
        if (cell) {
            var table = closestTag(cell, 'TABLE');
            if (table) { this.activeTable = table; this.updateGrips(); }
        }
    };

    Editor.prototype.updateGrips = function () {
        if (!this.overlay) return;
        this.overlay.innerHTML = '';
        if (this.mode !== 'rich') { this.overlay.classList.remove('is-on'); return; }
        var table = this.activeTable;
        if (!table || !this.rich.contains(table)) {
            this.overlay.classList.remove('is-on');
            this.activeTable = null;
            return;
        }
        var n = columnCount(table);
        if (n < 2 || !table.rows.length) { this.overlay.classList.remove('is-on'); return; }

        var scrollRect = this.scroll.getBoundingClientRect();
        var tableRect = table.getBoundingClientRect();
        var firstRow = table.rows[0];

        for (var i = 0; i < n - 1; i++) {
            var cell = firstRow.cells[i];
            if (!cell) continue;
            var rect = cell.getBoundingClientRect();
            var grip = document.createElement('div');
            grip.className = 'mre-grip';
            grip.style.left = (rect.right - scrollRect.left + this.scroll.scrollLeft - 4) + 'px';
            grip.style.top = (tableRect.top - scrollRect.top + this.scroll.scrollTop) + 'px';
            grip.style.height = Math.min(tableRect.height, 26) + 'px';
            grip.setAttribute('data-index', String(i));
            this.bindGrip(grip, table, i);
            this.overlay.appendChild(grip);
        }
        this.overlay.classList.add('is-on');
    };

    Editor.prototype.bindGrip = function (grip, table, index) {
        var self = this;
        grip.addEventListener('mousedown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var cols = table.querySelectorAll('colgroup > col');
            var firstRow = table.rows[0];
            if (!cols.length || !firstRow || !firstRow.cells[index] || !firstRow.cells[index + 1]) return;

            var totalPx = table.getBoundingClientRect().width || 1;
            var startX = e.clientX;
            var wL = firstRow.cells[index].getBoundingClientRect().width;
            var wR = firstRow.cells[index + 1].getBoundingClientRect().width;
            var minPx = totalPx * COL_MIN_PERCENT / 100;

            function onMove(ev) {
                var delta = ev.clientX - startX;
                var nl = wL + delta;
                var nr = wR - delta;
                if (nl < minPx) { nr -= (minPx - nl); nl = minPx; }
                if (nr < minPx) { nl -= (minPx - nr); nr = minPx; }
                cols[index].style.width = (nl / totalPx * 100) + '%';
                cols[index + 1].style.width = (nr / totalPx * 100) + '%';
                self.updateGrips();
            }
            function onUp() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.classList.remove('mre-resizing');
                self.commitColWidths(table);
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
            document.body.classList.add('mre-resizing');
        });
    };

    // 把像素列宽换算回 Markdown 分隔行的破折号数量（列宽即「边框大小」）
    Editor.prototype.commitColWidths = function (table) {
        var cols = table.querySelectorAll('colgroup > col');
        var n = cols.length;
        if (!n) return;
        var pcts = [];
        var total = 0;
        for (var i = 0; i < n; i++) {
            var w = parseFloat(cols[i].style.width) || 0;
            pcts.push(w);
            total += w;
        }
        if (total <= 0) return;
        var n2 = columnCount(table);
        var old = readColDashes(table, n2);
        var dashTotal = sum(old);
        var dashes = [];
        for (var j = 0; j < n2; j++) {
            dashes.push(Math.max(DASH_MIN, Math.round((pcts[j] || 0) / total * dashTotal)));
        }
        var aligns = readColAligns(table, n2);
        applyTableMeta(table, dashes, aligns);
        this.afterRichChange();
    };

    /* ---------- 链接 / 图片浮层 ---------- */

    Editor.prototype.askUrl = function (kind) {
        var self = this;
        this.closePop();

        if (this.mode === 'rich') {
            var r = this.getRichRange();
            this.savedRange = r ? r.cloneRange() : null;
        }

        var pop = document.createElement('div');
        pop.className = 'mre-pop';
        var input = document.createElement('input');
        input.type = 'text';
        input.placeholder = kind === 'link' ? 'https://链接地址' : 'https://图片地址';
        var ok = document.createElement('button');
        ok.type = 'button';
        ok.textContent = '确定';
        pop.appendChild(input);
        pop.appendChild(ok);
        document.body.appendChild(pop);
        this.pop = pop;

        var anchor = this.root.querySelector('[data-mre-cmd="' + kind + '"]');
        var rect = anchor ? anchor.getBoundingClientRect() : { left: 40, bottom: 120, width: 0 };
        var left = Math.max(8, Math.min(rect.left, window.innerWidth - pop.offsetWidth - 8));
        pop.style.left = left + 'px';
        pop.style.top = (rect.bottom + 4) + 'px';
        input.focus();

        function close() {
            document.removeEventListener('mousedown', onDoc, true);
            document.removeEventListener('keydown', onKey, true);
            if (pop.parentNode) pop.parentNode.removeChild(pop);
            self.pop = null;
        }
        function commit() {
            var url = input.value.trim();
            close();
            if (!url) return;
            self.applyUrl(kind, url);
        }
        function onDoc(ev) {
            if (!pop.contains(ev.target)) close();
        }
        function onKey(ev) {
            if (ev.key === 'Escape') close();
            else if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
        }
        ok.addEventListener('click', commit);
        document.addEventListener('mousedown', onDoc, true);
        document.addEventListener('keydown', onKey, true);
    };

    Editor.prototype.closePop = function () {
        if (this.pop && this.pop.parentNode) this.pop.parentNode.removeChild(this.pop);
        this.pop = null;
    };

    Editor.prototype.applyUrl = function (kind, url) {
        if (this.mode === 'rich') {
            this.rich.focus();
            var sel = window.getSelection();
            var range = this.savedRange;
            if (range) {
                try { sel.removeAllRanges(); sel.addRange(range); } catch (e) { /* 忽略 */ }
            }
            var r = this.getRichRange();
            if (!r) return;
            if (kind === 'link') {
                var a = document.createElement('a');
                a.setAttribute('href', url);
                if (r.collapsed) {
                    a.textContent = url;
                    r.insertNode(a);
                    placeCaretAfter(a);
                } else {
                    this.wrapRange(r, a);
                }
            } else {
                var img = document.createElement('img');
                img.setAttribute('src', url);
                img.setAttribute('alt', '');
                r.deleteContents();
                r.insertNode(img);
                placeCaretAfter(img);
            }
            this.afterRichChange();
        } else {
            if (kind === 'link') this.mdWrap('[' + this.selectedMdText() + '](' + url + ')', '');
            else this.mdInsert('![' + this.selectedMdText() + '](' + url + ')');
            this.onMdChange();
            this.updateToolbar();
        }
    };

    Editor.prototype.wrapRange = function (range, el) {
        try {
            range.surroundContents(el);
        } catch (e) {
            var frag = range.extractContents();
            el.appendChild(frag);
            range.insertNode(el);
        }
        placeCaretAfter(el);
    };

    function placeCaretAfter(el) {
        try {
            var r = document.createRange();
            r.setStartAfter(el);
            r.collapse(true);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(r);
        } catch (e) { /* 忽略 */ }
    }

    /* ---------- Markdown 源码模式命令 ---------- */

    Editor.prototype.selectedMdText = function () {
        return this.textarea.value.slice(this.textarea.selectionStart, this.textarea.selectionEnd);
    };

    Editor.prototype.mdWrap = function (before, after) {
        if (after === undefined) after = '';
        var ta = this.textarea;
        var v = ta.value;
        var s = ta.selectionStart, e = ta.selectionEnd;
        var sel = v.slice(s, e);
        // 已包裹则取消
        if (sel && before && v.slice(s - before.length, s) === before && v.slice(e, e + after.length) === after) {
            ta.value = v.slice(0, s - before.length) + sel + v.slice(e + after.length);
            ta.setSelectionRange(s - before.length, s - before.length + sel.length);
        } else {
            ta.value = v.slice(0, s) + before + sel + after + v.slice(e);
            ta.setSelectionRange(s + before.length, s + before.length + sel.length);
        }
        ta.focus();
    };

    Editor.prototype.mdInsert = function (text) {
        var ta = this.textarea;
        var v = ta.value;
        var s = ta.selectionStart, e = ta.selectionEnd;
        ta.value = v.slice(0, s) + text + v.slice(e);
        ta.setSelectionRange(s + text.length, s + text.length);
        ta.focus();
    };

    Editor.prototype.mdLinePrefix = function (prefix, ordered) {
        var ta = this.textarea;
        var v = ta.value;
        var s = ta.selectionStart, e = ta.selectionEnd;
        var ls = v.lastIndexOf('\n', s - 1) + 1;
        var le = v.indexOf('\n', e);
        if (le === -1) le = v.length;
        var block = v.slice(ls, le);
        var lines = block.split('\n');
        var stripRe = /^(#{1,6}\s|>\s?|[-*+]\s(\[[ xX]\]\s)?|\d+\.\s)/;
        var allHave = lines.every(function (l) { return l.indexOf(prefix) === 0 && l !== ''; });
        var out = lines.map(function (l, i) {
            if (allHave) return l.slice(prefix.length);
            var stripped = l.replace(stripRe, '');
            return (ordered ? (i + 1) + '. ' : prefix) + stripped;
        }).join('\n');
        ta.value = v.slice(0, ls) + out + v.slice(le);
        ta.setSelectionRange(ls, ls + out.length);
        ta.focus();
    };

    Editor.prototype.mdIndent = function (dir) {
        var ta = this.textarea;
        var v = ta.value;
        var s = ta.selectionStart, e = ta.selectionEnd;
        var ls = v.lastIndexOf('\n', s - 1) + 1;
        var le = v.indexOf('\n', e);
        if (le === -1) le = v.length;
        var lines = v.slice(ls, le).split('\n');
        var pad = dir > 0 ? '  ' : '';
        var out = lines.map(function (l) {
            if (dir > 0) return '  ' + l;
            return l.replace(/^ {1,2}/, '');
        }).join('\n');
        void pad;
        ta.value = v.slice(0, ls) + out + v.slice(le);
        ta.setSelectionRange(ls, ls + out.length);
        ta.focus();
    };

    Editor.prototype.execMd = function (cmd) {
        switch (cmd) {
            case 'bold': this.mdWrap('**', '**'); break;
            case 'italic': this.mdWrap('*', '*'); break;
            case 'strike': this.mdWrap('~~', '~~'); break;
            case 'code': this.mdWrap('`', '`'); break;
            case 'clear': {
                var v = this.textarea.value;
                var s = this.textarea.selectionStart, e = this.textarea.selectionEnd;
                var sel = v.slice(s, e).replace(/(\*\*|\*|~~|`)/g, '');
                this.textarea.value = v.slice(0, s) + sel + v.slice(e);
                this.textarea.setSelectionRange(s, s + sel.length);
                break;
            }
            case 'h1': this.mdLinePrefix('# '); break;
            case 'h2': this.mdLinePrefix('## '); break;
            case 'h3': this.mdLinePrefix('### '); break;
            case 'h4': this.mdLinePrefix('#### '); break;
            case 'quote': this.mdLinePrefix('> '); break;
            case 'ul': this.mdLinePrefix('- '); break;
            case 'ol': this.mdLinePrefix('1. ', true); break;
            case 'task': this.mdLinePrefix('- [ ] '); break;
            case 'hr': this.mdInsert('\n\n---\n\n'); break;
            case 'indent': this.mdIndent(1); break;
            case 'outdent': this.mdIndent(-1); break;
            case 'link': this.askUrl('link'); return;
            case 'image': this.askUrl('image'); return;
            case 'codeblock': this.mdCodeBlock(); break;
            case 'table-create': this.mdInsertTable(); break;
            case 'row-above': case 'row-below': case 'row-delete':
            case 'col-left': case 'col-right': case 'col-delete':
            case 'table-delete': case 'align-left': case 'align-center': case 'align-right':
                this.mdTableOp(cmd);
                break;
            default:
                return;
        }
        this.onMdChange();
    };

    Editor.prototype.mdCodeBlock = function () {
        var sel = this.selectedMdText();
        this.mdWrap('```\n' + sel + '\n```', '');
    };

    Editor.prototype.mdInsertTable = function () {
        var cols = defaultCols(3);
        var aligns = ['', '', ''];
        var tpl = [];
        tpl.push('| 表头1 | 表头2 | 表头3 |');
        tpl.push(delimLine(cols, aligns));
        tpl.push('|  |  |  |');
        tpl.push('|  |  |  |');
        var ta = this.textarea;
        var before = ta.value.slice(0, ta.selectionStart);
        var needLf = (before === '' || before.slice(-1) === '\n') ? '' : '\n\n';
        this.mdInsert(needLf + tpl.join('\n') + '\n');
    };

    Editor.prototype.mdTableOp = function (cmd) {
        var ta = this.textarea;
        var model = readMdTableAt(ta.value, ta.selectionStart);
        if (!model) return;
        var rowIdx = model.curRow; // 0 = 表头
        var colIdx = model.curCol;
        var isHeader = rowIdx === 0;
        var bodyIdx = rowIdx - 1;

        switch (cmd) {
            case 'row-above':
            case 'row-below': {
                var blank = [];
                for (var i = 0; i < model.n; i++) blank.push('');
                var at = isHeader ? (cmd === 'row-above' ? 0 : 1) : (cmd === 'row-above' ? bodyIdx : bodyIdx + 1);
                model.body.splice(at, 0, blank.slice());
                break;
            }
            case 'row-delete': {
                if (isHeader) {
                    if (model.body.length) { model.header = model.body.shift(); }
                    else { this.mdDeleteTable(model); return; }
                } else {
                    model.body.splice(bodyIdx, 1);
                    if (!model.body.length) { this.mdDeleteTable(model); return; }
                }
                break;
            }
            case 'col-left':
            case 'col-right': {
                var pos = cmd === 'col-left' ? colIdx : colIdx + 1;
                model.header.splice(pos, 0, '');
                for (var b = 0; b < model.body.length; b++) model.body[b].splice(pos, 0, '');
                var avg = Math.max(DASH_MIN, Math.round(sum(model.cols) / model.cols.length));
                model.cols.splice(pos, 0, avg);
                model.aligns.splice(pos, 0, '');
                break;
            }
            case 'col-delete': {
                if (model.n <= 1) { this.mdDeleteTable(model); return; }
                model.header.splice(colIdx, 1);
                for (var b2 = 0; b2 < model.body.length; b2++) model.body[b2].splice(colIdx, 1);
                model.cols.splice(colIdx, 1);
                model.aligns.splice(colIdx, 1);
                break;
            }
            case 'table-delete':
                this.mdDeleteTable(model);
                return;
            case 'align-left':
            case 'align-center':
            case 'align-right': {
                var a = cmd.replace('align-', '');
                model.aligns[colIdx] = model.aligns[colIdx] === a ? '' : a;
                break;
            }
            default:
                return;
        }
        this.writeMdTable(model);
    };

    Editor.prototype.mdDeleteTable = function (model) {
        var lines = model.lines.slice();
        lines.splice(model.start, model.end - model.start + 1);
        this.textarea.value = lines.join('\n');
        var pos = Math.max(0, model.start - 1);
        this.textarea.setSelectionRange(pos, pos);
        this.onMdChange();
    };

    Editor.prototype.writeMdTable = function (model) {
        var newLines = renderMdTable(model);
        var lines = model.lines.slice();
        lines.splice(model.start, model.end - model.start + 1, newLines.join('\n'));
        this.textarea.value = lines.join('\n');
        var pos = 0;
        for (var i = 0; i < model.start; i++) pos += lines[i].length + 1;
        this.textarea.setSelectionRange(pos, pos);
        this.textarea.focus();
        this.onMdChange();
    };

    /* ============================================================
     * 初始化
     * ============================================================ */

    function mount(root) {
        if (!root || root.__mreMounted) return root && root.__mre;
        var editor = new Editor(root);
        editor.init();
        root.__mreMounted = true;
        root.__mre = editor;
        return editor;
    }

    function initAll() {
        document.querySelectorAll('[data-mre]').forEach(function (root) { mount(root); });
    }

    var observer = null;
    function startObserver() {
        if (observer || !document.body) return;
        observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var added = mutations[i].addedNodes;
                for (var j = 0; j < added.length; j++) {
                    var node = added[j];
                    if (node.nodeType !== 1) continue;
                    if (node.matches && node.matches('[data-mre]')) mount(node);
                    else if (node.querySelectorAll) node.querySelectorAll('[data-mre]').forEach(function (r) { mount(r); });
                }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initAll(); startObserver(); });
    } else {
        initAll();
        startObserver();
    }

    // 对外暴露（也便于自动化测试）
    window.MarkdownEditor = {
        mount: mount,
        htmlToMarkdown: htmlToMarkdown,
        markdownToHtml: mdToHtml,
        scanTables: scanTables,
        splitRow: splitRow,
        delimLine: delimLine,
        defaultCols: defaultCols,
        readMdTableAt: readMdTableAt,
        renderMdTable: renderMdTable
    };
})();
