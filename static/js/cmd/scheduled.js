/**
 * scheduled.js — 定时任务管理页面逻辑（核心：任务 CRUD / 启停 / 触发 / 状态轮询）
 *
 * 由原 scheduled.js 拆分而来，本文件负责：
 *   - 任务列表加载与渲染
 *   - 创建/编辑/删除/启停/立即触发任务
 *   - 自动刷新任务执行状态
 *   - 调度类型 / 任务类型切换
 *   - 模态框（任务编辑）事件绑定
 *
 * 暴露：window.ScheduledCore
 *      escapeHtml：HTML 转义工具（供 scheduled-logs.js 复用）
 *
 * 配套文件（在本文件之后加载）：
 *   - scheduled-logs.js → window.ScheduledLogs（执行日志查看）
 *      日志相关按钮通过 window.ScheduledLogs.openLogsModal 调用
 */

window.ScheduledCore = (function () {
    'use strict';

    // DOM 引用（任务管理相关；日志/输出模态框的关闭逻辑也在此处理）
    var createBtn = document.getElementById('create-task-btn');
    var viewLogsBtn = document.getElementById('view-logs-btn');
    var taskModal = document.getElementById('task-modal');
    var taskForm = document.getElementById('task-form');
    var taskModalCancel = document.getElementById('task-modal-cancel');
    var taskModalTitle = document.getElementById('task-modal-title');
    var scheduleTypeSelect = document.getElementById('task-schedule-type');
    var taskTypeSelect = document.getElementById('task-type');
    var taskCommandLabel = document.getElementById('task-command-label');
    var taskCommandInput = document.getElementById('task-command');
    var intervalConfig = document.getElementById('interval-config');
    var timeConfig = document.getElementById('time-config');
    var timeLabel = document.getElementById('time-label');
    var logsModal = document.getElementById('logs-modal');
    var logsModalClose = document.getElementById('logs-modal-close');
    var outputModal = document.getElementById('output-modal');
    var outputModalClose = document.getElementById('output-modal-close');
    var taskListContainer = document.getElementById('task-list-container');
    var emptyState = document.getElementById('empty-state');

    // 自动刷新相关
    var AUTO_REFRESH_INTERVAL = 15000;  // 15 秒刷新一次状态
    var autoRefreshTimer = null;
    var tasksCache = [];              // 缓存最近一次任务列表，避免重渲染打断交互
    var statusCache = {};              // 缓存任务执行状态

    // ------------------------------------------------------------------
    // 初始化
    // ------------------------------------------------------------------

    document.addEventListener('DOMContentLoaded', function () {
        loadTasks();
        bindEvents();
        startAutoRefresh();
    });

    function bindEvents() {
        createBtn.addEventListener('click', openCreateModal);
        // 查看日志：交给 scheduled-logs.js 处理
        viewLogsBtn.addEventListener('click', function () { window.ScheduledLogs.openLogsModal(null); });
        taskModalCancel.addEventListener('click', closeTaskModal);
        taskForm.addEventListener('submit', handleTaskSubmit);
        scheduleTypeSelect.addEventListener('change', toggleScheduleConfig);
        taskTypeSelect.addEventListener('change', toggleTaskTypeConfig);
        logsModalClose.addEventListener('click', function () { logsModal.classList.add('hidden'); });
        outputModalClose.addEventListener('click', function () { outputModal.classList.add('hidden'); });

        // 快捷间隔按钮
        document.querySelectorAll('.quick-interval').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.getElementById('task-interval').value = btn.dataset.interval;
            });
        });

        // 点击遮罩关闭模态框
        taskModal.addEventListener('click', function (e) {
            if (e.target === taskModal) closeTaskModal();
        });
        logsModal.addEventListener('click', function (e) {
            if (e.target === logsModal) logsModal.classList.add('hidden');
        });
        outputModal.addEventListener('click', function (e) {
            if (e.target === outputModal) outputModal.classList.add('hidden');
        });

        // ESC 关闭所有打开的模态框
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                if (!taskModal.classList.contains('hidden')) closeTaskModal();
                if (!logsModal.classList.contains('hidden')) logsModal.classList.add('hidden');
                if (!outputModal.classList.contains('hidden')) outputModal.classList.add('hidden');
            }
        });

        // 页面可见性变化：切回时立即刷新一次
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) {
                loadTasks();
                loadStatus();
            }
        });
    }

    // ------------------------------------------------------------------
    // 自动刷新：后台轮询任务状态（轻量接口）
    // ------------------------------------------------------------------

    function startAutoRefresh() {
        stopAutoRefresh();
        autoRefreshTimer = setInterval(function () {
            // 仅当没有打开的模态框时刷新，避免打断用户操作
            if (taskModal.classList.contains('hidden')
                && logsModal.classList.contains('hidden')
                && outputModal.classList.contains('hidden')) {
                loadStatus();
            }
        }, AUTO_REFRESH_INTERVAL);
    }

    function stopAutoRefresh() {
        if (autoRefreshTimer) {
            clearInterval(autoRefreshTimer);
            autoRefreshTimer = null;
        }
    }

    function loadStatus() {
        fetch('/admin/cmd/scheduled/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                statusCache = data.status || {};
                // 只更新状态徽章，不重渲染整个列表
                updateStatusBadges(data.recent || {});
            })
            .catch(function () { /* 静默失败 */ });
    }

    function updateStatusBadges(recentMap) {
        tasksCache.forEach(function (t) {
            var card = document.querySelector('[data-task-card="' + t.id + '"]');
            if (!card) return;
            var badge = card.querySelector('.last-status-badge');
            if (!badge) return;

            var st = statusCache[t.id];
            if (!st) {
                badge.innerHTML = '<span class="text-xs text-cream/30">未执行</span>';
                return;
            }

            var color = st.last_success ? 'green' : 'red';
            var text = st.last_success ? '成功' : '失败';
            var recent = (recentMap[t.id] || 0) > 0
                ? ' · <span class="text-blue-300">活动中</span>' : '';
            badge.innerHTML =
                '<span class="px-1.5 py-0.5 text-xs rounded-full bg-' + color +
                '-500/20 text-' + color + '-300 border border-' + color +
                '-400/20">' + text + '</span>' +
                '<span class="text-xs text-cream/40 ml-2">' +
                (st.last_started_at || '') + ' (' +
                (st.last_duration || 0).toFixed(1) + 's)</span>' + recent;
        });
    }

    // ------------------------------------------------------------------
    // 调度类型切换
    // ------------------------------------------------------------------

    function toggleScheduleConfig() {
        var type = scheduleTypeSelect.value;
        if (type === 'interval') {
            intervalConfig.classList.remove('hidden');
            timeConfig.classList.add('hidden');
        } else if (type === 'daily') {
            intervalConfig.classList.add('hidden');
            timeConfig.classList.remove('hidden');
            timeLabel.textContent = '每日执行时间';
            var input = document.getElementById('task-execute-at');
            input.type = 'time';
            input.value = '';
        } else if (type === 'once') {
            intervalConfig.classList.add('hidden');
            timeConfig.classList.remove('hidden');
            timeLabel.textContent = '执行时间';
            var input2 = document.getElementById('task-execute-at');
            input2.type = 'datetime-local';
            input2.value = '';
        }
    }

    // 根据任务类型切换「执行命令」区域的标签和占位符
    function toggleTaskTypeConfig() {
        var type = taskTypeSelect.value;
        if (type === 'script') {
            taskCommandLabel.textContent = '脚本代码（Python 语法）';
            taskCommandInput.placeholder = "如：print('Hello World')\nfor i in range(3):\n    print(i)";
        } else {
            taskCommandLabel.textContent = '执行命令';
            taskCommandInput.placeholder = "如：echo 'Hello World'";
        }
    }

    // ------------------------------------------------------------------
    // 任务列表
    // ------------------------------------------------------------------

    function loadTasks() {
        fetch('/admin/cmd/scheduled/tasks')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                renderTasks(data.tasks || []);
                // 任务列表加载完后立即拉取一次执行状态
                loadStatus();
            })
            .catch(function (err) {
                console.error('加载任务失败:', err);
            });
    }

    function renderTasks(tasks) {
        tasksCache = tasks;
        if (!tasks.length) {
            taskListContainer.innerHTML = '';
            emptyState.classList.remove('hidden');
            return;
        }
        emptyState.classList.add('hidden');

        taskListContainer.innerHTML = tasks.map(function (t) {
            return buildTaskCard(t);
        }).join('');

        // 绑定事件
        taskListContainer.querySelectorAll('[data-action]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var action = btn.dataset.action;
                var id = parseInt(btn.dataset.id);
                if (action === 'edit') openEditModal(id);
                else if (action === 'delete') deleteTask(id);
                else if (action === 'toggle') toggleTask(id);
                else if (action === 'trigger') triggerTask(id);
                else if (action === 'logs') window.ScheduledLogs.openLogsModal(id);
            });
        });

        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }

        // 渲染完成后用缓存的状态徽章更新一次
        if (Object.keys(statusCache).length) {
            updateStatusBadges({});
        }
    }

    function buildTaskCard(t) {
        var typeLabel = {
            'interval': '间隔执行',
            'daily': '每日定时',
            'once': '一次性',
        }[t.schedule_type] || t.schedule_type;

        var intervalDesc = '';
        if (t.schedule_type === 'interval') {
            intervalDesc = formatInterval(t.interval_seconds);
        } else if (t.schedule_type === 'daily') {
            intervalDesc = '每日 ' + (t.execute_at || '00:00');
        } else if (t.schedule_type === 'once') {
            intervalDesc = t.execute_at || '';
        }

        var statusBadge = t.is_enabled
            ? '<span class="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-300 border border-green-400/20">启用</span>'
            : '<span class="px-2 py-0.5 text-xs rounded-full bg-red-500/20 text-red-300 border border-red-400/20">禁用</span>';

        // 任务类型徽章：shell / script
        var taskTypeBadge = (t.task_type === 'script')
            ? '<span class="px-2 py-0.5 text-xs rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-400/20">脚本</span>'
            : '<span class="px-2 py-0.5 text-xs rounded-full bg-slate-500/20 text-slate-300 border border-slate-400/20">Shell</span>';

        var toggleIcon = t.is_enabled ? 'pause' : 'play';
        var toggleText = t.is_enabled ? '禁用' : '启用';

        return '<div data-task-card="' + t.id + '" class="bg-forest-800/60 border border-cream/10 rounded-xl p-5">' +
            '<div class="flex items-start justify-between gap-4">' +
                '<div class="flex-1 min-w-0">' +
                    '<div class="flex items-center gap-2 mb-2 flex-wrap">' +
                        '<h3 class="font-bold text-lg truncate">' + escapeHtml(t.name) + '</h3>' +
                        statusBadge +
                        taskTypeBadge +
                    '</div>' +
                    '<div class="text-sm text-cream/50 mb-2 font-mono truncate">' + escapeHtml(t.command) + '</div>' +
                    '<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-cream/40">' +
                        '<span><i data-lucide="repeat" class="w-3 h-3 inline -mt-0.5"></i> ' + typeLabel + '</span>' +
                        '<span><i data-lucide="clock" class="w-3 h-3 inline -mt-0.5"></i> ' + intervalDesc + '</span>' +
                        (t.last_run_at ? '<span>上次: ' + t.last_run_at + '</span>' : '') +
                        (t.next_run_at ? '<span>下次: ' + t.next_run_at + '</span>' : '') +
                        '<span>执行次数: ' + (t.run_count || 0) + '</span>' +
                    '</div>' +
                    '<div class="last-status-badge mt-2 text-xs text-cream/30">未执行</div>' +
                '</div>' +
                '<div class="flex flex-col gap-1 shrink-0">' +
                    '<button data-action="trigger" data-id="' + t.id + '" ' +
                        'class="px-3 py-1.5 text-xs bg-gold-400/20 text-gold-300 border border-gold-400/20 rounded-lg hover:bg-gold-400/30 transition-colors flex items-center gap-1">' +
                        '<i data-lucide="zap" class="w-3 h-3"></i> 立即执行' +
                    '</button>' +
                    '<button data-action="logs" data-id="' + t.id + '" ' +
                        'class="px-3 py-1.5 text-xs bg-purple-600/20 text-purple-300 border border-purple-400/20 rounded-lg hover:bg-purple-600/30 transition-colors flex items-center gap-1">' +
                        '<i data-lucide="scroll-text" class="w-3 h-3"></i> 日志' +
                    '</button>' +
                    '<div class="flex gap-1">' +
                        '<button data-action="edit" data-id="' + t.id + '" ' +
                            'class="flex-1 px-2 py-1.5 text-xs bg-forest-700/60 border border-cream/10 rounded-lg hover:bg-forest-600/60 transition-colors">编辑</button>' +
                        '<button data-action="toggle" data-id="' + t.id + '" ' +
                            'class="flex-1 px-2 py-1.5 text-xs bg-forest-700/60 border border-cream/10 rounded-lg hover:bg-forest-600/60 transition-colors">' + toggleText + '</button>' +
                        '<button data-action="delete" data-id="' + t.id + '" ' +
                            'class="px-2 py-1.5 text-xs bg-red-500/20 text-red-300 border border-red-400/20 rounded-lg hover:bg-red-500/30 transition-colors">删除</button>' +
                    '</div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }

    function formatInterval(seconds) {
        if (seconds >= 86400) {
            var d = Math.floor(seconds / 86400);
            return '每' + d + '天';
        }
        if (seconds >= 3600) {
            var h = Math.floor(seconds / 3600);
            return '每' + h + '小时';
        }
        if (seconds >= 60) {
            var m = Math.floor(seconds / 60);
            return '每' + m + '分钟';
        }
        return '每' + seconds + '秒';
    }

    // ------------------------------------------------------------------
    // 创建/编辑模态框
    // ------------------------------------------------------------------

    function openCreateModal() {
        taskModalTitle.textContent = '创建定时任务';
        document.getElementById('task-id').value = '';
        document.getElementById('task-name').value = '';
        document.getElementById('task-command').value = '';
        document.getElementById('task-schedule-type').value = 'interval';
        document.getElementById('task-type').value = 'shell';
        document.getElementById('task-interval').value = 3600;
        document.getElementById('task-execute-at').value = '';
        toggleScheduleConfig();
        toggleTaskTypeConfig();
        taskModal.classList.remove('hidden');
    }

    function openEditModal(id) {
        fetch('/admin/cmd/scheduled/tasks')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var task = (data.tasks || []).find(function (t) { return t.id === id; });
                if (!task) return;

                taskModalTitle.textContent = '编辑定时任务';
                document.getElementById('task-id').value = task.id;
                document.getElementById('task-name').value = task.name;
                document.getElementById('task-command').value = task.command;
                document.getElementById('task-schedule-type').value = task.schedule_type;
                document.getElementById('task-type').value = task.task_type || 'shell';
                document.getElementById('task-interval').value = task.interval_seconds || 3600;

                var executeAtInput = document.getElementById('task-execute-at');
                if (task.schedule_type === 'daily' && task.execute_at) {
                    executeAtInput.type = 'time';
                    executeAtInput.value = task.execute_at;
                } else if (task.schedule_type === 'once' && task.execute_at) {
                    executeAtInput.type = 'datetime-local';
                    // 转换格式: "2024-01-01 12:00:00" -> "2024-01-01T12:00"
                    var dt = task.execute_at.replace(' ', 'T').substring(0, 16);
                    executeAtInput.value = dt;
                }

                toggleScheduleConfig();
                toggleTaskTypeConfig();
                taskModal.classList.remove('hidden');
            });
    }

    function closeTaskModal() {
        taskModal.classList.add('hidden');
    }

    function handleTaskSubmit(e) {
        e.preventDefault();

        var id = document.getElementById('task-id').value;
        var name = document.getElementById('task-name').value.trim();
        var command = document.getElementById('task-command').value.trim();
        var scheduleType = document.getElementById('task-schedule-type').value;
        var taskType = document.getElementById('task-type').value;
        var intervalSeconds = parseInt(document.getElementById('task-interval').value) || 3600;
        var executeAt = document.getElementById('task-execute-at').value;

        // 转换执行时间格式
        if (scheduleType === 'daily' && executeAt) {
            // time input -> "HH:MM"
            executeAt = executeAt;
        } else if (scheduleType === 'once' && executeAt) {
            // datetime-local -> "YYYY-MM-DD HH:MM:SS"
            executeAt = executeAt.replace('T', ' ') + ':00';
        }

        var payload = {
            name: name,
            command: command,
            schedule_type: scheduleType,
            task_type: taskType,
            interval_seconds: intervalSeconds,
            execute_at: executeAt,
        };

        var method = id ? 'PUT' : 'POST';
        var url = id
            ? '/admin/cmd/scheduled/tasks/' + id
            : '/admin/cmd/scheduled/tasks';

        fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    closeTaskModal();
                    loadTasks();
                } else {
                    alert(data.message || '操作失败');
                }
            })
            .catch(function (err) {
                alert('请求失败: ' + err);
            });
    }

    // ------------------------------------------------------------------
    // 任务操作
    // ------------------------------------------------------------------

    function deleteTask(id) {
        if (!confirm('确定删除此定时任务？')) return;
        fetch('/admin/cmd/scheduled/tasks/' + id + '/delete', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) loadTasks();
                else alert(data.message || '删除失败');
            });
    }

    function toggleTask(id) {
        fetch('/admin/cmd/scheduled/tasks/' + id + '/toggle', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) loadTasks();
                else alert(data.message || '操作失败');
            });
    }

    function triggerTask(id) {
        fetch('/admin/cmd/scheduled/tasks/' + id + '/trigger', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    // 显示「活动中」状态并轮询刷新
                    showTaskRunning(id);
                    // 立即拉一次状态，2 秒后再拉一次（命令通常很快完成）
                    setTimeout(loadStatus, 500);
                    setTimeout(loadStatus, 2000);
                    setTimeout(loadStatus, 5000);
                } else {
                    alert(data.message || '触发失败');
                }
            });
    }

    function showTaskRunning(taskId) {
        var card = document.querySelector('[data-task-card="' + taskId + '"]');
        if (!card) return;
        var badge = card.querySelector('.last-status-badge');
        if (!badge) return;
        badge.innerHTML =
            '<span class="px-1.5 py-0.5 text-xs rounded-full bg-blue-500/20 text-blue-300 border border-blue-400/20">执行中…</span>';
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;');
    }

    return {
        escapeHtml: escapeHtml,
    };
})();
