/**
 * 自研日历选择器
 *
 * 用法：页面引入 macros/calendar.html 的 calendar_field()，并在 extra_script 中调用
 * calendar_script() 加载本文件。组件自动初始化所有 [data-calendar] 容器。
 *
 * 支持两种模式：
 *   data-mode="date"      → 隐藏域值为 YYYY-MM-DD
 *   data-mode="datetime"  → 隐藏域值为 YYYY-MM-DDTHH:MM
 *
 * 弹层挂载到 body（position: fixed），避免被 .pixel-card 的
 * content-visibility / contain / backdrop-filter 裁剪。
 */
(function () {
    'use strict';

    var WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日'];
    var instances = [];
    var currentOpen = null;

    function pad(n) {
        return String(n).padStart(2, '0');
    }

    function pad2Or(value, min, max, fallback) {
        var n = parseInt(value, 10);
        if (isNaN(n)) return fallback;
        return Math.min(max, Math.max(min, n));
    }

    function sameDay(a, b) {
        return a.getFullYear() === b.getFullYear()
            && a.getMonth() === b.getMonth()
            && a.getDate() === b.getDate();
    }

    function todayDate() {
        var now = new Date();
        return new Date(now.getFullYear(), now.getMonth(), now.getDate());
    }

    function isoDate(d) {
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }

    function parseValue(raw) {
        if (!raw) return null;
        var m = String(raw).trim().match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
        if (!m) return null;
        var d = new Date(
            parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10),
            m[4] ? parseInt(m[4], 10) : 0,
            m[5] ? parseInt(m[5], 10) : 0,
            0, 0
        );
        return isNaN(d.getTime()) ? null : d;
    }

    function initField(field) {
        var mode = field.getAttribute('data-mode') === 'datetime' ? 'datetime' : 'date';
        var trigger = field.querySelector('.calendar-trigger');
        var textEl = field.querySelector('.calendar-value-text');
        var hidden = field.querySelector('input[type="hidden"]');
        var pop = field.querySelector('.calendar-popover');
        if (!trigger || !textEl || !hidden || !pop) return;

        // 移动到 body，彻底避免被卡片/弹窗的裁剪与层叠上下文影响
        document.body.appendChild(pop);

        var titleEl = pop.querySelector('[data-cal-title]');
        var gridEl = pop.querySelector('[data-cal-grid]');
        var timeRow = pop.querySelector('[data-cal-time]');
        var hourEl = pop.querySelector('[data-cal-hour]');
        var minuteEl = pop.querySelector('[data-cal-minute]');

        var state = {
            open: false,
            view: null,
            selected: null,
        };

        function displayText() {
            if (!state.selected) return '';
            var datePart = isoDate(state.selected);
            if (mode === 'datetime') {
                return datePart + ' ' + pad(state.selected.getHours()) + ':' + pad(state.selected.getMinutes());
            }
            return datePart;
        }

        function syncText() {
            var text = displayText();
            if (text) {
                textEl.textContent = text;
                textEl.classList.remove('is-placeholder');
            } else {
                textEl.textContent = mode === 'datetime' ? '选择日期时间' : '选择日期';
                textEl.classList.add('is-placeholder');
            }
        }

        function commit() {
            if (!state.selected) {
                hidden.value = '';
            } else if (mode === 'datetime') {
                hidden.value = isoDate(state.selected) + 'T'
                    + pad(state.selected.getHours()) + ':' + pad(state.selected.getMinutes());
            } else {
                hidden.value = isoDate(state.selected);
            }
            syncText();
        }

        function readTimeInputs() {
            var h = pad2Or(hourEl.value, 0, 23, 0);
            var m = pad2Or(minuteEl.value, 0, 59, 0);
            hourEl.value = pad(h);
            minuteEl.value = pad(m);
            return [h, m];
        }

        function render() {
            var y = state.view.getFullYear();
            var mth = state.view.getMonth();
            titleEl.textContent = y + '年' + (mth + 1) + '月';

            // 周一为每周第一天
            var offset = (new Date(y, mth, 1).getDay() + 6) % 7;
            var today = todayDate();
            gridEl.innerHTML = '';

            for (var i = 0; i < 42; i++) {
                var d = new Date(y, mth, 1 - offset + i);
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'calendar-day';
                btn.textContent = d.getDate();
                btn.setAttribute('data-date', isoDate(d));

                if (d.getMonth() !== mth) btn.classList.add('is-other');
                if (sameDay(d, today)) btn.classList.add('is-today');
                if (state.selected && sameDay(d, state.selected)) btn.classList.add('is-selected');

                btn.addEventListener('click', function () {
                    selectDay(this.getAttribute('data-date'));
                });
                gridEl.appendChild(btn);
            }
        }

        function selectDay(dateStr) {
            var parts = dateStr.split('-');
            var hour = mode === 'datetime' ? readTimeInputs()[0] : 0;
            var minute = mode === 'datetime' ? readTimeInputs()[1] : 0;
            state.selected = new Date(
                parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10),
                hour, minute, 0, 0
            );
            commit();
            render();
            if (mode === 'date') close();
        }

        function position() {
            var r = trigger.getBoundingClientRect();
            var w = pop.offsetWidth || 288;
            var h = pop.offsetHeight || 360;
            var gap = 8;
            var left = Math.min(Math.max(12, r.left), Math.max(12, window.innerWidth - w - 12));
            var top = r.bottom + gap;
            if (top + h > window.innerHeight - 12) {
                top = Math.max(12, r.top - h - gap);
            }
            pop.style.left = left + 'px';
            pop.style.top = top + 'px';
        }

        function open() {
            if (state.open) return;
            if (currentOpen && currentOpen !== api) currentOpen.close();

            var parsed = parseValue(hidden.value);
            if (parsed) {
                state.selected = parsed;
            } else {
                state.selected = mode === 'datetime' ? new Date() : todayDate();
            }
            state.view = new Date(state.selected.getFullYear(), state.selected.getMonth(), 1);

            if (mode === 'datetime') {
                hourEl.value = pad(state.selected.getHours());
                minuteEl.value = pad(state.selected.getMinutes());
            }

            pop.hidden = false;
            state.open = true;
            field.classList.add('is-open');
            trigger.setAttribute('aria-expanded', 'true');
            currentOpen = api;

            render();
            position();
        }

        function close() {
            if (!state.open) return;
            state.open = false;
            pop.hidden = true;
            field.classList.remove('is-open');
            trigger.setAttribute('aria-expanded', 'false');
            if (currentOpen === api) currentOpen = null;
        }

        var api = {
            field: field,
            pop: pop,
            close: close,
            position: position,
            contains: function (node) {
                return field.contains(node) || pop.contains(node);
            },
        };

        trigger.addEventListener('click', function (e) {
            e.stopPropagation();
            if (state.open) close(); else open();
        });

        pop.querySelector('[data-cal-prev]').addEventListener('click', function () {
            state.view = new Date(state.view.getFullYear(), state.view.getMonth() - 1, 1);
            render();
            position();
        });

        pop.querySelector('[data-cal-next]').addEventListener('click', function () {
            state.view = new Date(state.view.getFullYear(), state.view.getMonth() + 1, 1);
            render();
            position();
        });

        var todayBtn = pop.querySelector('[data-cal-today]');
        if (todayBtn) {
            todayBtn.addEventListener('click', function () {
                var now = new Date();
                if (mode === 'datetime') {
                    state.selected = now;
                    hourEl.value = pad(now.getHours());
                    minuteEl.value = pad(now.getMinutes());
                } else {
                    state.selected = todayDate();
                }
                state.view = new Date(state.selected.getFullYear(), state.selected.getMonth(), 1);
                commit();
                render();
                if (mode === 'date') close(); else position();
            });
        }

        var clearBtn = pop.querySelector('[data-cal-clear]');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                state.selected = null;
                hidden.value = '';
                syncText();
                close();
            });
        }

        var applyBtn = pop.querySelector('[data-cal-apply]');
        if (applyBtn) {
            applyBtn.addEventListener('click', function () {
                if (mode === 'datetime' && state.selected) {
                    var hm = readTimeInputs();
                    state.selected.setHours(hm[0], hm[1], 0, 0);
                }
                commit();
                close();
            });
        }

        if (mode === 'datetime') {
            timeRow.hidden = false;
            [hourEl, minuteEl].forEach(function (el) {
                el.addEventListener('change', function () {
                    if (!state.selected) state.selected = todayDate();
                    var hm = readTimeInputs();
                    state.selected.setHours(hm[0], hm[1], 0, 0);
                    commit();
                });
                el.addEventListener('blur', function () {
                    if (!state.selected) state.selected = todayDate();
                    var hm = readTimeInputs();
                    state.selected.setHours(hm[0], hm[1], 0, 0);
                    commit();
                });
                el.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        applyBtn.click();
                    }
                });
            });
        } else {
            timeRow.hidden = true;
        }

        // 初始化显示
        state.selected = parseValue(hidden.value);
        if (state.selected && mode === 'date') {
            state.selected.setHours(0, 0, 0, 0);
        }
        syncText();

        instances.push(api);
    }

    function closeAll() {
        instances.forEach(function (it) { it.close(); });
    }

    document.addEventListener('mousedown', function (e) {
        if (!currentOpen) return;
        if (currentOpen.contains(e.target)) return;
        currentOpen.close();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && currentOpen) currentOpen.close();
    });

    window.addEventListener('scroll', function () {
        if (currentOpen) currentOpen.position();
    }, true);

    window.addEventListener('resize', function () {
        if (currentOpen) currentOpen.position();
    });

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-calendar]').forEach(initField);
    });

    // 兼容脚本在 DOMContentLoaded 之后加载的情况
    if (document.readyState !== 'loading') {
        document.querySelectorAll('[data-calendar]').forEach(initField);
    }

    // 暴露少量调试接口（可选）
    window.CalendarPicker = { closeAll: closeAll };
})();
