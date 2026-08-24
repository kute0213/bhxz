/* ============================================================
 * base.js — 全站基础脚本（由 templates/base.html 提取）
 * 包含：移动端菜单、页面过渡、附件上传进度、自定义弹窗、
 *       Toast 提示、原生 confirm 拦截替换、图形验证码弹窗
 * 暴露全局对象：CustomModal、Toast、CaptchaModal
 * 页面级脚本通过 {% block extra_script %} 注入
 * 依赖：Tailwind CSS CDN、Lucide CDN（在 base.html 中加载）
 * ============================================================ */

// 安全初始化 lucide 图标（CDN 可能加载失败）
if (typeof lucide !== 'undefined' && lucide.createIcons) {
    try { lucide.createIcons(); } catch (_) {}
}

// 密码强度展示：必需规则与 core.auth.validate_password 保持一致。
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
                '<span class="password-strength-hint">至少 8 位且包含字母</span>' +
            '</div>';
        input.insertAdjacentElement('afterend', indicator);

        var label = indicator.querySelector('.password-strength-label');
        var hint = indicator.querySelector('.password-strength-hint');

        function updateStrength() {
            var password = input.value || '';
            if (!password) {
                indicator.dataset.level = '0';
                label.textContent = '密码强度：未输入';
                hint.textContent = '至少 8 位且包含字母';
                return;
            }

            var hasLetter = /\p{L}/u.test(password);
            var hasNumber = /\d/.test(password);
            var hasSymbol = /[^A-Za-z0-9]/.test(password);
            var hasMixedCase = /[a-z]/.test(password) && /[A-Z]/.test(password);
            var validLength = password.length >= 8;
            var level = 1;

            if (validLength && hasLetter) {
                level = 2;
                if (hasNumber || hasSymbol || hasMixedCase) level = 3;
                if (password.length >= 12 && hasNumber && hasSymbol && hasMixedCase) level = 4;
            }

            var labels = ['', '弱', '一般', '中等', '强'];
            indicator.dataset.level = String(level);
            label.textContent = '密码强度：' + labels[level];

            var missing = [];
            if (!validLength) missing.push('至少 8 位');
            if (!hasLetter) missing.push('包含字母');
            if (missing.length) {
                hint.textContent = '还需：' + missing.join('、');
            } else if (level < 4) {
                hint.textContent = '可加入大小写字母、数字和符号增强';
            } else {
                hint.textContent = '密码强度良好';
            }
        }

        input.addEventListener('input', updateStrength);
        updateStrength();
    });
})();

// 移动端菜单控制
var mobileMenuBtn = document.getElementById('mobile-menu-btn');
var mobileCloseBtn = document.getElementById('mobile-close-btn');
var mobileMenu = document.getElementById('mobile-menu');
var mobileOverlay = document.getElementById('mobile-overlay');

function openMobileMenu() {
    mobileMenu.classList.add('active');
    mobileOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeMobileMenu() {
    mobileMenu.classList.remove('active');
    mobileOverlay.classList.remove('active');
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

// 页面加载/跳转过渡动画
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

// ============================================
// 附件上传进度条
// ============================================
(function initUploadProgress() {
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form || !form.enctype || form.enctype.toLowerCase() !== 'multipart/form-data') return;

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

// ============================================
// 自定义弹窗系统 - 从按钮放大移动到中间
// ============================================
var CustomModal = (function () {
    var modal = document.getElementById('custom-modal');
    var modalBox = document.getElementById('modal-box');
    var modalIcon = document.getElementById('modal-icon');
    var modalTitle = document.getElementById('modal-title');
    var modalBody = document.getElementById('modal-body');
    var modalFooter = document.getElementById('modal-footer');
    var cancelBtn = document.getElementById('modal-cancel-btn');
    var confirmBtn = document.getElementById('modal-confirm-btn');

    var currentCallback = null;
    var currentTrigger = null;
    var triggerRect = null;

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

        currentCallback = callback;
        currentTrigger = trigger;

        modalTitle.textContent = title;
        modalBody.textContent = content;
        setIcon(type);

        confirmBtn.textContent = confirmText;
        cancelBtn.textContent = cancelText;
        cancelBtn.style.display = showCancel ? '' : 'none';

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
            modalBox.style.transform = '';
            modalBox.style.opacity = '';
            modalBox.style.transition = '';

            if (currentCallback) {
                currentCallback(result);
                currentCallback = null;
            }
            currentTrigger = null;
            triggerRect = null;
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
            options = options || {};
            open({
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
            options = options || {};
            open({
                title: options.title || '确认',
                content: message,
                type: options.type || 'warning',
                showCancel: true,
                confirmText: options.confirmText || '确定',
                cancelText: options.cancelText || '取消',
                trigger: options.trigger || null,
                callback: options.callback || null
            });
        }
    };
})();

// ============================================
// Toast 提示系统
// ============================================
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

// ============================================
// 退出登录确认：取消时保留当前会话，确认后才跳转退出路由
// ============================================
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

// ============================================
// 图形验证码弹窗（全局共享，供注册/找回密码等页面使用）
// 暴露全局对象：CaptchaModal
// 页面代码通过 CaptchaModal.show(hint, callback) 调用
// ============================================
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

    function loadModalCaptcha() {
        fetch('/api/captcha/generate')
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.success) {
                    captchaImg.src = data.image;
                    if (captchaIdInput) captchaIdInput.value = data.captcha_id || '';
                }
            })
            .catch(function(err) { console.error('加载验证码失败:', err); });
    }

    function show(hint, callback) {
        if (!modal) return;
        captchaHint.textContent = hint || '请完成图形验证码';
        captchaCodeInput.value = '';
        captchaCallback = callback;
        modal.style.display = 'block';
        loadModalCaptcha();
        setTimeout(function() { captchaCodeInput.focus(); }, 100);
    }

    function hide() {
        if (!modal) return;
        modal.style.display = 'none';
        captchaCallback = null;
    }

    function verify() {
        var code = captchaCodeInput.value.trim();
        if (!code) {
            if (typeof Toast !== 'undefined' && Toast.warning) Toast.warning('请输入验证码');
            captchaCodeInput.focus();
            return;
        }
        var captchaId = captchaIdInput.value;

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

// 向后兼容：旧的 window.__showCaptchaModal / __hideCaptchaModal 指向 CaptchaModal
window.__showCaptchaModal = CaptchaModal.show;
window.__hideCaptchaModal = CaptchaModal.hide;

// ============================================
// 代码一键复制
// ============================================
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

/* ============================================================
 * 复制音频时长（秒）—— 全站全局代理：
 * 任何页面上的 .copy-duration-btn（大喇叭音频「时长 Ns」按钮）
 * 点击后复制其 data-seconds 属性中的秒数到剪贴板。
 * 使用事件委托，对动态加载的按钮同样生效。
 * ============================================================ */
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

/* ============================================================
 * 大喇叭音频收藏 —— 全站全局代理：
 * 任何页面上的 .favorite-btn（收藏/取消收藏按钮）
 * 点击后调用 POST /music/<id>/favorite 切换收藏状态。
 * 使用事件委托，对动态加载的按钮同样生效；
 * 未登录按钮带 data-requires-login 提示跳转登录。
 * ============================================================ */
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

/* ============================================================
 * 大喇叭音频标签编辑 —— 全站全局代理：
 * 任何页面上的 .edit-tags-btn（编辑标签按钮）
 * 点击后 prompt 输入新标签，POST 到 /music/<id>/tags 保存。
 * 成功后在卡片内就地刷新标签徽章。
 * ============================================================ */
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

    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.edit-tags-btn') : null;
        if (!btn) return;
        var musicId = btn.getAttribute('data-id');
        if (!musicId) return;
        var current = btn.getAttribute('data-tags') || '';
        var next = prompt('编辑标签（逗号分隔，最多 10 个）：', current);
        if (next === null) return;

        btn.disabled = true;
        var body = new URLSearchParams();
        body.append('tags', next.trim());
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
            btn.setAttribute('data-tags', next.trim());
            var wrap = btn.closest('.music-card') || btn.closest('tr');
            if (wrap) {
                var container = wrap.querySelector('.tags-display');
                if (container) renderTags(container, next.trim());
            }
            if (typeof Toast !== 'undefined') Toast.success(data.message || '标签已保存');
        })
        .catch(function () {
            btn.disabled = false;
            if (typeof Toast !== 'undefined') Toast.error('网络异常，保存失败');
        });
    });
})();
