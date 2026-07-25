/**
 * 快捷命令管理模块
 *
 * 功能：
 *   - 增删改查一键命令
 *   - 运行普通 CMD 命令
 *   - 运行 MiniScript 脚本
 */

window.CmdPresets = (function () {
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
    let formType = null;
    let cancelBtn = null;

    let commands = [];
    let onRunCommand = null;
    let onRunScript = null;

    function init(options) {
        listContainer = document.getElementById('preset-list');
        addBtn = document.getElementById('add-cmd-btn');
        modal = document.getElementById('cmd-modal');
        modalTitle = document.getElementById('cmd-modal-title');
        form = document.getElementById('cmd-form');
        formId = document.getElementById('cmd-form-id');
        formName = document.getElementById('cmd-form-name');
        formCmd = document.getElementById('cmd-form-command');
        formDesc = document.getElementById('cmd-form-desc');
        formSort = document.getElementById('cmd-form-sort');
        formType = document.getElementById('cmd-form-type');
        cancelBtn = document.getElementById('cmd-modal-cancel');

        onRunCommand = options && options.onRunCommand;
        onRunScript = options && options.onRunScript;

        addBtn.addEventListener('click', () => openModal(null));
        cancelBtn.addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

        form.addEventListener('submit', handleSubmit);

        load();
    }

    function load() {
        fetch('/admin/cmd/commands')
            .then(r => r.json())
            .then(data => {
                commands = data.commands || [];
                render();
            })
            .catch(err => console.error('加载命令失败:', err));
    }

    function render() {
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
            const isScript = cmd.description && cmd.description.indexOf('[脚本]') === 0;
            const typeBadge = isScript
                ? '<span class="text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded">脚本</span>'
                : '<span class="text-[10px] bg-forest-600/50 text-cream/70 px-1.5 py-0.5 rounded">CMD</span>';

            return `
            <div class="pixel-card rounded-xl p-4" data-cmd-id="${cmd.id}">
                <div class="flex items-start justify-between gap-2 mb-2">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <h3 class="font-bold text-cream truncate">${escapeHtml(cmd.name)}</h3>
                            ${typeBadge}
                        </div>
                        ${cmd.description ? `<p class="text-cream/50 text-xs truncate">${escapeHtml(cmd.description)}</p>` : ''}
                    </div>
                    <div class="flex gap-1 flex-shrink-0">
                        <button class="cmd-edit-btn p-1.5 text-cream/50 hover:text-gold-400 transition-colors" title="编辑">
                            <i data-lucide="edit-2" class="w-4 h-4"></i>
                        </button>
                        <button class="cmd-editor-btn p-1.5 text-cream/50 hover:text-purple-300 transition-colors" title="在脚本编辑器中打开">
                            <i data-lucide="code-2" class="w-4 h-4"></i>
                        </button>
                        <button class="cmd-delete-btn p-1.5 text-cream/50 hover:text-red-400 transition-colors" title="删除">
                            <i data-lucide="trash" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>
                <div class="bg-black/30 rounded px-3 py-2 mb-3 font-mono text-xs text-cream/70 overflow-x-auto whitespace-pre-wrap max-h-20">
${escapeHtml(cmd.command)}
                </div>
                <button class="cmd-run-preset-btn w-full py-2 bg-forest-700/50 border border-cream/10 text-cream rounded-lg hover:bg-forest-600/50 transition-colors text-sm font-medium flex items-center justify-center gap-2">
                    <i data-lucide="play" class="w-4 h-4 text-gold-400"></i>
                    运行
                </button>
            </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();

        listContainer.querySelectorAll('.cmd-edit-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.closest('[data-cmd-id]').dataset.cmdId);
                const cmd = commands.find(c => c.id === id);
                if (cmd) openModal(cmd);
            });
        });

        listContainer.querySelectorAll('.cmd-editor-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.closest('[data-cmd-id]').dataset.cmdId);
                if (id) {
                    window.location.href = '/admin/cmd/editor?edit=' + id;
                }
            });
        });

        listContainer.querySelectorAll('.cmd-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.closest('[data-cmd-id]').dataset.cmdId);
                if (!confirm('确定删除这个快捷命令？')) return;
                fetch('/admin/cmd/commands/' + id + '/delete', { method: 'POST' })
                    .then(r => r.json())
                    .then(r => { if (r.success) load(); else alert(r.message); })
                    .catch(err => alert('网络错误: ' + err.message));
            });
        });

        listContainer.querySelectorAll('.cmd-run-preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.closest('[data-cmd-id]').dataset.cmdId);
                const cmd = commands.find(c => c.id === id);
                if (!cmd) return;

                const isScript = cmd.description && cmd.description.indexOf('[脚本]') === 0;
                if (isScript) {
                    if (onRunScript) onRunScript(cmd);
                } else {
                    if (onRunCommand) onRunCommand(cmd);
                }
            });
        });
    }

    function openModal(cmd) {
        formId.value = cmd ? cmd.id : '';
        formName.value = cmd ? cmd.name : '';
        formCmd.value = cmd ? cmd.command : '';
        formDesc.value = cmd ? (cmd.description || '') : '';
        formSort.value = cmd ? (cmd.sort_order || 0) : 0;

        const isScript = cmd && cmd.description && cmd.description.indexOf('[脚本]') === 0;
        formType.value = isScript ? 'script' : 'cmd';

        modalTitle.textContent = cmd ? '编辑快捷命令' : '添加快捷命令';
        modal.classList.remove('hidden');
        formName.focus();
    }

    function closeModal() {
        modal.classList.add('hidden');
    }

    function handleSubmit(e) {
        e.preventDefault();
        const id = formId.value;
        const type = formType.value;
        let desc = formDesc.value.trim();

        if (type === 'script' && desc.indexOf('[脚本]') !== 0) {
            desc = '[脚本] ' + desc;
        } else if (type === 'cmd' && desc.indexOf('[脚本]') === 0) {
            desc = desc.replace(/^\[脚本\]\s*/, '');
        }

        const data = {
            name: formName.value.trim(),
            command: formCmd.value.trim(),
            description: desc,
            sort_order: parseInt(formSort.value) || 0
        };

        const url = id ? '/admin/cmd/commands/' + id : '/admin/cmd/commands';
        const method = id ? 'PUT' : 'POST';

        fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(r => r.json()).then(result => {
            if (result.success) {
                closeModal();
                load();
            } else {
                alert(result.message || '保存失败');
            }
        }).catch(err => {
            alert('网络错误: ' + err.message);
        });
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
