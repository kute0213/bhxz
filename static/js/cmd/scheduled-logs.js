/**
 * scheduled-logs.js — 定时任务执行日志查看（拆分自原 scheduled.js）
 *
 * 职责：
 *   - 打开「执行日志」模态框（全部日志 / 单任务日志）
 *   - 分页加载日志列表
 *   - 点击日志条目查看完整输出
 *   - ESC / 点击遮罩关闭（已由 scheduled.js 统一处理）
 *
 * 暴露：window.ScheduledLogs.openLogsModal(taskId | null)
 *
 * 依赖：在本文件之前加载的 scheduled.js 暴露的 window.ScheduledCore.escapeHtml
 */

window.ScheduledLogs = (function () {
    'use strict';

    // DOM 引用（模态框元素由模板提供）
    var logsModal = document.getElementById('logs-modal');
    var logsContent = document.getElementById('logs-content');
    var logsPagination = document.getElementById('logs-pagination');
    var outputModal = document.getElementById('output-modal');
    var outputContent = document.getElementById('output-content');

    // 分页状态
    var PER_PAGE = 20;
    var currentPage = 1;
    var totalPages = 1;
    var currentTaskId = null;  // null = 全部任务日志

    // ------------------------------------------------------------------
    // 对外接口
    // ------------------------------------------------------------------

    /**
     * 打开日志模态框。
     * @param {number|null} taskId  任务 ID；null 表示查看全部日志
     */
    function openLogsModal(taskId) {
        currentTaskId = taskId || null;
        currentPage = 1;
        logsModal.classList.remove('hidden');
        loadLogs();
    }

    // ------------------------------------------------------------------
    // 加载日志列表
    // ------------------------------------------------------------------

    function loadLogs() {
        logsContent.innerHTML =
            '<div class="text-center text-cream/40 py-8">加载中…</div>';
        logsPagination.innerHTML = '';

        var url = currentTaskId
            ? '/admin/cmd/scheduled/tasks/' + currentTaskId + '/logs?page=' + currentPage + '&per_page=' + PER_PAGE
            : '/admin/cmd/scheduled/logs?page=' + currentPage + '&per_page=' + PER_PAGE;

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                totalPages = data.total_pages || 1;
                renderLogs(data.logs || []);
                renderPagination();
            })
            .catch(function (err) {
                logsContent.innerHTML =
                    '<div class="text-center text-red-300 py-8">加载失败: ' +
                    escapeHtml(String(err)) + '</div>';
            });
    }

    function renderLogs(logs) {
        if (!logs.length) {
            logsContent.innerHTML =
                '<div class="text-center text-cream/40 py-8">暂无执行日志</div>';
            return;
        }

        logsContent.innerHTML = logs.map(function (log) {
            return buildLogItem(log);
        }).join('');

        // 绑定点击查看详情
        logsContent.querySelectorAll('[data-log-id]').forEach(function (el) {
            el.addEventListener('click', function () {
                var logId = parseInt(el.dataset.logId);
                showLogDetail(logId);
            });
        });

        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }
    }

    function buildLogItem(log) {
        var successBadge = log.success
            ? '<span class="px-1.5 py-0.5 text-xs rounded-full bg-green-500/20 text-green-300 border border-green-400/20">成功</span>'
            : '<span class="px-1.5 py-0.5 text-xs rounded-full bg-red-500/20 text-red-300 border border-red-400/20">失败</span>';

        var exitCodeText = (log.exit_code === null || log.exit_code === undefined)
            ? '—'
            : ('退出码 ' + log.exit_code);

        var durationText = (typeof log.duration_seconds === 'number')
            ? log.duration_seconds.toFixed(1) + 's'
            : '—';

        // 任务名（仅在「全部日志」视图下显示）
        var taskNameBlock = currentTaskId
            ? ''
            : '<div class="text-xs text-cream/40 mt-0.5">任务: ' + escapeHtml(log.task_name || ('#' + log.task_id)) + '</div>';

        return '<div data-log-id="' + log.id + '" ' +
            'class="bg-forest-900/40 border border-cream/10 rounded-lg p-3 cursor-pointer hover:bg-forest-900/70 transition-colors">' +
                '<div class="flex items-center justify-between gap-2 flex-wrap">' +
                    '<div class="flex items-center gap-2 flex-wrap">' +
                        successBadge +
                        '<span class="text-xs text-cream/40">' + escapeHtml(log.started_at || '') + '</span>' +
                        '<span class="text-xs text-cream/40">· ' + durationText + '</span>' +
                        '<span class="text-xs text-cream/40">· ' + exitCodeText + '</span>' +
                    '</div>' +
                    '<i data-lucide="chevron-right" class="w-4 h-4 text-cream/30"></i>' +
                '</div>' +
                taskNameBlock +
                '<div class="text-xs text-cream/50 font-mono mt-1 truncate">' +
                    escapeHtml(log.command || '') +
                '</div>' +
            '</div>';
    }

    // ------------------------------------------------------------------
    // 分页
    // ------------------------------------------------------------------

    function renderPagination() {
        if (totalPages <= 1) {
            logsPagination.innerHTML =
                '<span class="text-xs text-cream/40">共 ' + totalPages + ' 页</span>';
            return;
        }

        var html = '';
        // 上一页
        html += paginationBtn('‹', currentPage > 1 ? currentPage - 1 : null);

        // 页码：最多显示 7 个，过多则用省略号
        var pages = buildPageNumbers(currentPage, totalPages);
        pages.forEach(function (p) {
            if (p === '...') {
                html += '<span class="px-2 text-cream/40">…</span>';
            } else {
                html += paginationBtn(String(p), p, p === currentPage);
            }
        });

        // 下一页
        html += paginationBtn('›', currentPage < totalPages ? currentPage + 1 : null);

        logsPagination.innerHTML = html;

        logsPagination.querySelectorAll('[data-page]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var p = parseInt(btn.dataset.page);
                if (!isNaN(p) && p !== currentPage) {
                    currentPage = p;
                    loadLogs();
                }
            });
        });
    }

    function paginationBtn(label, page, isActive) {
        if (page === null) {
            return '<button disabled class="px-2.5 py-1 text-xs rounded text-cream/20 cursor-not-allowed">' +
                label + '</button>';
        }
        var cls = isActive
            ? 'bg-gold-400 text-forest-900 font-bold'
            : 'bg-forest-700/60 border border-cream/10 text-cream/70 hover:bg-forest-600/60';
        return '<button data-page="' + page + '" ' +
            'class="px-2.5 py-1 text-xs rounded ' + cls + ' transition-colors">' + label + '</button>';
    }

    function buildPageNumbers(current, total) {
        // 简单的页码窗口算法：始终包含首尾、当前页前后 2 页
        var result = [];
        var left = Math.max(1, current - 2);
        var right = Math.min(total, current + 2);

        if (left > 1) {
            result.push(1);
            if (left > 2) result.push('...');
        }
        for (var i = left; i <= right; i++) {
            result.push(i);
        }
        if (right < total) {
            if (right < total - 1) result.push('...');
            result.push(total);
        }
        return result;
    }

    // ------------------------------------------------------------------
    // 日志详情（完整输出）
    // ------------------------------------------------------------------

    function showLogDetail(logId) {
        outputContent.textContent = '加载中…';
        outputModal.classList.remove('hidden');

        fetch('/admin/cmd/scheduled/logs/' + logId)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (log) {
                var parts = [];
                parts.push('任务: ' + (log.task_name || ('#' + log.task_id)));
                parts.push('命令: ' + (log.command || ''));
                parts.push('开始: ' + (log.started_at || ''));
                parts.push('结束: ' + (log.finished_at || ''));
                parts.push('耗时: ' +
                    (typeof log.duration_seconds === 'number'
                        ? log.duration_seconds.toFixed(2) + 's' : '—'));
                parts.push('退出码: ' +
                    (log.exit_code === null || log.exit_code === undefined
                        ? '—' : log.exit_code));
                parts.push('结果: ' + (log.success ? '成功' : '失败'));
                parts.push('----------------------------------------');
                parts.push(log.output || '(无输出)');
                outputContent.textContent = parts.join('\n');
            })
            .catch(function (err) {
                outputContent.textContent = '加载失败: ' + err;
            });
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------

    function escapeHtml(str) {
        // 复用 ScheduledCore.escapeHtml；若未加载则使用本地实现
        if (window.ScheduledCore && window.ScheduledCore.escapeHtml) {
            return window.ScheduledCore.escapeHtml(str);
        }
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    return {
        openLogsModal: openLogsModal,
    };
})();
