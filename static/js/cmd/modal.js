/**
 * CMD 页内弹窗系统
 *
 * 替代原生 alert / prompt / confirm，使用符合页面磨砂风格的模态框。
 * 返回 Promise，支持 async/await 链式调用。
 *
 * 设计原则（可维护性）：
 *   1. 单例 DOM：始终只有一个弹窗 DOM 结构，避免重复创建
 *   2. 调用队列：连续调用自动排队，上一个完全关闭后才显示下一个
 *   3. 状态机：closed → opening → open → closing → closed，非法状态直接忽略
 *   4. 单一关闭入口：所有关闭路径（按钮、ESC、背景点击、动画结束、超时）都走 _doClose()
 *
 * 用法：
 *   CmdModal.alert('标题', '消息')           => Promise<void>
 *   CmdModal.confirm('标题', '消息')         => Promise<bool>
 *   CmdModal.prompt('标题', '消息', '默认值') => Promise<string>
 */

window.CmdModal = (function () {

    // ============================================================
    // 状态常量
    // ============================================================
    const STATE = {
        CLOSED:  'closed',   // 完全关闭，display:none
        OPENING: 'opening',  // enter 动画中
        OPEN:    'open',     // 完全打开，等待用户操作
        CLOSING: 'closing',  // leave 动画中
    };

    // ============================================================
    // 内部状态
    // ============================================================
    let state = STATE.CLOSED;
    let queue = [];       // 待显示的弹窗队列 [{type, title, message, defaultValue, resolve}]
    let current = null;   // 当前正在显示的弹窗信息

    // DOM 引用
    let root = null;
    let backdrop = null;
    let container = null;
    let titleEl = null;
    let bodyEl = null;
    let iconEl = null;
    let inputWrap = null;
    let inputEl = null;
    let actionsEl = null;

    let closeTimer = null;  // 关闭动画超时 fallback
    let pendingEnterEnd = null;  // 未完成的 enter 动画监听器（用于在关闭时清理）

    // ============================================================
    // DOM 构建（只执行一次）
    // ============================================================
    function build() {
        if (root) return;

        root = document.createElement('div');
        root.id = 'cmd-modal-root';
        root.style.cssText = 'position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;';

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
        header.appendChild(headerText);

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

        // 全局事件绑定（只绑定一次）
        bindGlobalEvents();
    }

    function bindGlobalEvents() {
        // ESC 关闭
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && state === STATE.OPEN && current) {
                if (current.type === 'confirm') {
                    resolveAndClose(false);
                } else if (current.type === 'prompt') {
                    resolveAndClose('');
                }
                // alert 不支持 ESC 关闭
            }
            // Enter 提交（prompt 模式）
            // 注意：若焦点在按钮上（如 Tab 切换到"取消"），不拦截 Enter，
            // 让按钮自身的 click 事件正常触发，避免语义冲突
            if (e.key === 'Enter' && state === STATE.OPEN && current && current.type === 'prompt') {
                const activeTag = (document.activeElement && document.activeElement.tagName) || '';
                if (activeTag === 'BUTTON') {
                    return;  // 让按钮处理
                }
                e.preventDefault();
                resolveAndClose(inputEl.value);
            }
        });

        // 关闭动画结束
        container.addEventListener('animationend', function (e) {
            // 只响应 leave 动画的结束
            if (e.target !== container) return;
            if (state === STATE.CLOSING && e.animationName === 'cmdModalLeave') {
                finishClose();
            }
        });

        // enter 动画被取消时也要兜底进入 OPEN 状态
        // （onEnterEnd 自身也监听 animationcancel，这里是双保险）
        container.addEventListener('animationcancel', function (e) {
            if (e.target !== container) return;
            if (state === STATE.OPENING && e.animationName === 'cmdModalEnter') {
                // 动画被取消，直接进入 OPEN 状态，避免卡死
                if (pendingEnterEnd) {
                    container.removeEventListener('animationend', pendingEnterEnd);
                    container.removeEventListener('animationcancel', pendingEnterEnd);
                    pendingEnterEnd = null;
                }
                state = STATE.OPEN;
                if (current && current.type === 'prompt') {
                    setTimeout(function () { inputEl.focus(); inputEl.select(); }, 50);
                }
            }
        });
    }

    // ============================================================
    // 状态机核心：显示下一个
    // ============================================================
    function showNext() {
        if (state !== STATE.CLOSED) return;  // 忙，等当前的关完
        if (queue.length === 0) return;       // 没了

        current = queue.shift();
        render(current);
        doShow();
    }

    // ============================================================
    // 渲染弹窗内容
    // ============================================================
    function render(item) {
        titleEl.textContent = item.title || '';
        bodyEl.textContent = item.message || '';

        // 图标
        const iconMap = {
            alert:   ['info',     '#f4d03f'],
            confirm: ['question', '#60a5fa'],
            prompt:  ['question', '#60a5fa'],
        };
        const [iconName, iconColor] = iconMap[item.type] || ['info', '#f4d03f'];
        setIcon(iconName, iconColor);

        // 输入框
        if (item.type === 'prompt') {
            inputWrap.style.display = '';
            inputEl.value = item.defaultValue != null ? item.defaultValue : '';
        } else {
            inputWrap.style.display = 'none';
        }

        // 按钮
        actionsEl.innerHTML = '';
        if (item.type === 'alert') {
            actionsEl.appendChild(makeBtn('确定', 'primary', function () {
                resolveAndClose();
            }));
        } else if (item.type === 'confirm') {
            actionsEl.appendChild(makeBtn('取消', 'ghost', function () {
                resolveAndClose(false);
            }));
            actionsEl.appendChild(makeBtn('确定', 'primary', function () {
                resolveAndClose(true);
            }));
        } else if (item.type === 'prompt') {
            actionsEl.appendChild(makeBtn('取消', 'ghost', function () {
                resolveAndClose('');
            }));
            actionsEl.appendChild(makeBtn('确定', 'primary', function () {
                resolveAndClose(inputEl.value);
            }));
        }
    }

    function setIcon(name, color) {
        iconEl.innerHTML = '';
        const svg = document.createElement('i');
        svg.setAttribute('data-lucide', name);
        svg.className = 'w-5 h-5';
        if (color) svg.style.color = color;
        iconEl.appendChild(svg);

        const bgMap = {
            info:     'rgba(244,208,63,0.15)',
            success:  'rgba(74,222,128,0.15)',
            warning:  'rgba(251,191,36,0.15)',
            error:    'rgba(248,113,113,0.15)',
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
        } else {
            btn.classList.add('bg-cream/10', 'text-cream/80', 'hover:bg-cream/20');
        }
        btn.textContent = text;
        btn.addEventListener('click', onClick);
        return btn;
    }

    // ============================================================
    // 显示动画
    // ============================================================
    function doShow() {
        state = STATE.OPENING;

        root.style.display = 'flex';

        // 清理可能残留的旧监听器（防御）
        if (pendingEnterEnd) {
            container.removeEventListener('animationend', pendingEnterEnd);
            container.removeEventListener('animationcancel', pendingEnterEnd);
            pendingEnterEnd = null;
        }

        // 重启动画
        container.classList.remove('cmd-modal-leave');
        container.classList.remove('cmd-modal-enter');
        void container.offsetWidth;
        container.classList.add('cmd-modal-enter');

        // 动画结束 → 进入 OPEN 状态
        // 同时监听 animationcancel，避免 enter 动画被中途取消时监听器泄漏
        const onEnterEnd = function (e) {
            if (e.target !== container) return;
            if (e.animationName !== 'cmdModalEnter') return;
            // 状态守卫：若期间已被关闭，则不再切到 OPEN
            if (state !== STATE.OPENING) return;
            container.removeEventListener('animationend', onEnterEnd);
            container.removeEventListener('animationcancel', onEnterEnd);
            pendingEnterEnd = null;
            state = STATE.OPEN;
            // prompt 聚焦
            if (current && current.type === 'prompt') {
                setTimeout(function () { inputEl.focus(); inputEl.select(); }, 50);
            }
        };
        pendingEnterEnd = onEnterEnd;
        container.addEventListener('animationend', onEnterEnd);
        container.addEventListener('animationcancel', onEnterEnd);

        // 渲染图标
        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }
    }

    // ============================================================
    // 关闭入口（所有路径都走这里）
    // ============================================================
    function resolveAndClose(result) {
        if (state === STATE.CLOSED || state === STATE.CLOSING) return;
        if (!current) return;

        const item = current;
        current = null;
        doClose();
        item.resolve(result);
    }

    function doClose() {
        if (state === STATE.CLOSED || state === STATE.CLOSING) return;
        state = STATE.CLOSING;

        // 清除超时 fallback
        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }

        // 清理可能未完成的 enter 动画监听器，避免泄漏
        if (pendingEnterEnd) {
            container.removeEventListener('animationend', pendingEnterEnd);
            container.removeEventListener('animationcancel', pendingEnterEnd);
            pendingEnterEnd = null;
        }

        container.classList.remove('cmd-modal-enter');
        container.classList.add('cmd-modal-leave');

        // 超时 fallback：300ms 后强制完成关闭
        closeTimer = setTimeout(function () {
            closeTimer = null;
            finishClose();
        }, 300);
    }

    function finishClose() {
        if (state === STATE.CLOSED) return;

        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }

        container.classList.remove('cmd-modal-leave');
        root.style.display = 'none';
        state = STATE.CLOSED;

        // 处理队列中的下一个
        setTimeout(showNext, 50);
    }

    // ============================================================
    // Public API
    // ============================================================

    function alert(title, message) {
        return new Promise(function (resolve) {
            build();
            queue.push({ type: 'alert', title: title, message: message, resolve: resolve });
            showNext();
        });
    }

    function confirm(title, message) {
        return new Promise(function (resolve) {
            build();
            queue.push({ type: 'confirm', title: title, message: message, resolve: resolve });
            showNext();
        });
    }

    function prompt(title, message, defaultValue) {
        return new Promise(function (resolve) {
            build();
            queue.push({ type: 'prompt', title: title, message: message, defaultValue: defaultValue, resolve: resolve });
            showNext();
        });
    }

    return {
        alert: alert,
        confirm: confirm,
        prompt: prompt,
    };
})();
