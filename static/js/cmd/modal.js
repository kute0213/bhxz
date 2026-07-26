/**
 * CMD 页内弹窗系统
 *
 * 替代原生 alert / prompt / confirm，使用符合页面磨砂风格的模态框。
 * 返回 Promise，支持 async/await 链式调用。
 *
 * 用法：
 *   CmdModal.alert('标题', '消息')           => Promise<void>
 *   CmdModal.confirm('标题', '消息')         => Promise<bool>
 *   CmdModal.prompt('标题', '消息', '默认值') => Promise<string>
 */

window.CmdModal = (function () {

    // --------------------------------------------------------
    // DOM 构建：单例模态框
    // --------------------------------------------------------
    let root = null;
    let backdrop = null;
    let container = null;
    let titleEl = null;
    let bodyEl = null;
    let iconEl = null;
    let inputWrap = null;
    let inputEl = null;
    let actionsEl = null;

    let pending = null; // { resolve, type }
    let closeTimer = null; // close() 的超时 fallback 定时器
    let animEndHandler = null; // 当前 animationend 监听器引用（修复连续弹窗闪退）

    function build() {
        if (root) return;

        root = document.createElement('div');
        root.id = 'cmd-modal-root';
        root.style.cssText = 'position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;';
        root.classList.add('cmd-modal-root');
        // hidden 类由 Tailwind 提供，但内联样式优先级更高，所以用 style.display 控制显隐

        backdrop = document.createElement('div');
        backdrop.style.cssText = 'position:absolute;inset:0;background:rgba(0,0,0,0.7);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);';

        container = document.createElement('div');
        container.className = 'pixel-card rounded-2xl p-0 w-[92vw] max-w-md overflow-hidden';
        container.style.cssText = 'position:relative;';

        // 顶部渐变条
        const topBar = document.createElement('div');
        topBar.style.cssText = 'position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#f4d03f,#d4a827);border-radius:16px 16px 0 0;z-index:1;';
        container.appendChild(topBar);

        // 头部
        const header = document.createElement('div');
        header.className = 'flex items-center gap-3 px-6 pt-6 pb-3';
        iconEl = document.createElement('div');
        iconEl.style.cssText = 'width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0;';
        const iconSvg = document.createElement('i');
        iconSvg.setAttribute('data-lucide', 'info');
        iconSvg.className = 'w-5 h-5';
        iconEl.appendChild(iconSvg);
        const headerText = document.createElement('div');
        headerText.style.cssText = 'flex:1;min-width:0;';
        titleEl = document.createElement('h3');
        titleEl.className = 'text-lg font-bold text-cream leading-tight';
        headerText.appendChild(titleEl);
        header.appendChild(iconEl);

        // 正文
        const bodyWrap = document.createElement('div');
        bodyWrap.className = 'px-6 pb-4';
        bodyEl = document.createElement('p');
        bodyEl.className = 'text-cream/70 text-sm leading-relaxed whitespace-pre-wrap';
        bodyWrap.appendChild(bodyEl);

        // 输入框（prompt 用，默认隐藏）
        inputWrap = document.createElement('div');
        inputWrap.className = 'px-6 pb-4';
        inputWrap.style.display = 'none';
        inputEl = document.createElement('input');
        inputEl.type = 'text';
        inputEl.className = 'w-full bg-black/30 border border-cream/10 rounded-lg px-4 py-2.5 text-cream placeholder-cream/30 focus:outline-none focus:border-gold-400/50';
        inputWrap.appendChild(inputEl);

        // 操作按钮区
        actionsEl = document.createElement('div');
        actionsEl.className = 'px-6 pb-6 pt-2 flex gap-3 justify-end';

        container.appendChild(header);
        container.appendChild(bodyWrap);
        container.appendChild(inputWrap);
        container.appendChild(actionsEl);

        root.appendChild(backdrop);
        root.appendChild(container);
        document.body.appendChild(root);

        // ESC 关闭
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && pending && pending.type === 'confirm') {
                close();
                pending.resolve(false);
            }
        });

        // 点击背景关闭（仅 confirm 模式）
        backdrop.addEventListener('click', function () {
            if (pending && pending.type === 'confirm') {
                close();
                pending.resolve(false);
            }
        });
    }

    // --------------------------------------------------------
    // 显示 / 隐藏
    // --------------------------------------------------------
    function show() {
        build();
        // 清除上次 close() 的超时 fallback，防止新弹窗被旧定时器隐藏
        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }
        // 移除上次 close() 残留的 animationend 监听器，防止新弹窗 enter 动画结束时被旧监听器隐藏
        if (animEndHandler && container) {
            container.removeEventListener('animationend', animEndHandler);
            animEndHandler = null;
        }
        root.style.display = 'flex';
        // 重启动画
        container.classList.remove('cmd-modal-leave');
        container.classList.remove('cmd-modal-enter');
        void container.offsetWidth;
        container.classList.add('cmd-modal-enter');

        // 重新渲染 lucide 图标
        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }
    }

    function close() {
        if (!root) return;
        // 清除已有的定时器，避免重复
        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }
        // 移除旧的监听器，防止重复绑定
        if (animEndHandler) {
            container.removeEventListener('animationend', animEndHandler);
            animEndHandler = null;
        }
        container.classList.remove('cmd-modal-enter');
        container.classList.add('cmd-modal-leave');

        let done = false;
        const finish = function () {
            if (done) return;
            done = true;
            container.classList.remove('cmd-modal-leave');
            root.style.display = 'none';
            // 清理监听器引用
            if (animEndHandler) {
                container.removeEventListener('animationend', animEndHandler);
                animEndHandler = null;
            }
        };

        animEndHandler = function () { finish(); };
        container.addEventListener('animationend', animEndHandler);

        // 超时 fallback：300ms 后强制关闭，防止动画未定义导致弹窗无法关闭
        closeTimer = setTimeout(function () {
            closeTimer = null;
            finish();
        }, 300);
    }

    // --------------------------------------------------------
    // 图标 & 按钮辅助
    // --------------------------------------------------------
    function setIcon(name, color) {
        if (!iconEl) return;
        iconEl.innerHTML = '';
        const svg = document.createElement('i');
        svg.setAttribute('data-lucide', name);
        svg.className = 'w-5 h-5';
        if (color) svg.style.color = color;
        iconEl.appendChild(svg);

        // 背景色映射
        const bgMap = {
            info: 'rgba(244,208,63,0.15)',
            success: 'rgba(74,222,128,0.15)',
            warning: 'rgba(251,191,36,0.15)',
            error: 'rgba(248,113,113,0.15)',
            question: 'rgba(96,165,250,0.15)',
            terminal: 'rgba(168,85,247,0.15)',
        };
        iconEl.style.background = bgMap[name] || 'rgba(244,208,63,0.15)';
        iconEl.style.color = color || '#f4d03f';

        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }
    }

    function makeBtn(text, variant, onClick) {
        const btn = document.createElement('button');
        btn.className = 'px-5 py-2 rounded-lg font-bold text-sm transition-all duration-150 active:scale-95';
        if (variant === 'primary') {
            btn.classList.add('bg-gold-400', 'text-forest-900', 'hover:bg-gold-500');
        } else if (variant === 'danger') {
            btn.classList.add('bg-red-500', 'text-white', 'hover:bg-red-600');
        } else if (variant === 'ghost') {
            btn.classList.add('bg-cream/10', 'text-cream/80', 'hover:bg-cream/20');
        } else {
            btn.classList.add('bg-cream/10', 'text-cream/80', 'hover:bg-cream/20');
        }
        btn.textContent = text;
        btn.addEventListener('click', onClick);
        return btn;
    }

    // --------------------------------------------------------
    // Public API
    // --------------------------------------------------------

    /**
     * 消息提示（类似原生 alert）
     * @returns {Promise<void>}
     */
    function alert(title, message, icon) {
        return new Promise(function (resolve) {
            build();
            pending = { resolve: resolve, type: 'alert' };
            titleEl.textContent = title || '提示';
            bodyEl.textContent = message || '';
            inputWrap.style.display = 'none';

            const iconName = icon || 'info';
            setIcon(iconName);

            actionsEl.innerHTML = '';
            actionsEl.appendChild(makeBtn('确定', 'primary', function () {
                close();
                pending = null;
                resolve();
            }));

            show();
        });
    }

    /**
     * 确认对话框（类似原生 confirm）
     * @returns {Promise<boolean>} true=确认, false=取消
     */
    function confirm(title, message) {
        return new Promise(function (resolve) {
            build();
            pending = { resolve: resolve, type: 'confirm' };
            titleEl.textContent = title || '确认';
            bodyEl.textContent = message || '';
            inputWrap.style.display = 'none';
            setIcon('question');

            actionsEl.innerHTML = '';
            actionsEl.appendChild(makeBtn('取消', 'ghost', function () {
                close();
                pending = null;
                resolve(false);
            }));
            actionsEl.appendChild(makeBtn('确定', 'primary', function () {
                close();
                pending = null;
                resolve(true);
            }));

            show();
        });
    }

    /**
     * 输入对话框（类似原生 prompt）
     * @returns {Promise<string>} 用户输入的字符串，取消返回空字符串
     */
    function prompt(title, message, defaultValue) {
        return new Promise(function (resolve) {
            build();
            pending = { resolve: resolve, type: 'prompt' };
            titleEl.textContent = title || '输入';
            bodyEl.textContent = message || '';
            inputWrap.style.display = '';
            inputEl.value = defaultValue || '';
            setIcon('question');

            actionsEl.innerHTML = '';
            actionsEl.appendChild(makeBtn('取消', 'ghost', function () {
                close();
                pending = null;
                resolve('');
            }));
            const okBtn = makeBtn('确定', 'primary', function () {
                close();
                pending = null;
                resolve(inputEl.value);
            });
            actionsEl.appendChild(okBtn);

            show();
            setTimeout(function () { inputEl.focus(); inputEl.select(); }, 100);

            // Enter 提交
            inputEl.addEventListener('keydown', function onKey(e) {
                if (e.key === 'Enter') {
                    inputEl.removeEventListener('keydown', onKey);
                    close();
                    pending = null;
                    resolve(inputEl.value);
                }
            });
        });
    }

    return {
        alert: alert,
        confirm: confirm,
        prompt: prompt,
        close: close,
    };
})();
