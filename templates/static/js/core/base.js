// 滨海小镇 - 基础脚本
// 功能：图标初始化、密码强度、移动端菜单、页面过渡、附件上传、弹窗、Toast、验证码、代码复制等

// 安全初始化 lucide 图标
if (typeof lucide !== 'undefined' && lucide.createIcons) {
    try { lucide.createIcons(); } catch (_) {}
}

// 密码策略：与 core/shared/validation.validate_password_strength 规则保持一致
// 规则：长度 8-30 位；必须同时包含大写字母、小写字母、数字、特殊字符；拒绝常见弱密码
var PasswordPolicy = (function() {
    var MIN_LENGTH = 8;
    var MAX_LENGTH = 30;
    // 常见弱密码（仅用于前端即时提示，完整弱密码库以后端为准）
    var WEAK_PASSWORDS = {
        'password': 1, 'password1': 1, 'password123': 1, 'passw0rd': 1,
        'admin': 1, 'admin123': 1, 'admin1234': 1, 'adminadmin': 1,
        'root1234': 1, 'rootroot': 1, 'manager': 1, 'guest123': 1,
        'test1234': 1, 'testtest': 1, 'temp1234': 1, 'default': 1,
        'iloveyou': 1, 'sunshine': 1, 'princess': 1, 'dragon': 1,
        'monkey': 1, 'football': 1, 'baseball': 1, 'welcome': 1,
        'master': 1, 'shadow': 1, 'killer': 1, 'superman': 1, 'batman': 1,
        'qwerty123': 1, 'qwertyuiop': 1, '1q2w3e4r': 1, '1qaz2wsx': 1,
        'qwe123': 1, 'qweasd': 1, 'a1b2c3d4': 1, 'abcd1234': 1,
        'password!': 1, 'p@ssw0rd': 1, 'minecraft': 1, 'minecraft123': 1
    };

    // 连续递增/递减序列（如 abcdefg、1234567）
    function isSequential(s) {
        if (s.length < 4) return false;
        var asc = true, desc = true;
        for (var i = 1; i < s.length; i++) {
            var diff = s.charCodeAt(i) - s.charCodeAt(i - 1);
            if (diff !== 1) asc = false;
            if (diff !== -1) desc = false;
            if (!asc && !desc) return false;
        }
        return /^[A-Za-z0-9]+$/.test(s);
    }

    function isWeak(password) {
        var s = (password || '').trim().toLowerCase();
        if (!s) return false;
        if (Object.prototype.hasOwnProperty.call(WEAK_PASSWORDS, s)) return true;
        if (s.length >= 4) {
            var first = s.charAt(0), allSame = true;
            for (var i = 1; i < s.length; i++) {
                if (s.charAt(i) !== first) { allSame = false; break; }
            }
            if (allSame) return true;
        }
        return isSequential(s);
    }

    // 返回 { valid, missing: [...], level, empty }
    function validate(password) {
        var pw = password || '';
        if (!pw) {
            return { valid: false, empty: true, level: 0, missing: ['请输入密码'] };
        }
        var missing = [];
        if (pw.length < MIN_LENGTH) missing.push('至少 ' + MIN_LENGTH + ' 位');
        if (pw.length > MAX_LENGTH) missing.push('不超过 ' + MAX_LENGTH + ' 位');
        if (!/[A-Z]/.test(pw)) missing.push('大写字母');
        if (!/[a-z]/.test(pw)) missing.push('小写字母');
        if (!/\d/.test(pw)) missing.push('数字');
        if (!/[^A-Za-z0-9]/.test(pw)) missing.push('特殊字符');
        if (isWeak(pw)) missing.push('不要使用常见弱密码');

        var hasMixedCase = /[a-z]/.test(pw) && /[A-Z]/.test(pw);
        var hasNumber = /\d/.test(pw);
        var hasSymbol = /[^A-Za-z0-9]/.test(pw);
        var level = 1;
        if (pw.length >= MIN_LENGTH && hasMixedCase) {
            level = 2;
            if (hasNumber || hasSymbol) level = 3;
            if (pw.length >= 12 && hasNumber && hasSymbol && hasMixedCase) level = 4;
        }

        return { valid: missing.length === 0, empty: false, level: level, missing: missing };
    }

    return { MIN_LENGTH: MIN_LENGTH, MAX_LENGTH: MAX_LENGTH, validate: validate, isWeak: isWeak };
})();

// 密码强度展示：输入时实时检测，并列出尚未满足的规则
(function initPasswordStrengthIndicators() {
    document.querySelectorAll('input[data-password-strength]').forEach(function(input) {
        if (input.dataset.strengthInitialized === 'true') return;
        input.dataset.strengthInitialized = 'true';

        var indicator = document.createElement('div');
        indicator.className = 'password-strength';
        indicator.dataset.level = '0';
        indicator.setAttribute('aria-live', 'polite');
        indicator.innerHTML =
            '<div class="password-strength-bars" aria-hidden="true">' +
                '<span class="password-strength-bar"></span>'.repeat(4) +
            '</div>' +
            '<div class="password-strength-meta">' +
                '<span class="password-strength-label">密码强度：未输入</span>' +
                '<span class="password-strength-hint">至少 8 位，含大小写字母、数字和特殊字符</span>' +
            '</div>';
        input.insertAdjacentElement('afterend', indicator);

        var label = indicator.querySelector('.password-strength-label');
        var hint = indicator.querySelector('.password-strength-hint');

        function updateStrength() {
            var result = PasswordPolicy.validate(input.value || '');
            input.setCustomValidity(result.valid || result.empty ? '' : result.missing.join('、'));
            if (result.empty) {
                indicator.dataset.level = '0';
                label.textContent = '密码强度：未输入';
                hint.textContent = '至少 8 位，含大小写字母、数字和特殊字符';
                return;
            }

            var labels = ['', '弱', '一般', '中等', '强'];
            indicator.dataset.level = String(result.level);
            label.textContent = '密码强度：' + labels[result.level];
            hint.textContent = result.valid
                ? (result.level < 4 ? '密码符合要求，可再增强强度' : '密码强度良好')
                : '还需：' + result.missing.join('、');
        }

        input.addEventListener('input', updateStrength);
        updateStrength();
    });
})();

// 确认密码实时一致性检测：data-password-confirm="选择器"
(function initPasswordConfirmChecks() {
    document.querySelectorAll('input[data-password-confirm]').forEach(function(confirmInput) {
        if (confirmInput.dataset.confirmInitialized === 'true') return;
        confirmInput.dataset.confirmInitialized = 'true';

        var target = document.querySelector(confirmInput.getAttribute('data-password-confirm'));
        if (!target) return;

        var hint = document.createElement('p');
        hint.className = 'mt-2 text-xs min-h-[1rem] text-cream/50';
        hint.setAttribute('aria-live', 'polite');
        confirmInput.insertAdjacentElement('afterend', hint);

        function updateMatch() {
            var value = confirmInput.value || '';
            if (!value) {
                hint.textContent = '';
                hint.className = 'mt-2 text-xs min-h-[1rem] text-cream/50';
                confirmInput.setCustomValidity('');
                return;
            }
            if (value === (target.value || '')) {
                hint.textContent = '两次输入的密码一致';
                hint.className = 'mt-2 text-xs min-h-[1rem] text-green-400';
                confirmInput.setCustomValidity('');
            } else {
                hint.textContent = '两次输入的密码不一致';
                hint.className = 'mt-2 text-xs min-h-[1rem] text-red-400';
                confirmInput.setCustomValidity('两次输入的密码不一致');
            }
        }

        confirmInput.addEventListener('input', updateMatch);
        target.addEventListener('input', updateMatch);
        updateMatch();
    });
})();

// 移动端菜单控制：打开/关闭侧边菜单，ESC 键关闭
var mobileMenuBtn = document.getElementById('mobile-menu-btn');
var mobileCloseBtn = document.getElementById('mobile-close-btn');
var mobileMenu = document.getElementById('mobile-menu');
var mobileOverlay = document.getElementById('mobile-overlay');

function openMobileMenu() {
    mobileMenu.classList.add('active');
    mobileOverlay.classList.add('active');
    if (mobileMenuBtn) mobileMenuBtn.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
}

function closeMobileMenu() {
    mobileMenu.classList.remove('active');
    mobileOverlay.classList.remove('active');
    if (mobileMenuBtn) mobileMenuBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
}

if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', openMobileMenu);
}
if (mobileCloseBtn) {
    mobileCloseBtn.addEventListener('click', closeMobileMenu);
}
if (mobileOverlay) {
    mobileOverlay.addEventListener('click', closeMobileMenu);
}

// 点击移动菜单中的链接后关闭菜单
document.querySelectorAll('#mobile-menu a').forEach(function (link) {
    link.addEventListener('click', closeMobileMenu);
});

// ESC 键关闭菜单
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        closeMobileMenu();
    }
});

// 页面加载/跳转过渡动画：捕获站内链接点击，添加离场动画后跳转
(function () {
    try {
        var pageContent = document.querySelector('main.page-content');

    // 页面加载完成时触发入场动画
    function triggerEnter() {
        if (pageContent) {
            requestAnimationFrame(function () {
                pageContent.classList.add('page-ready');
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', triggerEnter);
    } else {
        triggerEnter();
    }

    // 页面离开动画
    document.addEventListener('click', function (e) {
        var link = e.target.closest('a[href]');
        if (!link) return;

        var href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('http') ||
            href.startsWith('javascript:') || href.startsWith('mailto:') ||
            link.target === '_blank' || link.hasAttribute('download')) return;

        if (e.ctrlKey || e.metaKey) return;

        e.preventDefault();
        document.body.classList.add('page-leaving');

        setTimeout(function () {
            window.location.href = href;
        }, 350);
    });

    // 浏览器前进/后退可能直接恢复离场时的页面快照，必须先清理离场状态。
    window.addEventListener('pageshow', function (e) {
        document.body.classList.remove('page-leaving');
        if (pageContent) {
            pageContent.classList.remove('page-ready');
            requestAnimationFrame(function () {
                pageContent.classList.add('page-ready');
            });
        }
    });
} catch (e) {
    console.error('页面过渡动画初始化失败:', e);
    // 捕获异常后直接显示页面
    var pc = document.querySelector('main.page-content');
    if (pc) {
        pc.style.opacity = '1';
        pc.style.transform = 'translateY(0)';
        pc.classList.add('page-ready');
    }
}
})();

// 附件上传进度条：监听 multipart/form-data 表单提交，显示上传进度
(function initUploadProgress() {
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form || !form.enctype || form.enctype.toLowerCase() !== 'multipart/form-data') return;
        if (form.dataset.uploadManaged === 'true') return;

        var fileInputs = form.querySelectorAll('input[type="file"]');
        var hasFiles = false;
        fileInputs.forEach(function (input) {
            if (input.files && input.files.length > 0) hasFiles = true;
        });
        if (!hasFiles) return;

        // 找到或创建进度条
        var wrapper = form.querySelector('.upload-progress-wrapper');
        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.className = 'upload-progress-wrapper';
            wrapper.innerHTML = '<div class="upload-progress-bar"><div class="upload-progress-fill purple"></div></div><div class="upload-progress-text"><span class="upload-percent">0%</span><span class="upload-status">上传中...</span></div>';
            var submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
            if (submitBtn && submitBtn.parentElement) {
                submitBtn.parentElement.insertBefore(wrapper, submitBtn.nextSibling);
            } else {
                form.appendChild(wrapper);
            }
        }
        var fill = wrapper.querySelector('.upload-progress-fill');
        var percentEl = wrapper.querySelector('.upload-percent');
        var statusEl = wrapper.querySelector('.upload-status');
        var submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');

        wrapper.classList.add('active');
        fill.style.width = '0%';
        percentEl.textContent = '0%';
        statusEl.textContent = '上传中...';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.style.opacity = '0.6';
        }

        e.preventDefault();
        e.stopPropagation();

        var formData = new FormData(form);
        var xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', function (ev) {
            if (ev.lengthComputable) {
                var pct = Math.round((ev.loaded / ev.total) * 100);
                fill.style.width = pct + '%';
                percentEl.textContent = pct + '%';
                if (pct >= 100) {
                    statusEl.textContent = '处理中...';
                }
            }
        });

        xhr.addEventListener('load', function () {
            fill.style.width = '100%';
            percentEl.textContent = '100%';
            statusEl.textContent = '完成';
            // 延迟后跟随重定向
            setTimeout(function () {
                window.location.href = xhr.getResponseHeader('X-Redirect') || window.location.href;
            }, 300);
        });

        xhr.addEventListener('error', function () {
            statusEl.textContent = '上传失败';
            fill.className = 'upload-progress-fill red';
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.style.opacity = '';
            }
            setTimeout(function () {
                wrapper.classList.remove('active');
                fill.className = 'upload-progress-fill purple';
            }, 2000);
        });

        xhr.addEventListener('abort', function () {
            statusEl.textContent = '已取消';
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.style.opacity = '';
            }
        });

        xhr.open(form.method.toUpperCase(), form.action, true);
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        xhr.send(formData);
    }, true);
})();

// 自定义弹窗系统（alert / confirm / prompt 模式）
var CustomModal = (function () {
    var modal = document.getElementById('custom-modal');
    var modalBox = document.getElementById('modal-box');
    var modalIcon = document.getElementById('modal-icon');
    var modalTitle = document.getElementById('modal-title');
    var modalBody = document.getElementById('modal-body');
    var modalFooter = document.getElementById('modal-footer');
    var modalInputWrap = document.getElementById('modal-input-wrap');
    var modalInput = document.getElementById('modal-input');
    var cancelBtn = document.getElementById('modal-cancel-btn');
    var confirmBtn = document.getElementById('modal-confirm-btn');

    var currentCallback = null;
    var currentTrigger = null;
    var triggerRect = null;
    var pendingResolve = null;
    var currentShowInput = false;

    // options 简写：直接传字符串作为标题（如 confirm('...', '确认清空')）
    function normalizeOptions(options) {
        if (typeof options === 'string') {
            return { title: options };
        }
        return options || {};
    }

    function setIcon(type) {
        var iconMap = {
            'warning': 'alert-triangle',
            'info': 'info',
            'success': 'check-circle',
            'error': 'x-circle',
            'question': 'help-circle'
        };
        var iconName = iconMap[type] || 'info';
        modalIcon.className = 'modal-icon ' + type;
        modalIcon.innerHTML = '<i data-lucide="' + iconName + '" class="w-5 h-5"></i>';
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons({ root: modalIcon }); } catch (_) {}
        }
    }

    function open(options) {
        options = options || {};
        var title = options.title || '提示';
        var content = options.content || '';
        var type = options.type || 'info';
        var showCancel = options.showCancel !== false;
        var confirmText = options.confirmText || '确定';
        var cancelText = options.cancelText || '取消';
        var callback = options.callback || null;
        var trigger = options.trigger || null;
        var showInput = !!options.showInput;
        var inputValue = options.inputValue != null ? String(options.inputValue) : '';
        var placeholder = options.placeholder || '';

        currentCallback = callback;
        currentTrigger = trigger;
        currentShowInput = showInput;

        modalTitle.textContent = title;
        modalBody.textContent = content;
        setIcon(type);

        confirmBtn.textContent = confirmText;
        cancelBtn.textContent = cancelText;
        cancelBtn.style.display = showCancel ? '' : 'none';

        // prompt 模式：显示输入框并预填默认值
        if (modalInputWrap && modalInput) {
            modalInputWrap.style.display = showInput ? '' : 'none';
            modalInput.value = inputValue;
            modalInput.placeholder = placeholder;
        }

        var promise = new Promise(function (resolve) {
            pendingResolve = resolve;
        });

        // 从触发按钮位置放大到中间
        if (trigger) {
            var rect = trigger.getBoundingClientRect();
            triggerRect = rect;
            var vw = window.innerWidth;
            var vh = window.innerHeight;
            var btnCx = rect.left + rect.width / 2;
            var btnCy = rect.top + rect.height / 2;
            var vpCx = vw / 2;
            var vpCy = vh / 2;

            // 计算偏移：从按钮中心到视口中心
            var dx = btnCx - vpCx;
            var dy = btnCy - vpCy;

            // 计算起始缩放：按钮尺寸相对于弹窗尺寸
            var modalW = 440;
            var modalH = 240;
            var scaleX = rect.width / modalW;
            var scaleY = rect.height / modalH;
            var startScale = Math.min(Math.max(scaleX, scaleY, 0.08), 0.35);

            // 重置过渡，设置起始位置
            modalBox.style.transition = 'none';
            modalBox.style.transform = 'translate(' + dx + 'px, ' + dy + 'px) scale(' + startScale + ')';
            modalBox.style.opacity = '0';

            // 显示弹窗
            modal.offsetHeight;
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';

            // 下一帧启用过渡，动画到中心
            requestAnimationFrame(function () {
                modalBox.style.transition = '';
                modalBox.style.transform = 'translate(0, 0) scale(1)';
                modalBox.style.opacity = '1';
            });
        } else {
            // 无触发器：简单淡入
            modalBox.style.transition = 'none';
            modalBox.style.transform = 'scale(0.92)';
            modalBox.style.opacity = '0';

            modal.offsetHeight;
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';

            requestAnimationFrame(function () {
                modalBox.style.transition = '';
                modalBox.style.transform = 'scale(1)';
                modalBox.style.opacity = '1';
            });
        }

        // prompt 模式：弹窗打开后聚焦输入框
        if (showInput && modalInput) {
            setTimeout(function () {
                modalInput.focus();
                modalInput.select();
            }, 120);
        }

        return promise;
    }

    function close(result) {
        // 反向动画：回到触发位置
        if (triggerRect) {
            var vw = window.innerWidth;
            var vh = window.innerHeight;
            var btnCx = triggerRect.left + triggerRect.width / 2;
            var btnCy = triggerRect.top + triggerRect.height / 2;
            var vpCx = vw / 2;
            var vpCy = vh / 2;
            var dx = btnCx - vpCx;
            var dy = btnCy - vpCy;
            var modalW = 440;
            var modalH = 240;
            var scaleX = triggerRect.width / modalW;
            var scaleY = triggerRect.height / modalH;
            var endScale = Math.min(Math.max(scaleX, scaleY, 0.08), 0.35);

            modalBox.style.transition = '';
            modalBox.style.transform = 'translate(' + dx + 'px, ' + dy + 'px) scale(' + endScale + ')';
            modalBox.style.opacity = '0';
        } else {
            modalBox.style.transform = 'scale(0.92)';
            modalBox.style.opacity = '0';
        }

        setTimeout(function () {
            modal.classList.remove('active');
            document.body.style.overflow = '';

            // prompt 模式：确认返回输入值，取消/关闭返回 null
            var value = result;
            if (currentShowInput) {
                value = result ? (modalInput ? modalInput.value : '') : null;
            }

            if (currentCallback) {
                currentCallback(value);
                currentCallback = null;
            }
            if (pendingResolve) {
                pendingResolve(value);
                pendingResolve = null;
            }
            currentTrigger = null;
            triggerRect = null;
            currentShowInput = false;

            // 等遮罩淡出（0.3s）结束后再清理内联样式。
            // 若立即清理，弹窗卡片会先回到 opacity:1 / scale(1)，
            // 在遮罩尚未消失时「闪现」出一个重影后再关闭。
            setTimeout(function () {
                if (modal.classList.contains('active')) return; // 期间又被重新打开则不清
                modalBox.style.transform = '';
                modalBox.style.opacity = '';
                modalBox.style.transition = '';
            }, 320);
        }, 400);
    }

    if (confirmBtn) {
        confirmBtn.addEventListener('click', function () {
            close(true);
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function () {
            close(false);
        });
    }

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && modal && modal.classList.contains('active')) {
            close(false);
        }
        if (e.key === 'Enter' && modal && modal.classList.contains('active')) {
            close(true);
        }
    });

    // 点击遮罩关闭
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal) {
                close(false);
            }
        });
    }

    return {
        open: open,
        close: close,
        alert: function (message, options) {
            options = normalizeOptions(options);
            return open({
                title: options.title || '提示',
                content: message,
                type: options.type || 'info',
                showCancel: false,
                confirmText: options.confirmText || '确定',
                trigger: options.trigger || null,
                callback: options.callback || null
            });
        },
        confirm: function (message, options) {
            options = normalizeOptions(options);
            return open({
                title: options.title || '确认',
                content: message,
                type: options.type || 'warning',
                showCancel: true,
                confirmText: options.confirmText || '确定',
                cancelText: options.cancelText || '取消',
                trigger: options.trigger || null,
                callback: options.callback || null
            });
        },
        prompt: function (message, options) {
            options = normalizeOptions(options);
            return open({
                title: options.title || '输入',
                content: message,
                type: options.type || 'info',
                showCancel: true,
                confirmText: options.confirmText || '确定',
                cancelText: options.cancelText || '取消',
                showInput: true,
                inputValue: options.defaultValue != null ? options.defaultValue : '',
                placeholder: options.placeholder || '',
                trigger: options.trigger || null,
                callback: options.callback || null
            });
        }
    };
})();

// Toast 提示系统（成功/错误/警告/信息）
var Toast = (function () {
    var container = document.getElementById('toast-container');

    function show(message, type, duration) {
        type = type || 'info';
        duration = duration || 3000;

        var toast = document.createElement('div');
        toast.className = 'toast ' + type;

        var iconMap = {
            'success': 'check-circle',
            'error': 'x-circle',
            'warning': 'alert-triangle',
            'info': 'info'
        };
        var iconName = iconMap[type] || 'info';

        toast.innerHTML = '<i data-lucide="' + iconName + '" class="w-5 h-5"></i><span>' + message + '</span>';

        container.appendChild(toast);
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons({ root: toast }); } catch (_) {}
        }

        requestAnimationFrame(function () {
            toast.classList.add('show');
        });

        setTimeout(function () {
            toast.classList.remove('show');
            setTimeout(function () {
                toast.remove();
            }, 400);
        }, duration);
    }

    return {
        show: show,
        success: function (msg, duration) { show(msg, 'success', duration); },
        error: function (msg, duration) { show(msg, 'error', duration); },
        warning: function (msg, duration) { show(msg, 'warning', duration); },
        info: function (msg, duration) { show(msg, 'info', duration); }
    };
})();

// 退出登录确认
(function initLogoutConfirm() {
    document.querySelectorAll('a[data-logout-confirm]').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            // 阻止全站页面跳转动画提前访问 logout，必须等待用户明确确认。
            e.stopPropagation();

            CustomModal.confirm('退出后需要重新登录，是否确认退出？', {
                title: '退出登录',
                type: 'question',
                confirmText: '确认',
                cancelText: '取消',
                trigger: link,
                callback: function (confirmed) {
                    if (confirmed) {
                        window.location.href = link.href;
                    }
                }
            });
        });
    });
})();

(function initCustomConfirm() {
    function processForm(form) {
        var onsubmit = form.getAttribute('onsubmit');
        if (!onsubmit || onsubmit.indexOf('confirm(') === -1) return;

        var match = onsubmit.match(/confirm\(['"](.+?)['"]\)/);
        var message = match ? match[1] : '确定要执行此操作吗？';

        form.removeAttribute('onsubmit');

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            e.stopPropagation();

            var submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');

            CustomModal.confirm(message, {
                trigger: submitBtn,
                callback: function (result) {
                    if (result) {
                        form.submit();
                    }
                }
            });
        }, true);
    }

    function processLink(link) {
        var onclick = link.getAttribute('onclick');
        if (!onclick || onclick.indexOf('confirm(') === -1) return;

        var match = onclick.match(/confirm\(['"](.+?)['"]\)/);
        var message = match ? match[1] : '确定要执行此操作吗？';

        link.removeAttribute('onclick');

        link.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();

            CustomModal.confirm(message, {
                trigger: link,
                callback: function (result) {
                    if (result) {
                        window.location.href = link.href;
                    }
                }
            });
        }, true);
    }

    function scan(root) {
        if (root.matches && root.matches('form[onsubmit*="confirm("]')) processForm(root);
        if (root.matches && root.matches('a[onclick*="confirm("]')) processLink(root);
        root.querySelectorAll && root.querySelectorAll('form[onsubmit*="confirm("]').forEach(processForm);
        root.querySelectorAll && root.querySelectorAll('a[onclick*="confirm("]').forEach(processLink);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            scan(document.body);
        });
    } else {
        scan(document.body);
    }

    var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
            m.addedNodes.forEach(function (node) {
                if (node.nodeType === 1) scan(node);
            });
        });
    });

    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }
})();

// 图形验证码弹窗
var CaptchaModal = (function () {
    var modal = document.getElementById('captcha-modal');
    if (!modal) return { show: function() {}, hide: function() {} };

    var captchaImg = document.getElementById('modal-captcha-img');
    var captchaIdInput = document.getElementById('modal-captcha-id');
    var captchaCodeInput = document.getElementById('modal-captcha-input');
    var captchaSubmit = document.getElementById('modal-captcha-submit');
    var captchaRefresh = document.getElementById('modal-captcha-refresh');
    var captchaClose = document.getElementById('modal-captcha-close');
    var captchaHint = document.getElementById('captcha-modal-hint');

    var captchaCallback = null;
    var captchaRequestId = 0;

    function loadModalCaptcha() {
        var previousId = captchaIdInput ? captchaIdInput.value : '';
        var currentRequestId = ++captchaRequestId;
        if (captchaIdInput) captchaIdInput.value = '';
        captchaImg.alt = '验证码加载中';
        var url = '/api/captcha/generate' + (previousId ? '?previous_id=' + encodeURIComponent(previousId) : '');
        fetch(url, { cache: 'no-store' })
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (currentRequestId !== captchaRequestId) return;
                if (data.success && data.image && data.captcha_id) {
                    captchaImg.src = data.image;
                    captchaImg.alt = '四位图形验证码，点击可刷新';
                    if (captchaIdInput) captchaIdInput.value = data.captcha_id || '';
                } else {
                    captchaImg.alt = '验证码加载失败，点击重试';
                }
            })
            .catch(function(err) {
                if (currentRequestId === captchaRequestId) captchaImg.alt = '验证码加载失败，点击重试';
                console.error('加载验证码失败:', err);
            });
    }

    function show(hint, callback) {
        if (!modal) return;
        captchaHint.textContent = hint || '请完成图形验证码';
        captchaCodeInput.value = '';
        captchaCallback = callback;
        openModal('captcha-modal');
        loadModalCaptcha();
        setTimeout(function() { captchaCodeInput.focus(); }, 150);
    }

    function hide() {
        if (!modal) return;
        closeModal('captcha-modal');
        captchaCallback = null;
    }

    function verify() {
        var code = captchaCodeInput.value.trim();
        if (code.length !== 4) {
            if (typeof Toast !== 'undefined' && Toast.warning) Toast.warning('请输入完整的 4 位验证码');
            captchaCodeInput.focus();
            return;
        }
        var captchaId = captchaIdInput.value;
        if (!captchaId) {
            if (typeof Toast !== 'undefined' && Toast.warning) Toast.warning('验证码正在加载，请稍候');
            return;
        }

        captchaSubmit.disabled = true;
        captchaSubmit.textContent = '验证中...';

        fetch('/api/captcha/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                captcha_id: captchaId,
                captcha: code
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.success) {
                if (typeof captchaCallback === 'function') {
                    captchaCallback(captchaId, code);
                }
                hide();
            } else {
                if (typeof Toast !== 'undefined' && Toast.error) Toast.error(data.message || '验证码错误');
                captchaCodeInput.value = '';
                loadModalCaptcha();
                captchaCodeInput.focus();
            }
        })
        .catch(function() {
            if (typeof Toast !== 'undefined' && Toast.error) Toast.error('网络错误，请重试');
        })
        .finally(function() {
            captchaSubmit.disabled = false;
            captchaSubmit.textContent = '验证';
        });
    }

    // 事件绑定
    if (captchaSubmit) captchaSubmit.addEventListener('click', verify);
    if (captchaCodeInput) captchaCodeInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') verify();
    });
    if (captchaRefresh) captchaRefresh.addEventListener('click', function() {
        captchaCodeInput.value = '';
        loadModalCaptcha();
    });
    if (captchaImg) captchaImg.addEventListener('click', function() {
        captchaCodeInput.value = '';
        loadModalCaptcha();
    });
    if (captchaClose) captchaClose.addEventListener('click', hide);
    if (modal) modal.addEventListener('click', function(e) {
        if (e.target === modal) hide();
    });

    return { show: show, hide: hide };
})();

window.__showCaptchaModal = CaptchaModal.show;
window.__hideCaptchaModal = CaptchaModal.hide;

// 代码一键复制：为 <pre><code> 块添加复制按钮，支持 clipboard API 和 fallback
var CodeBlocks = (function () {
    // 为所有 <pre><code> 块添加复制按钮
    function enhance(root) {
        if (!root) root = document;
        var blocks = root.querySelectorAll('pre code');
        blocks.forEach(function (codeEl) {
            var pre = codeEl.parentElement;
            if (!pre || pre.tagName !== 'PRE') return;
            // 已处理过则跳过
            if (pre.querySelector('.code-copy-btn')) return;

            // 设置相对定位
            pre.style.position = 'relative';

            // 创建复制按钮
            var btn = document.createElement('button');
            btn.className = 'code-copy-btn';
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> 复制';
            btn.setAttribute('aria-label', '复制代码');
            pre.appendChild(btn);

            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var text = codeEl.textContent || '';
                // 去掉末尾多余的换行
                text = text.replace(/\n$/, '');
                navigator.clipboard.writeText(text).then(function () {
                    var orig = btn.innerHTML;
                    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> 已复制';
                    btn.classList.add('copied');
                    setTimeout(function () {
                        btn.innerHTML = orig;
                        btn.classList.remove('copied');
                    }, 2000);
                }).catch(function () {
                    // clipboard 失败时 fallback
                    var ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.position = 'fixed';
                    ta.style.left = '-9999px';
                    document.body.appendChild(ta);
                    ta.select();
                    try {
                        document.execCommand('copy');
                        var orig = btn.innerHTML;
                        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> 已复制';
                        btn.classList.add('copied');
                        setTimeout(function () {
                            btn.innerHTML = orig;
                            btn.classList.remove('copied');
                        }, 2000);
                    } catch (err) {
                        btn.innerHTML = '复制失败';
                    }
                    document.body.removeChild(ta);
                });
            });
        });
    }

    // 自动增强：监听 DOM 变化（用于动态加载的内容）
    var observer = null;
    function startObserver() {
        if (observer) return;
        observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1) {
                        // 如果新节点包含 <pre><code>
                        if (node.querySelector && node.querySelector('pre code')) {
                            enhance(node);
                        }
                    }
                });
            });
        });
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

    // DOMContentLoaded 时增强一次
    function init() {
        enhance(document.body);
        startObserver();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { enhance: enhance };
})();

// 复制音频时长（秒）
document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('.copy-duration-btn') : null;
    if (!btn) return;
    var seconds = btn.getAttribute('data-seconds') || '';
    if (!seconds) return;

    function done(ok) {
        if (typeof Toast !== 'undefined') {
            if (ok) Toast.success('时长已复制：' + seconds + ' 秒');
            else Toast.error('复制失败，请手动复制');
        }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(seconds).then(function () { done(true); }, function () { done(false); });
    } else {
        var ta = document.createElement('textarea');
        ta.value = seconds;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { done(document.execCommand('copy')); } catch (_) { done(false); }
        document.body.removeChild(ta);
    }
});

// 大喇叭音频收藏
(function () {
    function updateFavoriteBtn(btn, isFav) {
        btn.setAttribute('data-state', isFav ? '1' : '0');
        btn.setAttribute('title', isFav ? '取消收藏' : '收藏');
        var text = btn.querySelector('.fav-text');
        if (text) text.textContent = isFav ? '已收藏' : '收藏';
        var icon = btn.querySelector('[data-lucide="heart"]');
        if (icon) {
            if (isFav) icon.classList.add('fill-amber-400');
            else icon.classList.remove('fill-amber-400');
        }
        btn.classList.toggle('border-amber-400/50', isFav);
        btn.classList.toggle('text-amber-300', isFav);
        btn.classList.toggle('border-cream/20', !isFav);
        btn.classList.toggle('text-cream/70', !isFav);
    }

    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.favorite-btn') : null;
        if (!btn) return;
        var musicId = btn.getAttribute('data-id');
        if (!musicId) return;

        if (btn.getAttribute('data-requires-login') === '1') {
            if (typeof Toast !== 'undefined') Toast.warning('请先登录后再收藏');
            setTimeout(function () {
                location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
            }, 800);
            return;
        }

        btn.disabled = true;
        fetch('/music/' + encodeURIComponent(musicId) + '/favorite', {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            btn.disabled = false;
            if (!data || !data.success) {
                if (typeof Toast !== 'undefined') Toast.error((data && data.message) || '操作失败');
                return;
            }
            updateFavoriteBtn(btn, data.is_favorited);
            if (typeof Toast !== 'undefined') Toast.success(data.message);
            // 「我的收藏」页取消收藏时，淡出移除该卡片；无收藏时刷新显示空状态
            if (!data.is_favorited && /\/music\/my\/favorites/.test(location.pathname)) {
                var card = btn.closest('.music-card');
                if (card) {
                    card.style.transition = 'opacity .3s';
                    card.style.opacity = '0';
                    setTimeout(function () {
                        card.remove();
                        if (!document.querySelector('.music-card')) location.reload();
                    }, 300);
                }
            }
        })
        .catch(function () {
            btn.disabled = false;
            if (typeof Toast !== 'undefined') Toast.error('网络异常，操作失败');
        });
    });
})();

// 管理中心无刷新操作（通用）
// 用法：给任意按钮/链接加 .admin-action，并设置以下 data-* 属性：
//   data-action-url      请求地址（必填）
//   data-action-method   请求方法，默认 POST
//   data-action-confirm  执行前确认提示（可选）
//   data-action-success  成功提示（可选，默认使用后端返回的 message）
//   data-action-payload  请求体（JSON 字符串，可选；不填则发送空请求）
//   data-action-remove   成功后移除的元素选择器（从按钮向上查找，可选，如 "tr"）
//   data-action-reload   成功后是否刷新页面（"1" 刷新，默认 0）
// 成功后会在 document 派发 admin:action 事件，detail = {el, data, url, method}，
// 页面可监听该事件做局部 DOM 更新（无需刷新页面）。
(function initAdminActions() {
    function parseError(res, data) {
        if (res.status === 429) return (data && data.message) || '操作过于频繁，请稍后重试';
        if (res.status === 403) return (data && data.message) || '没有权限执行该操作';
        return (data && data.message) || ('操作失败（' + res.status + '）');
    }

    function run(el) {
        var url = el.getAttribute('data-action-url');
        if (!url) return;

        var method = (el.getAttribute('data-action-method') || 'POST').toUpperCase();
        var payload = el.getAttribute('data-action-payload');
        var removeSel = el.getAttribute('data-action-remove');
        var reload = el.getAttribute('data-action-reload') === '1';
        var successMsg = el.getAttribute('data-action-success');

        var opts = {
            method: method,
            headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
        };
        // 统一以 JSON 提交：既满足「API 使用 JSON 格式」，也使请求免于表单 CSRF 校验
        // （application/json 的跨域 POST 无法由简单表单伪造）。
        if (method !== 'GET' && method !== 'HEAD') {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = payload || '{}';
        }

        el.disabled = true;
        el.classList.add('is-loading');

        fetch(url, opts)
            .then(function (res) {
                return res.json().catch(function () { return {}; }).then(function (data) {
                    return { res: res, data: data };
                });
            })
            .then(function (r) {
                var data = r.data || {};
                if (!r.res.ok || data.success === false) {
                    if (typeof Toast !== 'undefined') Toast.error(parseError(r.res, data));
                    return;
                }
                if (typeof Toast !== 'undefined') Toast.success(data.message || successMsg || '操作成功');

                if (removeSel) {
                    var node = el.closest(removeSel);
                    if (node) {
                        node.style.transition = 'opacity .25s ease';
                        node.style.opacity = '0';
                        setTimeout(function () { node.remove(); }, 250);
                    }
                }
                document.dispatchEvent(new CustomEvent('admin:action', {
                    detail: { el: el, data: data, url: url, method: method }
                }));
                if (reload) setTimeout(function () { location.reload(); }, 400);
            })
            .catch(function () {
                if (typeof Toast !== 'undefined') Toast.error('网络异常，操作失败');
            })
            .finally(function () {
                el.disabled = false;
                el.classList.remove('is-loading');
            });
    }

    document.addEventListener('click', function (e) {
        var el = e.target && e.target.closest ? e.target.closest('.admin-action') : null;
        if (!el || el.disabled) return;
        e.preventDefault();
        e.stopPropagation();

        var confirmMsg = el.getAttribute('data-action-confirm');
        if (confirmMsg) {
            CustomModal.confirm(confirmMsg, {
                trigger: el,
                callback: function (ok) { if (ok) run(el); }
            });
        } else {
            run(el);
        }
    });
})();

// 大喇叭音频标签编辑
(function () {
    function renderTags(container, tags) {
        container.innerHTML = '';
        if (!tags) return;
        tags.split(',').forEach(function (tag) {
            tag = (tag || '').trim();
            if (!tag) return;
            var span = document.createElement('span');
            span.className = 'inline-block px-2 py-0.5 rounded-full text-xs bg-gold-400/10 text-gold-300/90 border border-gold-400/20 mr-1 mb-1';
            span.textContent = '#' + tag;
            container.appendChild(span);
        });
    }

    function saveTags(btn, musicId, next) {
        btn.disabled = true;
        var body = new URLSearchParams();
        body.append('tags', (next || '').trim());
        fetch('/music/' + encodeURIComponent(musicId) + '/tags', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' },
            body: body.toString()
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            btn.disabled = false;
            if (!data || !data.success) {
                if (typeof Toast !== 'undefined') Toast.error((data && data.message) || '保存失败');
                return;
            }
            btn.setAttribute('data-tags', (next || '').trim());
            var wrap = btn.closest('.music-card') || btn.closest('tr');
            if (wrap) {
                var container = wrap.querySelector('.tags-display');
                if (container) renderTags(container, next);
            }
            if (typeof Toast !== 'undefined') Toast.success(data.message || '标签已保存');
        })
        .catch(function () {
            btn.disabled = false;
            if (typeof Toast !== 'undefined') Toast.error('网络异常，保存失败');
        });
    }

    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.edit-tags-btn') : null;
        if (!btn) return;
        var musicId = btn.getAttribute('data-id');
        if (!musicId) return;
        var current = btn.getAttribute('data-tags') || '';

        CustomModal.prompt('编辑标签（逗号分隔，最多 10 个，每个 ≤12 字）：', {
            title: '编辑标签',
            defaultValue: current,
            placeholder: '例如：BGM, 开服, 活动曲',
            trigger: btn,
            callback: function (value) {
                if (value === null) return;
                saveTags(btn, musicId, value);
            }
        });
    });
})();

/* ============================================================
   自定义开关 (.switch) —— 点击/键盘切换，hidden input 存值
   ============================================================ */
document.addEventListener('click', function (e) {
    var sw = e.target.closest('[data-switch]');
    if (!sw) return;
    toggleSwitch(sw);
});
document.addEventListener('keydown', function (e) {
    if (e.code !== 'Space' && e.code !== 'Enter') return;
    var sw = document.activeElement && document.activeElement.closest('[data-switch]');
    if (!sw) return;
    e.preventDefault();
    toggleSwitch(sw);
});
function toggleSwitch(sw) {
    var on = sw.classList.toggle('is-on');
    sw.setAttribute('aria-checked', on ? 'true' : 'false');
    var hidden = sw.querySelector('input[type="hidden"]');
    if (hidden) hidden.value = on ? '1' : '0';
    sw.dispatchEvent(new CustomEvent('change', { bubbles: true }));
}

/* ============================================================
   自定义下拉 (.custom-select) —— 点击展开 + 键盘导航
   ============================================================ */
document.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-custom-select] [data-trigger]');
    if (trigger) {
        var cs = trigger.closest('[data-custom-select]');
        document.querySelectorAll('[data-custom-select].is-open').forEach(function (el) {
            if (el !== cs) closeSelect(el);
        });
        openSelect(cs);
        return;
    }
    if (!e.target.closest('[data-custom-select]')) {
        document.querySelectorAll('[data-custom-select].is-open').forEach(closeSelect);
    }
});
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('[data-custom-select].is-open').forEach(closeSelect);
    }
});
function openSelect(cs) {
    cs.classList.add('is-open');
    var trigger = cs.querySelector('[data-trigger]');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    // 选中当前值对应的 option
    var hidden = cs.querySelector('input[type="hidden"]');
    var current = hidden ? hidden.value : '';
    var opts = cs.querySelectorAll('.custom-select-option');
    opts.forEach(function (o) { o.classList.remove('is-hover'); });
    opts.forEach(function (o) {
        if (o.getAttribute('data-value') === current) {
            o.classList.add('is-hover');
            o.scrollIntoView({ block: 'nearest' });
        }
    });
}
function closeSelect(cs) {
    cs.classList.remove('is-open');
    var trigger = cs.querySelector('[data-trigger]');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
}
document.addEventListener('click', function (e) {
    var opt = e.target.closest('.custom-select-option');
    if (!opt) return;
    var cs = opt.closest('[data-custom-select]');
    if (!cs) return;
    // 清空之前的选中标记
    cs.querySelectorAll('.custom-select-option.is-selected').forEach(function (o) {
        o.classList.remove('is-selected');
    });
    opt.classList.add('is-selected');
    // 更新 label
    var label = cs.querySelector('.custom-select-label');
    if (label) label.textContent = opt.textContent.trim();
    // 更新 hidden input
    var hidden = cs.querySelector('input[type="hidden"]');
    var value = opt.getAttribute('data-value');
    if (hidden) {
        var prev = hidden.value;
        hidden.value = value;
        if (prev !== value) {
            hidden.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
    closeSelect(cs);
});
