/**
 * 快捷命令管理模块
 *
 * 功能：
 *   - 增删改查一键命令（Shell 命令，存储在数据库）
 *   - 脚本列表展示和运行（从文件系统读取）
 *   - 运行普通 CMD 命令（前端通过 SSE 流式执行）
 *   - 运行 Python 脚本（通过后端 SSE API /admin/cmd/run-script 执行）
 *
 * 类型判断：
 *   - Shell 命令：存储在 cmd_commands 表中，描述不以 [脚本] 开头
 *   - 脚本：存储在文件系统 scripts/ 目录下
 */

window.CmdPresets = (function () {
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

        if (addBtn) {
            addBtn.addEventListener('click', () => openModal(null));
        }
        if (cancelBtn) {
            cancelBtn.addEventListener('click', closeModal);
        }
        if (modal) {
            modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
        }
        if (form) {
            form.addEventListener('submit', handleSubmit);
        }

        load();
    }

    function load() {
        // 并行加载：Shell 命令 + 脚本列表
        Promise.all([
            fetch('/admin/cmd/commands').then(r => r.json()),
            fetch('/admin/cmd/scripts').then(r => r.json()).catch(() => ({ scripts: [] }))
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
            <div class="pixel-card rounded-xl p-4" data-script-filename="${escapeHtml(s.filename)}">
                <div class="flex items-start justify-between gap-2 mb-2">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <h3 class="font-bold text-cream truncate">${escapeHtml(s.name)}</h3>
                            <span class="text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded">脚本</span>
                        </div>
                        ${s.description ? `<p class="text-cream/50 text-xs truncate">${escapeHtml(s.description)}</p>` : ''}
                        <p class="text-cream/30 text-[10px] mt-1">${escapeHtml(s.filename)} · ${formatSize(s.size)}</p>
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
                const filename = btn.closest('[data-script-filename]').dataset.scriptFilename;
                if (filename) {
                    window.location.href = '/admin/cmd/editor?file=' + encodeURIComponent(filename);
                }
            });
        });

        // 绑定删除按钮
        scriptListContainer.querySelectorAll('.script-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const filename = btn.closest('[data-script-filename]').dataset.scriptFilename;
                if (!confirm('确定删除脚本 "' + filename + '"？')) return;
                fetch('/admin/cmd/scripts/' + encodeURIComponent(filename), { method: 'DELETE' })
                    .then(r => r.json())
                    .then(r => { if (r.success) load(); else alert(r.message); })
                    .catch(err => alert('网络错误: ' + err.message));
            });
        });

        // 绑定运行按钮
        scriptListContainer.querySelectorAll('.script-run-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const filename = btn.closest('[data-script-filename]').dataset.scriptFilename;
                const script = scripts.find(s => s.filename === filename);
                if (!script) return;

                // 先获取脚本内容再运行
                fetch('/admin/cmd/scripts/' + encodeURIComponent(filename))
                    .then(r => r.json())
                    .then(data => {
                        if (data.script && onRunScript) {
                            onRunScript({
                                name: data.script.name,
                                command: data.script.content,
                                description: data.script.description,
                                isFileScript: true,
                            });
                        }
                    })
                    .catch(err => alert('加载脚本失败: ' + err.message));
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
            <div class="pixel-card rounded-xl p-4" data-cmd-id="${cmd.id}">
                <div class="flex items-start justify-between gap-2 mb-2">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <h3 class="font-bold text-cream truncate">${escapeHtml(cmd.name)}</h3>
                            <span class="text-[10px] bg-forest-600/50 text-cream/70 px-1.5 py-0.5 rounded">CMD</span>
                        </div>
                        ${cmd.description ? `<p class="text-cream/50 text-xs truncate">${escapeHtml(cmd.description)}</p>` : ''}
                    </div>
                    <div class="flex gap-1 flex-shrink-0">
                        <button class="cmd-edit-btn p-1.5 text-cream/50 hover:text-gold-400 transition-colors" title="编辑">
                            <i data-lucide="edit-2" class="w-4 h-4"></i>
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
