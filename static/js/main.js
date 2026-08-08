document.addEventListener('DOMContentLoaded', function() {
    if (window.__animationsInitialized) return;
    window.__animationsInitialized = true;

    initScrollAnimations();
    initSmoothScroll();
    initButtonFeedback();
    initMouseGlow();
    initScrollProgress();
    initStaggerReveal();
    initTextReveal();
    initCardTilt();
    initParallax();
    initParticles();
});

// ============================================
// 滚动渐入（基础）
// ============================================
function initScrollAnimations() {
    var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var animatedElements = document.querySelectorAll('.section-fade');

    if (prefersReduced) {
        animatedElements.forEach(function(el) {
            el.classList.add('visible');
        });
        return;
    }

    var observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.05, rootMargin: '0px 0px -30px 0px' });

    animatedElements.forEach(function(el) {
        observer.observe(el);
    });
}

// ============================================
// 平滑滚动
// ============================================
function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
        anchor.addEventListener('click', function(e) {
            var href = this.getAttribute('href');
            if (href === '#' || href.length < 2) return;

            var target = document.querySelector(href);
            if (!target) return;

            e.preventDefault();
            var offsetPosition = target.getBoundingClientRect().top + window.pageYOffset - 80;
            window.scrollTo({ top: offsetPosition, behavior: 'smooth' });
        });
    });
}

// ============================================
// 按钮涟漪效果
// ============================================
function initButtonFeedback() {
    document.addEventListener('click', function(e) {
        var button = e.target.closest('.btn-primary, .btn-secondary, .btn-danger, .btn-danger-outline');
        if (!button) return;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        var ripple = document.createElement('span');
        var rect = button.getBoundingClientRect();
        var size = Math.max(rect.width, rect.height);

        ripple.style.cssText = 'position:absolute;border-radius:50%;background:rgba(255,255,255,0.25);transform:scale(0);animation:ripple 0.6s ease-out;pointer-events:none;z-index:10;width:' + size + 'px;height:' + size + 'px;left:' + (e.clientX - rect.left - size / 2) + 'px;top:' + (e.clientY - rect.top - size / 2) + 'px';

        button.appendChild(ripple);
        setTimeout(function() { ripple.remove(); }, 600);
    });
}

// ============================================
// 鼠标跟随光晕
// ============================================
function initMouseGlow() {
    var glow = document.getElementById('mouse-glow');
    if (!glow) return;

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        glow.style.display = 'none';
        return;
    }

    if (window.matchMedia('(hover: none)').matches) {
        document.addEventListener('touchmove', function(e) {
            if (e.touches.length > 0) {
                var t = e.touches[0];
                glow.style.transform = 'translate3d(' + (t.clientX - 250) + 'px, ' + (t.clientY - 250) + 'px, 0)';
            }
        }, { passive: true });
        return;
    }

    var targetX = -250, targetY = -250;
    var currentX = -250, currentY = -250;
    var rafId = null;

    document.addEventListener('mousemove', function(e) {
        targetX = e.clientX - 250;
        targetY = e.clientY - 250;
        if (!rafId) rafId = requestAnimationFrame(updateGlow);
    }, { passive: true });

    function updateGlow() {
        currentX += (targetX - currentX) * 0.12;
        currentY += (targetY - currentY) * 0.12;

        glow.style.transform = 'translate3d(' + currentX + 'px, ' + currentY + 'px, 0)';

        var diff = Math.abs(targetX - currentX) + Math.abs(targetY - currentY);
        if (diff > 0.5) {
            rafId = requestAnimationFrame(updateGlow);
        } else {
            currentX = targetX;
            currentY = targetY;
            glow.style.transform = 'translate3d(' + currentX + 'px, ' + currentY + 'px, 0)';
            rafId = null;
        }
    }
}

// ============================================
// 高级动画：滚动进度条
// ============================================
function initScrollProgress() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var bar = document.createElement('div');
    bar.className = 'scroll-progress';
    document.body.appendChild(bar);

    var ticking = false;
    function updateProgress() {
        var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        var docHeight = Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight,
            document.body.offsetHeight,
            document.documentElement.offsetHeight,
            document.body.clientHeight,
            document.documentElement.clientHeight
        );
        var winHeight = window.innerHeight;
        var scrollPercent = (scrollTop / (docHeight - winHeight)) * 100;
        bar.style.width = scrollPercent + '%';
        ticking = false;
    }

    window.addEventListener('scroll', function() {
        if (!ticking) {
            requestAnimationFrame(updateProgress);
            ticking = true;
        }
    }, { passive: true });

    // 初始更新
    updateProgress();
}

// ============================================
// 高级动画：卡片交错出现
// ============================================
function initStaggerReveal() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        document.querySelectorAll('.stagger-item').forEach(function(el) {
            el.classList.add('visible');
        });
        return;
    }

    var observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                var delay = parseFloat(entry.target.getAttribute('data-stagger-delay')) || 0;
                setTimeout(function() {
                    entry.target.classList.add('visible');
                }, delay * 1000);
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.05, rootMargin: '0px 0px -20px 0px' });

    document.querySelectorAll('.stagger-item').forEach(function(el) {
        observer.observe(el);
    });
}

// ============================================
// 高级动画：文字逐词揭示
// ============================================
function initTextReveal() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        document.querySelectorAll('.text-reveal').forEach(function(el) {
            el.classList.add('visible');
        });
        document.querySelectorAll('.text-reveal-word').forEach(function(el) {
            el.classList.add('visible');
        });
        return;
    }

    // 处理 .text-reveal 块级元素（整体淡入）
    var revealObserver = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                revealObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.2 });

    document.querySelectorAll('.text-reveal').forEach(function(el) {
        revealObserver.observe(el);
    });

    // 处理 .text-reveal-word 逐词揭示
    var wordObserver = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                var words = entry.target.querySelectorAll('.text-reveal-word');
                words.forEach(function(word, index) {
                    setTimeout(function() {
                        word.classList.add('visible');
                    }, index * 60);
                });
                wordObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.2 });

    document.querySelectorAll('.text-reveal-container').forEach(function(el) {
        wordObserver.observe(el);
    });
}

// ============================================
// 高级动画：3D 卡片倾斜
// ============================================
function initCardTilt() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (window.matchMedia('(hover: none)').matches) return;

    document.querySelectorAll('.tilt-card').forEach(function(card) {
        var container = card.closest('.tilt-container') || card.parentElement;
        var shine = card.querySelector('.tilt-shine');
        if (!shine) {
            shine = document.createElement('div');
            shine.className = 'tilt-shine';
            card.appendChild(shine);
        }

        card.addEventListener('mousemove', function(e) {
            var rect = card.getBoundingClientRect();
            var x = e.clientX - rect.left;
            var y = e.clientY - rect.top;

            var centerX = rect.width / 2;
            var centerY = rect.height / 2;

            var rotateX = ((y - centerY) / centerY) * -6;
            var rotateY = ((x - centerX) / centerX) * 6;

            card.style.transform = 'perspective(800px) rotateX(' + rotateX + 'deg) rotateY(' + rotateY + 'deg) scale3d(1.02, 1.02, 1.02)';

            // 光晕跟随
            var pctX = (x / rect.width) * 100;
            var pctY = (y / rect.height) * 100;
            shine.style.background = 'radial-gradient(circle at ' + pctX + '% ' + pctY + '%, rgba(255,255,255,0.1), transparent 60%)';
            shine.style.opacity = '1';
        });

        card.addEventListener('mouseleave', function() {
            card.style.transform = '';
            shine.style.opacity = '0';
        });
    });
}

// ============================================
// 高级动画：视差滚动
// ============================================
function initParallax() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var layers = [];
    document.querySelectorAll('.parallax-layer').forEach(function(el) {
        var speed = parseFloat(el.getAttribute('data-parallax-speed')) || 0.1;
        layers.push({ el: el, speed: speed, top: 0 });
    });

    if (layers.length === 0) return;

    var ticking = false;
    function updateParallax() {
        var scrollY = window.pageYOffset;
        var winHeight = window.innerHeight;

        layers.forEach(function(layer) {
            var rect = layer.el.getBoundingClientRect();
            var elCenter = rect.top + rect.height / 2;
            var viewCenter = winHeight / 2;
            var offset = (elCenter - viewCenter) * layer.speed;

            layer.el.style.transform = 'translate3d(0, ' + (offset * -1) + 'px, 0)';
        });

        ticking = false;
    }

    window.addEventListener('scroll', function() {
        if (!ticking) {
            requestAnimationFrame(updateParallax);
            ticking = true;
        }
    }, { passive: true });

    updateParallax();
}

// ============================================
// 高级动画：悬浮粒子背景
// ============================================
function initParticles() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var container = document.querySelector('.particle-container');
    if (container) return; // 已经存在

    // 只在非移动设备上启用粒子
    if (window.innerWidth < 768) return;

    container = document.createElement('div');
    container.className = 'particle-container';
    document.body.appendChild(container);

    var count = Math.min(Math.floor(window.innerWidth / 40), 30);
    var particles = [];
    var rafId = null;

    for (var i = 0; i < count; i++) {
        var p = document.createElement('div');
        p.className = 'particle';
        var size = 1.5 + Math.random() * 2.5;
        p.style.width = size + 'px';
        p.style.height = size + 'px';
        p.style.opacity = 0.1 + Math.random() * 0.3;
        p.style.left = Math.random() * 100 + '%';
        p.style.top = Math.random() * 100 + '%';

        container.appendChild(p);

        particles.push({
            el: p,
            x: Math.random() * 100,
            y: Math.random() * 100,
            vx: (Math.random() - 0.5) * 0.15,
            vy: (Math.random() - 0.5) * 0.15 - 0.04
        });
    }

    function animateParticles() {
        particles.forEach(function(p) {
            p.x += p.vx;
            p.y += p.vy;

            if (p.x < 0 || p.x > 100) p.vx *= -1;
            if (p.y < 0 || p.y > 100) p.vy *= -1;

            p.el.style.transform = 'translate3d(' + p.x + 'vw, ' + p.y + 'vh, 0)';
        });

        rafId = requestAnimationFrame(animateParticles);
    }

    // 延迟启动，避免影响页面初始渲染
    setTimeout(function() {
        animateParticles();
    }, 1000);
}