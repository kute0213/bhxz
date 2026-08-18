/**
 * 快捷命令管理模块
 *
 * 功能：
 *   - 增删改查一键命令（Shell 命令，存储在数据库）
 *   - 脚本列表展示和运行（从文件系统读取）
 *   - 运行普通脚本命令（前端通过 SSE 流式执行）
 *   - 运行 Python 脚本（通过后端 SSE API /admin/script/run-script 执行）
 *
 * 类型判断：
 *   - Shell 命令：存储在 cmd_commands 表中，描述不以 [脚本] 开头
 *   - 脚本：存储在文件系统 scripts/ 目录下
 */

window.ScriptPresets = (function () {
    let listContainer = null;
    let scriptListContainer = null;
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

    let commands = [];   // Shell 快捷命令（来自数据库）
    let scripts = [];    // 脚本（来自文件系统）
    let onRunCommand = null;
    let onRunScript = null;

    function init(options) {
        listContainer = document.getElementById('preset-list');
        scriptListContainer = document.getElementById('script-list');
        addBtn = document.getElementById('add-script-btn');
        modal = document.getElementById('script-modal');
        modalTitle = document.getElementById('script-modal-title');
        form = document.getElementById('script-form');
        formId = document.getElementById('script-form-id');
        formName = document.getElementById('script-form-name');
        formCmd = document.getElementById('script-form-command');
        formDesc = document.getElementById('script-form-desc');
        formSort = document.getElementById('script-form-sort');
        formType = document.getElementById('script-form-type');
        cancelBtn = document.getElementById('script-modal-cancel');

        onRunCommand = options && options.onRunCommand;
        onRunScript = options && options.onRunScript;

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
        // 并行加载：Shell 命令 + 脚本列表
        Promise.all([
            fetch('/admin/script/commands').then(r => r.json()),
            fetch('/admin/script/scripts').then(r => r.json()).catch(() => ({ scripts: [] }))
        ]).then(([cmdData, scriptData]) => {
            // 筛选出 Shell 命令（排除脚本类型）
            const allCommands = cmdData.commands || [];
            commands = allCommands.filter(c => !(c.description && c.description.indexOf('[脚本]') === 0));

            scripts = scriptData.scripts || [];

            renderCommands();
            renderScripts();
        }).catch(err => console.error('加载失败:', err));
    }

    function renderScripts() {
        if (!scriptListContainer) return;

        if (!scripts || scripts.length === 0) {
            scriptListContainer.innerHTML = `
                <div class="col-span-full pixel-card rounded-xl p-8 text-center">
                    <i data-lucide="file-x" class="w-10 h-10 text-cream/30 mx-auto mb-3"></i>
                    <p class="text-cream/50 text-sm">暂无脚本，点击上方「脚本编辑器」创建</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        scriptListContainer.innerHTML = scripts.map(s => {
            return `
            <div class="pixel-card rounded-xl p-4" data-script-id="${s.id}">
                <div class="flex items-start justify-between gap-2 mb-2">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <h3 class="font-bold text-cream truncate">${escapeHtml(s.name)}</h3>
                            <span class="text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded">脚本</span>
                        </div>
                        ${s.description ? `<p class="text-cream/50 text-xs truncate">${escapeHtml(s.description)}</p>` : ''}
                        <p class="text-cream/30 text-[10px] mt-1">${s.script_type === 'shell' ? 'Shell 命令' : 'MiniScript 脚本'}</p>
                    </div>
                    <div class="flex gap-1 flex-shrink-0">
                        <button class="script-editor-btn p-1.5 text-cream/50 hover:text-purple-300 transition-colors" title="在编辑器中打开">
                            <i data-lucide="edit-3" class="w-4 h-4"></i>
                        </button>
                        <button class="script-delete-btn p-1.5 text-cream/50 hover:text-red-400 transition-colors" title="删除">
                            <i data-lucide="trash" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>
                <button class="script-run-btn w-full py-2 bg-purple-600/30 border border-purple-400/20 text-purple-200 rounded-lg hover:bg-purple-600/40 transition-colors text-sm font-medium flex items-center justify-center gap-2">
                    <i data-lucide="play" class="w-4 h-4 text-purple-300"></i>
                    运行脚本
                </button>
            </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();

        // 绑定编辑按钮
        scriptListContainer.querySelectorAll('.script-editor-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = btn.closest('[data-script-id]').dataset.scriptId;
                if (id) {
                    window.location.href = '/admin/script/editor?id=' + encodeURIComponent(id);
                }
            });
        });

        // 绑定删除按钮
        scriptListContainer.querySelectorAll('.script-delete-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = btn.closest('[data-script-id]').dataset.scriptId;
                const script = scripts.find(s => String(s.id) === String(id));
                if (!script) return;
                const ok = await window.ScriptModal.confirm('删除脚本', '确定删除脚本 "' + script.name + '"？');
                if (!ok) return;
                try {
                    const r = await fetch('/admin/script/scripts/' + id, { method: 'DELETE' });
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

        // 绑定运行按钮
        scriptListContainer.querySelectorAll('.script-run-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = btn.closest('[data-script-id]').dataset.scriptId;
                const script = scripts.find(s => String(s.id) === String(id));
                if (!script) return;

                try {
                    const r = await fetch('/admin/script/scripts/' + id);
                    const data = await r.json();
                    if (data.script && onRunScript) {
                        onRunScript({
                            id: data.script.id,
                            name: data.script.name,
                            command: data.script.content,
                            description: data.script.description,
                            isFileScript: true,
                        });
                    }
                } catch (err) {
                    window.ScriptModal.alert('加载失败', '加载脚本失败: ' + err.message);
                }
            });
        });
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

        const isScript = cmd && cmd.description && cmd.description.indexOf('[脚本]') === 0;
        formType.value = isScript ? 'script' : 'cmd';

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

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    return {
        init: init,
        load: load,
        getAll: () => commands,
    };
})();
