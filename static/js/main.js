document.addEventListener('DOMContentLoaded', function() {
    if (window.__animationsInitialized) return;
    window.__animationsInitialized = true;

    initScrollAnimations();
    initSmoothScroll();
    initButtonFeedback();
    initMouseGlow();
});

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
    var lastMoveTime = 0;

    document.addEventListener('mousemove', function(e) {
        targetX = e.clientX - 250;
        targetY = e.clientY - 250;
        lastMoveTime = Date.now();
        if (!rafId) rafId = requestAnimationFrame(updateGlow);
    }, { passive: true });

    function updateGlow() {
        currentX += (targetX - currentX) * 0.12;
        currentY += (targetY - currentY) * 0.12;

        var diff = Math.abs(targetX - currentX) + Math.abs(targetY - currentY);
        glow.style.transform = 'translate3d(' + currentX + 'px, ' + currentY + 'px, 0)';

        if (diff > 0.5) {
            rafId = requestAnimationFrame(updateGlow);
        } else {
            rafId = null;
        }
    }
}
