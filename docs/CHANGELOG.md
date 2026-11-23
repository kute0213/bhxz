# 更新日志

> 历史版本已归档至 [CHANGELOG_ARCHIVE_2026-11-22.md](CHANGELOG_ARCHIVE_2026-11-22.md)。

## [Unreleased]

### 新增

* **音频上传支持 MP4**（`config.py`、`services/music/upload/`、`static/templates/music/upload.html`）：大喇叭音频允许上传 `.mp4`，ffmpeg 通过 `-map 0:a` 自动提取音轨并转码为 HLS 与唱片 MP3，原始视频文件在转码完成后删除。

### 修复

* **操作后页面元素不自动刷新**（`static/js/core/base.js` 及各页面模板）：
  * 新增统一的 `window.registerPageRefresh(fn)` / `window.refreshPageData()` 机制，通用 `admin-action` 处理器在操作成功后自动调用页面注册的刷新函数。
  * 管理后台用户、指南、音频、背景、建筑、游戏账号、封禁、假人、直播、防火墙、IndexNow、广播、自动维护、系统设置等页面，操作完成后通过既有 API 重新拉取数据并同步列表、计数、徽章、空状态与统计卡片；日志页继续由 SSE 实时推送。
  * 修改用户名 / 上传或删除头像后，同步更新全站头部用户名与头像，无需刷新页面。
* **首页底部「加入我们」按钮**（`static/templates/index.html`）：恢复为两个并排的大按钮，统一高度与内边距，窄屏自动换行 / 纵向排列。

### 移除

* **服务器指南封面字段**（`core/db/schema.py`、`routes/admin/guides/`、`routes/guides/pages/`、`static/templates/admin/guide_form.html`）：删除 `cover_image` 字段及管理后台表单中的「封面图片 URL」输入项，创建 / 编辑 / 替换草稿不再写入封面。

### 文档

* **文档体系重构**：
  * 精简重写 `README.md`，收敛为项目总览、快速开始、目录结构、功能、配置、API 概览与架构。
  * 精简重写 `docs/DEVELOPMENT.md`，保留分层、编码、模板、测试、构建发布与易错点规范，删除过时与重复内容。
  * 新增 `docs/API.md`，逐接口记录方法、鉴权、请求字段、响应字段、错误码、限流 / CSRF 规则与所属路由文件。
  * 旧更新日志完整归档至 `docs/CHANGELOG_ARCHIVE_2026-11-22.md`，当前文件重置为增量记录。
