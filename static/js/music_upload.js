/* 大喇叭音频上传页：表单校验、双阶段详细进度条。
 *
 * 流程：
 *   1. 提交表单 → XMLHttpRequest 上传文件（阶段一：文件上传进度条）
 *   2. 上传完成返回 task_id → 轮询 /music/upload/progress/<task_id>
 *      （阶段二：ffmpeg 转码进度条）
 *   3. status=done 展示成功卡片，status=error 展示失败卡片
 *
 * 依赖：base.js（Toast）、Lucide（图标）
 */
(function () {
    var form = document.getElementById('upload-form');
    if (!form) return;

    var card = document.getElementById('upload-card');
    var progressCard = document.getElementById('progress-card');
    var successCard = document.getElementById('success-card');
    var errorCard = document.getElementById('error-card');

    var progressIcon = document.getElementById('progress-icon');
    var progressTitle = document.getElementById('progress-title');

    var uploadPhase = document.getElementById('upload-phase');
    var transcodePhase = document.getElementById('transcode-phase');
    var transcodeStatus = document.getElementById('transcode-status');

    var uploadBar = document.getElementById('upload-bar');
    var uploadPercentText = document.getElementById('upload-percent-text');
    var transcodeBar = document.getElementById('transcode-bar');
    var transcodePercentText = document.getElementById('transcode-percent-text');

    var submitBtn = document.getElementById('submit-btn');
    var hint = document.getElementById('progress-hint');

    var pollTimer = null;
    var uploading = false;

    // ------------------------------------------------------------------
    // 页面状态切换
    // ------------------------------------------------------------------
    function hideAll() {
        progressCard.classList.add('hidden');
        successCard.classList.add('hidden');
        errorCard.classList.add('hidden');
    }

    function showProgress() {
        hideAll();
        progressCard.classList.remove('hidden');
        uploadPhase.classList.remove('hidden');
        transcodePhase.classList.add('hidden');
        uploadBar.style.width = '0%';
        uploadPercentText.textContent = '0%';
        transcodeBar.style.width = '0%';
        transcodeBar.classList.remove('is-indeterminate');
        transcodePercentText.textContent = '0%';
        transcodeStatus.textContent = '正在准备转码…';
        if (hint) hint.textContent = '';
        progressIcon.classList.add('animate-spin');
        progressTitle.textContent = '正在上传…';
    }

    function showTranscode(message) {
        uploadPhase.classList.add('hidden');
        transcodePhase.classList.remove('hidden');
        uploadBar.style.width = '100%';
        uploadPercentText.textContent = '100%';
        progressTitle.textContent = '正在转码…';
        // 尚未有真实百分比时显示不确定态动画进度条，避免「只有文字没有进度条」
        transcodeBar.classList.add('is-indeterminate');
        transcodeStatus.textContent = message || '正在准备转码…';
    }

    function showSuccess(musicId, title, isPublic) {
        stopPolling();
        hideAll();
        successCard.classList.remove('hidden');
        var link = location.origin + '/music/' + musicId + '.m3u8';
        document.getElementById('success-title').textContent = '上传成功！';
        var desc = document.getElementById('success-desc');
        var stateText = isPublic ? '等待管理员审核' : '私有（仅自己可见）';
        desc.textContent = '音频「' + title + '」已上传并转码完成，当前状态：' + stateText + '。';
        var copyBtn = document.getElementById('copy-link-btn');
        if (copyBtn) copyBtn.setAttribute('data-url', link);
        refreshIcons();
        if (typeof Toast !== 'undefined') Toast.success('音频上传成功');
    }

    function showError(message) {
        stopPolling();
        hideAll();
        errorCard.classList.remove('hidden');
        document.getElementById('error-desc').textContent = message || '上传失败，请稍后重试';
        refreshIcons();
    }

    function setBusy(busy) {
        uploading = busy;
        if (submitBtn) {
            submitBtn.disabled = busy;
            submitBtn.style.opacity = busy ? '0.6' : '';
        }
        form.querySelectorAll('input').forEach(function (input) {
            input.disabled = busy;
        });
        if (busy && card) card.classList.add('opacity-60', 'pointer-events-none');
        if (!busy && card) card.classList.remove('opacity-60', 'pointer-events-none');
    }

    // ------------------------------------------------------------------
    // 转码进度轮询
    // ------------------------------------------------------------------
    function pollProgress(taskId) {
        stopPolling();
        pollTimer = setInterval(function () {
            fetch('/music/upload/progress/' + encodeURIComponent(taskId))
                .then(function (res) { return res.json(); })
                .then(function (task) {
                    if (!task) { showError('任务不存在或已过期'); return; }
                    if (task.status === 'error') {
                        showError(task.error || task.message || '转码失败');
                        return;
                    }
                    if (task.status === 'done') {
                        showTranscode('转码完成');
                        transcodeBar.style.width = '100%';
                        transcodePercentText.textContent = '100%';
                        showSuccess(task.music_id, task.title || '', task.status === 'done');
                        return;
                    }
                    // transcoding：有真实百分比后切换为精确进度
                    transcodeBar.classList.remove('is-indeterminate');
                    var percent = Math.min(99, Math.max(0, task.percent || 0));
                    transcodeBar.style.width = percent + '%';
                    transcodePercentText.textContent = Math.round(percent) + '%';
                    transcodeStatus.textContent = task.message || ('正在转码… ' + Math.round(percent) + '%');
                })
                .catch(function () {
                    showError('网络异常，无法获取转码进度，请前往「我的音频」查看结果');
                });
        }, 1000);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    // ------------------------------------------------------------------
    // 提交上传
    // ------------------------------------------------------------------
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (uploading) return;

        var fileInput = document.getElementById('file-input');
        var titleInput = document.getElementById('title-input');
        if (!fileInput || !fileInput.files || !fileInput.files.length) {
            if (typeof Toast !== 'undefined') Toast.warning('请选择要上传的音频文件');
            return;
        }
        if (!titleInput.value.trim()) {
            if (typeof Toast !== 'undefined') Toast.warning('请填写音频名称');
            titleInput.focus();
            return;
        }

        setBusy(true);
        showProgress();

        var formData = new FormData();
        formData.append('title', titleInput.value.trim());
        formData.append('audio_file', fileInput.files[0]);
        var isPublicEl = document.getElementById('is-public-input');
        if (isPublicEl && isPublicEl.checked) formData.append('is_public', '1');

        var xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', function (ev) {
            if (!ev.lengthComputable) return;
            var pct = Math.round((ev.loaded / ev.total) * 100);
            uploadBar.style.width = pct + '%';
            uploadPercentText.textContent = pct + '%';
            if (pct >= 100) {
                progressTitle.textContent = '上传完成，等待转码…';
                if (hint) hint.textContent = '文件已上传，正在进入 ffmpeg 转码阶段…';
            }
        });

        xhr.addEventListener('load', function () {
            var data = null;
            try { data = JSON.parse(xhr.responseText); } catch (_) {}
            if (xhr.status === 200 && data && data.task_id) {
                showTranscode('正在准备转码…');
                pollProgress(data.task_id);
            } else {
                setBusy(false);
                showError((data && data.error) || '上传失败，请稍后重试');
            }
        });

        xhr.addEventListener('error', function () {
            setBusy(false);
            showError('网络异常，上传失败，请稍后重试');
        });
        xhr.addEventListener('abort', function () {
            setBusy(false);
            showError('上传已取消');
        });

        xhr.open('POST', '/music/upload', true);
        xhr.send(formData);
    });

    // ------------------------------------------------------------------
    // 成功卡片按钮：复制链接 / 再传一个；失败卡片：重新上传
    // ------------------------------------------------------------------
    var copyLinkBtn = document.getElementById('copy-link-btn');
    if (copyLinkBtn) {
        copyLinkBtn.addEventListener('click', function () {
            var url = copyLinkBtn.getAttribute('data-url') || '';
            if (!url) return;
            function done(ok) {
                if (typeof Toast !== 'undefined') {
                    if (ok) Toast.success('播放链接已复制'); else Toast.error('复制失败，请手动复制');
                }
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(url).then(function () { done(true); }, function () { done(false); });
            } else {
                var ta = document.createElement('textarea');
                ta.value = url;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                try { done(document.execCommand('copy')); } catch (_) { done(false); }
                document.body.removeChild(ta);
            }
        });
    }

    function resetForm() {
        hideAll();
        setBusy(false);
        form.reset();
        refreshIcons();
    }

    var uploadAnotherBtn = document.getElementById('upload-another-btn');
    if (uploadAnotherBtn) uploadAnotherBtn.addEventListener('click', resetForm);

    var retryBtn = document.getElementById('error-retry-btn');
    if (retryBtn) retryBtn.addEventListener('click', function () {
        hideAll();
        setBusy(false);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // ------------------------------------------------------------------
    // 辅助：重新渲染图标
    // ------------------------------------------------------------------
    function refreshIcons() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons(); } catch (_) {}
        }
    }
})();
