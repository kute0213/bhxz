/* ============================================================
 * base.js — 全站基础脚本（由 templates/base.html 提取）
 * 包含：移动端菜单、页面过渡、附件上传进度、自定义弹窗、
 *       Toast 提示、原生 confirm 拦截替换、图形验证码弹窗
 * 暴露全局对象：CustomModal、Toast、CaptchaModal
 * 页面级脚本通过 {% block extra_script %} 注入
 * 依赖：Tailwind CSS CDN、Lucide CDN（在 base.html 中加载）
 * ============================================================ */

lucide.createIcons();

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

    // 浏览器后退时重新触发入场动画
    window.addEventListener('pageshow', function (e) {
        if (e.persisted && pageContent) {
            pageContent.classList.remove('page-ready');
            requestAnimationFrame(function () {
                pageContent.classList.add('page-ready');
            });
        }
    });
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
            wrapper.innerHTML = '<div class="upload-progress-bar"><div class="upload-progress-fill"></div></div><div class="upload-progress-text"><span class="upload-percent">0%</span><span class="upload-status">上传中...</span></div>';
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
            fill.style.background = '#ef4444';
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.style.opacity = '';
            }
            setTimeout(function () {
                wrapper.classList.remove('active');
                fill.style.background = '';
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
        if (window.lucide) {
            lucide.createIcons({ root: modalIcon });
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
        if (window.lucide) {
            lucide.createIcons({ root: toast });
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
