/**
 * 快捷命令管理模块
 *
 * 功能：
 *   - 增删改查一键命令（Shell 命令，存储在数据库）
 *   - 运行快捷命令（前端通过弹窗终端执行）
 *
 * 类型：
 *   - Shell 命令：存储在 cmd_commands 表中
 */

window.ScriptPresets = (function () {
    let listContainer = null;
    let addBtn = null;
    let modal = null;
    let modalTitle = null;
    let form = null;
    let formId = null;
    let formName = null;
    let formCmd = null;
    let formDesc = null;
    let formSort = null;
    let cancelBtn = null;

    let commands = [];   // Shell 快捷命令（来自数据库）
    let onRunCommand = null;

    function init(options) {
        listContainer = document.getElementById('preset-list');
        addBtn = document.getElementById('add-script-btn');
        modal = document.getElementById('script-modal');
        modalTitle = document.getElementById('script-modal-title');
        form = document.getElementById('script-form');
        formId = document.getElementById('script-form-id');
        formName = document.getElementById('script-form-name');
        formCmd = document.getElementById('script-form-command');
        formDesc = document.getElementById('script-form-desc');
        formSort = document.getElementById('script-form-sort');
        cancelBtn = document.getElementById('script-modal-cancel');

        onRunCommand = options && options.onRunCommand;

        if (addBtn) {
            addBtn.addEventListener('click', () => openModal(null));
        }
        if (cancelBtn) {
            cancelBtn.addEventListener('click', closeModal);
        }
        if (form) {
            form.addEventListener('submit', handleSubmit);
        }

        load();
    }

    function load() {
        fetch('/admin/script/commands').then(r => r.json()).then(cmdData => {
            commands = cmdData.commands || [];
            renderCommands();
        }).catch(err => console.error('加载失败:', err));
    }

    function renderCommands() {
        if (!listContainer) return;

        if (!commands || commands.length === 0) {
            listContainer.innerHTML = `
                <div class="col-span-full pixel-card rounded-xl p-8 text-center">
                    <i data-lucide="zap-off" class="w-10 h-10 text-cream/30 mx-auto mb-3"></i>
                    <p class="text-cream/50 text-sm">暂无快捷命令，点击右上角添加</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        listContainer.innerHTML = commands.map(cmd => {
            return `
            <div class="pixel-card rounded-xl p-4" data-script-id="${cmd.id}">
                <div class="flex items-start justify-between gap-2 mb-2">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <h3 class="font-bold text-cream truncate">${escapeHtml(cmd.name)}</h3>
                            <span class="text-[10px] bg-forest-600/50 text-cream/70 px-1.5 py-0.5 rounded">Shell</span>
                        </div>
                        ${cmd.description ? `<p class="text-cream/50 text-xs truncate">${escapeHtml(cmd.description)}</p>` : ''}
                    </div>
                    <div class="flex gap-1 flex-shrink-0">
                        <button class="script-edit-btn p-1.5 text-cream/50 hover:text-gold-400 transition-colors" title="编辑">
                            <i data-lucide="edit-2" class="w-4 h-4"></i>
                        </button>
                        <button class="script-delete-btn p-1.5 text-cream/50 hover:text-red-400 transition-colors" title="删除">
                            <i data-lucide="trash" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>
                <div class="bg-black/30 rounded px-3 py-2 mb-3 font-mono text-xs text-cream/70 overflow-x-auto whitespace-pre-wrap max-h-20">
${escapeHtml(cmd.command)}
                </div>
                <button class="script-run-preset-btn w-full py-2 bg-forest-700/50 border border-cream/10 text-cream rounded-lg hover:bg-forest-600/50 transition-colors text-sm font-medium flex items-center justify-center gap-2">
                    <i data-lucide="play" class="w-4 h-4 text-gold-400"></i>
                    运行
                </button>
            </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();

        listContainer.querySelectorAll('.script-edit-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.closest('[data-script-id]').dataset.scriptId);
                const cmd = commands.find(c => c.id === id);
                if (cmd) openModal(cmd);
            });
        });

        listContainer.querySelectorAll('.script-delete-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = parseInt(btn.closest('[data-script-id]').dataset.scriptId);
                const cmd = commands.find(c => c.id === id);
                if (!cmd) return;
                const ok = await window.ScriptModal.confirm('删除快捷命令', '确定删除 "' + cmd.name + '"？');
                if (!ok) return;
                try {
                    const r = await fetch('/admin/script/commands/' + id + '/delete', { method: 'POST' });
                    const data = await r.json();
                    if (data.success) {
                        load();
                    } else {
                        window.ScriptModal.alert('删除失败', data.message || '未知错误');
                    }
                } catch (err) {
                    window.ScriptModal.alert('网络错误', err.message);
                }
            });
        });

        listContainer.querySelectorAll('.script-run-preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.closest('[data-script-id]').dataset.scriptId);
                const cmd = commands.find(c => c.id === id);
                if (!cmd) return;
                if (onRunCommand) onRunCommand(cmd);
            });
        });
    }

    function openModal(cmd) {
        formId.value = cmd ? cmd.id : '';
        formName.value = cmd ? cmd.name : '';
        formCmd.value = cmd ? cmd.command : '';
        formDesc.value = cmd ? (cmd.description || '') : '';
        formSort.value = cmd ? (cmd.sort_order || 0) : 0;

        modalTitle.textContent = cmd ? '编辑快捷命令' : '添加快捷命令';
        modal.classList.remove('hidden');
        formName.focus();
    }

    function closeModal() {
        modal.classList.add('hidden');
    }

    async function handleSubmit(e) {
        e.preventDefault();
        const id = formId.value;

        const data = {
            name: formName.value.trim(),
            command: formCmd.value.trim(),
            description: (formDesc.value || '').trim(),
            sort_order: parseInt(formSort.value) || 0
        };

        const url = id ? '/admin/script/commands/' + id : '/admin/script/commands';
        const method = id ? 'PUT' : 'POST';

        try {
            const r = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await r.json();
            if (result.success) {
                closeModal();
                load();
            } else {
                window.ScriptModal.alert('保存失败', result.message || '未知错误');
            }
        } catch (err) {
            window.ScriptModal.alert('网络错误', err.message);
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return {
        init: init,
        load: load,
        getAll: () => commands,
    };
})();