# 更新日志

本文件记录滨海小镇官网项目的所有重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

### 修复
- **简化图形验证码难度 + 群内验证码改为弹窗模式**：
  - `services/captcha.py`：验证码从两位数加法 (10-99) 改为个位数加法 (1-9)，答案范围 2-18；减少干扰线条数 (6→3) 和干扰点数 (120→60)；增大字体 (18→22px)，文字颜色更深、干扰颜色更浅
  - `templates/register.html`：调整表单顺序，图形验证码移到邮箱验证码上方
  - `templates/register.html`：群内验证码改为弹窗模式，打开注册页即弹出要求输入，验证正确后才显示注册表单
  - `routes/main.py`：新增 `/api/verify-group-code` 和 `/api/verify-group-code/check` AJAX 接口，验证结果存入 session
  - `routes/main.py`：注册路由改为检查 session 中的群内验证码标记，不再依赖表单字段

- **修复广播邮件发送返回 "Unexpected token '<'" 错误**：
  - 根因：`/admin/broadcast/send` 等 AJAX 路由使用 `@login_required` 装饰器，session 过期或权限不足时返回 302 HTML 重定向，前端 `fetch().json()` 解析 HTML 遇到 `<` 字符报错
  - `core/auth.py` 新增 `admin_required` 装饰器：对 JSON/AJAX 请求返回 JSON 401/403（而非 HTML 重定向）
  - `core/auth.py` 优化 `login_required`：同样对 JSON/AJAX 请求返回 JSON 401，避免其他 AJAX 接口出现同类问题
  - `core/auth.py` 新增 `_is_json_request()` 辅助函数：检测 `Accept`/`Content-Type`/`X-Requested-With` 头
  - `routes/admin/broadcast.py` 三个路由改用 `@admin_required`，移除手动权限检查，代码更简洁
  - `templates/admin_broadcast.html` 所有 fetch 调用添加 `Accept: application/json` 请求头，并对非 200 响应做降级处理

### 新增
- **管理员广播邮件功能**：
  - 新增 `routes/admin/broadcast.py`：广播邮件路由（页面 + 发送 API + 历史日志 API），POST `/admin/broadcast/send` 接收 JSON 并异步发送
  - 新增 `templates/admin_broadcast.html`：Markdown 编辑器 + 实时预览（marked.js 渲染）+ 发送确认弹窗 + 广播历史记录
  - `services/email_templates.py` 新增 `broadcast_message()` 函数：将 Markdown 转为 HTML 构建广播邮件
  - `services/email_templates.py` 新增 Markdown 内容样式（`.mail-content`）：标题、列表、引用块、代码块、表格、图片等元素适配邮件暗色主题 + 移动端响应式
  - `core/db/schema.py` 新增 `broadcast_logs` 表：记录每次广播的发送者、主题、内容、接收人数和时间
  - 发送流程：管理员勾选二次确认 → 验证邮件服务启用 → 构建 HTML 模板 → 异步批量发送 → 记录日志
  - 支持 Markdown 全部常用语法：标题、加粗、列表、引用、代码块、表格、链接、图片
  - 广播标题自动添加 `[广播]` 前缀，接收人能一眼识别
- **统一邮件 HTML 模板模块**：
  - 新增 `services/email_templates.py`：集中构建所有邮件 HTML，消除散落在 3 个文件中的重复模板代码
  - 提取公共组件：外层容器 `_wrap()`、高亮块 `_highlight_block()`、验证码大号块 `_code_block()`、次要提示 `_muted()`
  - 三个对外构建函数：`verification_code()`（验证码邮件）、`guide_review_pending()`（新指南待审核通知）、`guide_review_result()`（审核结果通知）
  - 顶部内联 `<style>` 含 `@media (max-width: 480px)` 媒体查询：移动端自适应缩小验证码字号（32px→26px）、字间距（8px→4px）、内边距，避免横向溢出
  - 容器 `max-width: 480px` + `width: 100%` + `box-sizing: border-box`，适配任意屏幕宽度
  - 所有用户输入内容（验证码、指南标题、用户名、拒绝原因）经 `html.escape()` 转义，防止 XSS 注入
  - 配色与网站整体风格一致：金黄主色 `#f4d03f` + 暗绿背景 `#1a2a1a` + 成功绿/失败红语义色
  - `requirements.txt` 新增 `pygments` 依赖：为 `codehilite` 扩展提供代码块语法高亮，避免降级丢失表格/代码块扩展
- **验证码功能**：
  - 新增 `services/captcha.py`：生成带随机干扰线和干扰点的数学题验证码图片（base64 编码，不保存文件）
  - 新增 `routes/api/captcha.py`：验证码生成 API `/api/captcha/generate`
  - 登录和注册页面添加验证码输入框，点击图片可刷新
  - 后端严格校验验证码（答案存储在 session 中，一次性使用后立即清除）
  - 延迟加载 Pillow 库，避免不必要的依赖检查开销
- **统一网页弹窗系统**：
  - 新增 `CustomModal` 弹窗组件：放大居中动画，支持触发元素位置感知
  - 新增 `Toast` 提示组件：成功/错误/警告/信息四种类型
  - `base.js` 新增 `initCustomConfirm`：自动拦截 `form[onsubmit*="confirm("]` 与 `a[onclick*="confirm("]`，统一替换为自定义弹窗
  - `base.js` 新增附件上传进度条（XHR + `progress` 事件）
  - 所有页面已替换浏览器原生 `alert`/`confirm` 为统一的网页弹窗，符合磨砂玻璃整体风格
- **服务器指南系统**：
  - 新增 `server_guides` 表：存储指南标题、slug、摘要、Markdown 内容、审核状态、作者、置顶与排序
  - 新增 `guide_edit_bans` 表：记录用户/IP 的编辑权限封禁，支持限时或永久封禁
  - 公开页面：`/guides` 卡片式列表页（支持 `?my=1` 查看我的指南）、`/guides/<slug>` Markdown 详情页（标题锚点、代码高亮）
  - 成员 API：`POST /api/guides/submit` 提交新指南、`POST /api/guides/<id>/edit-request` 提交编辑请求、`GET /api/guides/my` 获取我的指南，均需登录，提交后进入 `pending` 待审核状态
  - 管理后台：专业 Markdown 编辑器（分栏实时预览）、审核工作流（通过/拒绝附原因）、置顶与排序控制
  - 封禁管理：`/admin/guide-bans` 按用户名或 IP 封禁/解封，后端 `_is_banned()` 实时校验
  - 前端使用 `marked.js` 渲染 Markdown，支持标题自动生成锚点链接
  - 蓝图拆分：`routes/guides/`（公开页面 + 成员 API）、`routes/admin/guides.py` + `guide_bans.py`（管理后台）

### 重构
- **前端移动端适配补强**：
  - `templates/community.html`：投票/留言板区域标题行 `flex items-center justify-between` → `flex flex-wrap items-center justify-between gap-3`，移动端长标题不再挤压按钮
  - `templates/community.html`：回复列表头像区、投票页脚行添加 `flex-wrap` + `gap-2`
  - `templates/community.html`：投票/留言板标题添加 `break-words`，留言内容添加 `break-all`，防止长无空字符串横向溢出
  - `templates/community.html`：留言输入框 + 发送按钮容器添加 `flex-wrap` + `min-w-[200px]`
  - `templates/index.html`：模组介绍内容添加 `break-all`，防止长 URL/长英文串溢出
  - `templates/admin_users.html`：页头与表格行操作按钮添加 `flex-wrap`，用户名添加 `break-all`
  - `templates/admin_broadcast.html`：编辑器/预览头部添加 `flex-wrap` + `gap-2`
  - `templates/performance.html`：CPU/内存进度条卡片头部添加 `flex-wrap` + `gap-2`
  - `templates/settings.html`：用户名添加 `break-all`
- **后端认证架构优化**：
  - `core/auth.py` 新增 `hash_password()` / `verify_password()` 工具函数，统一密码哈希算法
  - `routes/main.py` 移除 5 处重复的 `hashlib.sha256(password.encode('utf-8')).hexdigest()`，改用 `hash_password()`，移除 `import hashlib`
  - `routes/admin/broadcast.py` 使用 `g._current_user` 避免重复查询，简化日志记录的连接管理（嵌套 try/finally）
- **前端移动端彻底适配**：
  - `templates/admin_settings.html`：内联 `style="width: 200px;"` / `style="width: 120px;"` 改为响应式 `w-full sm:w-48` / `w-full sm:w-32`，移动端输入框占满宽度，桌面端固定宽度
  - `templates/admin_settings.html`：设置项行布局从 `flex items-center` 改为 `flex flex-col sm:flex-row sm:items-center`，移动端纵向堆叠
  - `templates/admin_settings.html`：操作栏添加 `flex-wrap`，避免窄屏按钮挤压
  - `templates/admin_logs.html`：工具栏从 `flex items-center justify-between` 改为 `flex flex-col` + 内部 `flex-wrap`，移动端标题与操作行垂直排列
  - `templates/manage_mod_intros.html`：底部信息行添加 `truncate` + `min-w-0` + `flex-shrink-0`，避免长文本将删除按钮挤出可视区
  - `templates/community.html`：投票选项行添加 `truncate` + `flex-shrink-0`，防止长选项挤压百分比
  - 多处页面 H1 标题从 `text-2xl` / `text-3xl` 改为 `text-xl sm:text-2xl` / `text-2xl sm:text-3xl` 响应式变体（admin_db_backup、admin_logs、admin_settings、admin_users、register、login、settings、performance、manage_mod_intros）
  - `templates/admin.html`：统计卡片数字改为 `text-xl sm:text-2xl break-all`，防止大数字溢出
  - `templates/performance.html`：系统信息卡片从 `grid-cols-2` 改为 `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`，小屏单列
  - `templates/docs.html` / `templates/guides/detail.html`：`.prose-docs table` 添加 `display: block; overflow-x: auto; max-width: 100%;`，Markdown 表格在移动端可横向滚动
  - `templates/register.html` / `templates/login.html`：容器 `mx-6` → `mx-4 sm:mx-6`，内边距 `p-8` → `p-5 sm:p-8`
  - `templates/manage_mod_intros.html`：容器 `px-6` → `px-4 sm:px-6 lg:px-8`
  - `templates/index.html`：内联 `text-2xl` → `text-xl sm:text-2xl`
- **验证码服务内存清理机制**：
  - `services/captcha.py` `CaptchaService`：新增后台清理线程（每 60 秒清理一次过期验证码），避免内存泄漏
  - `services/email_code.py` `EmailCodeService`：新增后台清理线程（每 5 分钟清理一次过期验证码），避免内存泄漏
  - 两个服务的 docstring 完善安全特性说明（服务端内存存储、一次性删除防重放、过期时间、后台清理）
- **邮件 HTML 模板统一重构**：
  - `services/email_code.py`：验证码邮件 HTML 改用 `email_templates.verification_code()` 构建，移除硬编码 f-string 模板
  - `routes/guides/api.py`：指南待审核通知 HTML 改用 `email_templates.guide_review_pending()` 构建
  - `routes/admin/guides.py`：审核结果通知 HTML 改用 `email_templates.guide_review_result()` 构建，简化 `if/else` 分支为统一调用
  - 消除 3 个文件中重复的外层容器样式与高亮块样式，所有邮件 HTML 集中在 `services/email_templates.py` 维护

### 修复
- **替换 `admin_db_backup.html` 中内联 `confirm()`**：脚本块中的原生 `confirm('确定要删除此备份吗？此操作不可恢复。')` 替换为 `CustomModal.confirm()`，与全站统一弹窗风格保持一致（`initCustomConfirm` 仅拦截 `onsubmit`/`onclick` 属性，无法拦截脚本块内调用，故手动改写）

- **邮件发送与验证码相关修复**：
  - 修复 yagmail SMTP 连接参数错误：移除 `smtp_set_debug_level` 参数，避免 `SMTP_SSL.__init__() got an unexpected keyword argument` 错误
  - 修复邮箱验证码发送前需图形验证码验证：`POST /api/email/send-code` 新增 `captcha` 参数，后端校验图形验证码后才发送邮箱验证码，防止恶意刷短信
  - 注册页面和设置页面的邮箱验证码发送按钮增加图形验证码校验，发送失败时自动刷新图形验证码
  - 修复 DuckDB WAL 文件损坏导致启动失败：`get_db()` 捕获 `InternalException`，检测到 WAL 损坏时自动删除损坏的 WAL 文件并重试连接，输出恢复日志
  - 优化 `_is_mp_child_process()` 函数：移除冗余的环境变量重复设置，简化 frozen 分支判断逻辑

- **修复 Windows 终端输出重复问题**：
  - `services/terminal/session.py`：`read_pending_output` 增加 `caller_generation` 参数，旧 SSE 连接在 generation 切换后返回空列表且不再消费输出队列，避免同一段输出被多个连接重复发送
  - `services/terminal/session.py`：`next_generation()` 非首次切换时清空旧输出队列，防止重连时残留输出被新连接重复显示；首次连接（generation 从 0 到 1）保留会话初始化输出
  - `routes/cmd/terminal.py`：SSE 生成器将当前 generation 传入 `read_pending_output`，实现代际一致性校验
  - `static/js/cmd/terminal-core.js`：`SseTerminal` 新增 `_connecting` 锁，防止并发调用 `connect()` 产生多个 EventSource 连接
  - `core/shell.py`：Windows cmd 启动参数改为 `cmd.exe /q /k`，关闭命令回显，减少命令被前后端重复渲染的概率
- **修复留言板附件选择显示异常与多文件上传失效**：
  - `templates/community.html`：将内联 `onchange` 中的复杂 JavaScript 提取为 `updateFileList(input, listId)` 函数，避免 HTML 属性中 `"` 转义错误导致 `<input>` 标签提前关闭、按钮文本显示为 JS 代码碎片的问题
  - 前端使用 `DataTransfer` 累积历次选择的文件并写回 `input.files`，支持单次多选和多次点击“添加附件”追加文件，避免后一次选择覆盖前一次
  - 表单提交时所有累积文件通过 `FormData` 一并上传，后端 `request.files.getlist('attachments')` 遍历保存

### 重构
- **终端（CMD 命令提示符）与 MiniScript 彻底重构**：
  - 前端提取 `static/js/cmd/terminal-core.js`：统一 ANSI 解析、SSE 连接管理（含断线重连 / 心跳看门狗 / 待发送队列）、命令历史、输入发送，供 `terminal.js` 弹窗与 `editor-terminal.js` 内嵌终端复用
  - 后端拆分 `services/terminal/` 包：`TerminalSession` 封装单个持久 shell 会话的状态、IO 与生命周期；`TerminalManager` 按 Flask session 隔离管理多个 shell 进程，支持过期自动清理
  - MiniScript 改为 session-based 状态管理：新增 `services/miniscript/session.py`，`ScriptSessionManager` 按 Flask session 隔离 `ScriptExecutor` 与 prompt/confirm 响应事件，彻底解决多用户/多 worker 环境下响应串扰
  - 路由层瘦身：`routes/cmd/terminal.py` 与 `routes/cmd/script.py` 仅保留 HTTP/SSE 协议转换，所有子进程状态管理下沉到 `services/terminal/` 与 `services/miniscript/`
- **跨平台子进程工具统一迁移到 `core/`**：
  - 新增 `core/process_utils.py`：从原 `utils/process.py` 迁移并增强，提供跨平台编码解码（UTF-8/GBK/CP936/GB18030/MBCS）、无缓冲环境变量、`run_process` 统一封装
  - 新增 `core/process_manager.py`：统一处理 Windows `CREATE_NO_WINDOW` / `CREATE_NEW_PROCESS_GROUP` 与 Unix `setsid`、进程组 SIGTERM/SIGKILL、Windows `CTRL_BREAK_EVENT` 进程组信号、阶梯式终止
  - 新增 `core/shell.py`：自动检测 Windows cmd/PowerShell 与 Unix bash/sh，构造统一环境变量与初始化命令
  - 删除已废弃的 `utils/process.py` 与 `utils/__init__.py`

### 修复
- **彻底修复数据库备份失败（Windows 文件锁定）**：
  - `services/backup_manager.py`：将 `shutil.copy2` 文件复制替换为 DuckDB 在线备份 `ATTACH` + `COPY FROM DATABASE` + `DETACH`
  - 备份过程中数据库无需关闭，不影响正常读写，彻底解决 Windows `[WinError 32] 另一个程序正在使用此文件，进程无法访问` 错误
  - 动态查询 `duckdb_databases()` 获取当前数据库名（如 `site`），避免硬编码 `main` 导致的兼容性问题；数据库名使用双引号包裹，路径中的单引号转义，避免特殊字符导致 SQL 语法错误
  - 备份失败时自动清理残留临时文件
- **修复交互式终端 SSE 连接断开问题**：
  - 后端 `routes/cmd/terminal.py`：subprocess 改为二进制模式（`text=False`），避免 TextIOWrapper 内部缓冲与 `os.read` 混用导致数据丢失；`select.select` 改用文件描述符（`stdout.fileno()`）；stdin 写入前将 str 编码为 bytes
  - SSE 心跳从注释 `: ping` 改为 `data: {"type":"heartbeat","data":{}}` 事件，避免被部分代理/缓冲丢弃
  - SSE 生成器增加异常兜底（循环内 try/except + 最外层 try/except），避免异常冒泡导致连接意外关闭
  - 前端 `static/js/cmd/editor-terminal.js`：`onerror` 增加 3 秒延迟自动重连（主动关闭 EventSource 默认自动重连以避免冲突）；新增 `heartbeat` / `error` 事件处理；`init()` 监听页面可见性，切回页面时若已断开则立即重连

### 新增
- **留言板附件功能全面优化**：
  - `routes/community/board.py`：新增文件类型白名单（`png/jpg/jpeg/gif/webp/pdf/txt/zip/rar/7z/doc/docx/xls/xlsx/ppt/pptx/mp4/mp3/wav`）、数量限制（最多 5 个）、大小限制（单个 100MB）
  - 附件存储格式从纯文件名数组升级为 JSON 元信息数组（含 `filename`、`original_name`、`file_type`、`size_bytes`），向后兼容旧格式
  - `templates/community.html`：前端实时附件预览（图片缩略图/文件图标、文件名、大小）、实时校验（数量/类型/大小）、错误提示
  - 历史附件展示优化：按文件类型显示对应图标（图片、PDF、压缩包、音视频等）
- **交互式终端面板**：输出面板改造为完整终端，底部输入行支持直接执行 shell 命令（SSE 流式输出）
- **终端命令历史**：↑/↓ 切换历史命令，最多保存 100 条，localStorage 持久化
- **终端快捷键**：Ctrl+L 清屏、Ctrl+C 终止当前命令、Enter 执行
- **运行命令行显示**：运行脚本时终端顶部显示 `$ python <文件名>` 命令行
- **终端后端 API**：`POST /admin/cmd/terminal/run`（SSE 流式执行）、`POST /admin/cmd/terminal/abort`（终止命令）

### 重构
- **CmdModal 状态机 + 队列架构**：彻底重写弹窗系统，从根源解决连续弹窗闪退问题
  - 四态状态机：`closed → opening → open → closing → closed`，非法状态直接忽略
  - 调用队列：连续调用自动排队，上一个完全关闭后才显示下一个
  - 单一关闭入口：所有关闭路径都走 `resolveAndClose → doClose → finishClose`
  - 动画事件精确匹配：按 `animationName` 区分 enter/leave，避免事件串扰
  - 全局事件只绑定一次：ESC/Enter/背景点击等事件在 build() 时统一注册

### 变更
- 脚本编辑器输出面板标题从"输出"改为"终端"，配色改为紫色主题
- 终端面板宽度增加（桌面端 420px / 480px / 560px 三档）
- `editor.js` 的 `appendOutput` / `clearOutput` 优先使用 TerminalPanel，保持向后兼容
- `editor.js` 新增 `getCurrentFilename()` 公共 API

### 修复
- **彻底修复脚本无法保存**：根因是 CmdModal 单例连续弹窗时动画事件残留导致第二个弹窗被意外关闭。通过状态机+队列架构从根本上解决，而非临时补丁式修复

### 修复
- 修复 `/admin/logs` 页面 500 错误：模板中 `url_for('api.api_logs_refresh')` 端点名错误，实际蓝图名为 `api_admin`，改为 `url_for('api_admin.api_logs_refresh')`

### 新增
- 脚本自动保存：编辑已有脚本时防抖 2 秒自动保存，工具栏四态状态指示器（已修改/保存中/已保存/保存失败）
- 可折叠输出面板：编辑器输出区支持展开/收起，折叠状态 localStorage 记忆
- 脚本文件系统：MiniScript 脚本从数据库移到 `scripts/` 目录，每个脚本一个独立 `.py` 文件，文件头注释存储名称和描述元数据
- 脚本管理服务（`services/script_manager.py`）：增删改查、文件名安全检查、元数据解析
- 脚本文件 API（`/admin/cmd/scripts`）：列表、获取、保存、删除
- CMD 控制台首页分开展示「脚本」和「快捷命令」两个区块
- 定时任务从文件系统读取脚本内容执行，`command` 字段存储文件名
- 前端实时 Python 语法检查（`editor-highlight.js` 新增 `registerDiagnostics` / `checkPythonSyntax`）：检查括号匹配、缩进一致性、冒号缺失、续行符错误、未闭合字符串，编辑器内实时显示错误波浪线
- 定时任务「从快捷命令选择」功能：创建/编辑定时任务时可直接从已有快捷命令列表中选择，自动填充命令内容和任务类型
- 代码结构重组：6 个大文件拆分为包结构（`core/db/`、`services/monitoring/`、`routes/community/`、`routes/admin/`、`routes/cmd/`、`routes/scheduled/`）
- 前端模块化拆分：`base.html` 拆分为 `base.css` + `base.js`；`editor.js` 拆分为 `editor-highlight.js` + `editor-sse.js`；`scheduled.js` 拆分出 `scheduled-logs.js`

### 修复
- 修复编辑器保存弹窗闪退：`CmdModal` 单例连续弹窗时，旧 `close()` 的 300ms 超时 `setTimeout` 会隐藏新弹窗。新增 `closeTimer` 在 `show()` 时清除旧定时器

### 删除
- 脚本安全检测功能（`services/miniscript/sandbox.py` 及 `validate_script` 调用）
- 一次性迁移脚本 `migrate_scripts_to_files.py`、`migrate_sqlite_to_duckdb.py`
- 编辑器可折叠侧边栏（脚本文件列表），改为直接通过 URL `?file=xxx.py` 打开

### 变更
- 更新日志文件从项目根目录移至 `docs/CHANGELOG.md`

### 重构（代码结构优化）
- **`core/database.py`**(526行) → `core/db/` 包（`connection.py` + `schema.py`）
- **`services/monitoring.py`**(404行) → `services/monitoring/` 包（`cpu.py` + `memory.py` + `system.py`）
- **`routes/community.py`**(476行) → `routes/community/` 包（`pages` + `polls` + `board` + `helpers`）
- **`routes/admin.py`**(385行) → `routes/admin/` 包（`pages` + `users` + `mod_intros` + `logs` + `backup`）
- **`routes/cmd.py`**(383行) → `routes/cmd/` 包（`pages` + `commands` + `execution` + `script`）
- **`routes/scheduled.py`**(369行) → `routes/scheduled/` 包（`tasks` + `logs`）
- **`templates/base.html`**(1194行) → 提取 `static/css/base.css` + `static/js/base.js`
- **`static/js/cmd/editor.js`**(607行) → 拆分 `editor-highlight.js` + `editor-sse.js`
- **`static/js/cmd/scheduled.js`**(593行) → 拆分 `scheduled-logs.js`
- **executor 稳定性**：阶梯式终止（SIGTERM→SIGKILL）防止僵尸进程
- **SSE 稳定性**：短轮询替代长 wait，客户端断开时及时退出
- **scheduler 异常隔离**：单任务失败不影响调度循环

### 新增（MiniScript 后端化）
- MiniScript 后端 Python 执行引擎（`services/miniscript/`，独立子进程 + AST 沙箱 + 管道通信）
- 脚本定时执行功能：`scheduled_tasks` 表新增 `task_type` 字段（`shell` / `script`，默认 `shell`），调度器按类型分发到 `subprocess.run` 或 `ScriptExecutor`
- 数据库优化备份功能（手动触发 + 自动清理旧备份，备份写入 `./backups/db/`）
- 定时数据库备份调度器（默认每天 03:00 执行 CHECKPOINT + 文件复制 + 完整性校验）
- 数据库备份管理面板（`admin_db_backup.html`，含 10 阶段进度条与最近 20 条备份历史）
- 文件读写/数据库访问内置函数：`file_read` / `file_write` / `file_append` / `file_list` / `file_exists` / `db_query` / `db_execute`
- AST 沙箱校验器（`validate_script`）：拒绝 `exec` / `eval` / `compile` / `__import__` 等危险调用、双下划线属性访问、`global` / `nonlocal` 声明
- 脚本强制终止功能：`POST /admin/cmd/abort-script` 接口 + 编辑器/终端「强制终止」按钮
- 脚本内 `set_timeout(seconds)` 动态调整超时（上限 300 秒）
- MiniScript 脚本执行 SSE API：`POST /admin/cmd/run-script` 流式返回 `output` / `alert` / `prompt` / `confirm` / `error` / `done` 六种事件
- 交互响应接口 `POST /admin/cmd/script-response`：通过 `threading.Event` 唤醒等待中的 SSE 线程
- 脚本执行互斥控制：同时只允许一个脚本执行，并发请求返回 `409`
- 交互响应超时保护：等待前端响应超过 60 秒时，`prompt` 返回 `None`、`confirm` 返回 `False`
- 循环迭代上限保护：`while` / `for` 最大 100,000 次迭代
- `db_backups` 表：记录备份状态/大小/耗时
- 兼容老库：`init_db` 自动通过 `ALTER TABLE ADD COLUMN` 补齐 `task_type` 字段

### 变更
- 数据库从 SQLite 迁移到 DuckDB（高性能嵌入式 OLAP，单文件、列存、窗口函数）
- DuckDB 兼容层：`core/database.py` 封装 `DuckDBRow` / `lastrowid` / `executescript` / `SEQUENCE + nextval()` 模拟 sqlite3 接口
- 前端编辑器移除 JS 解释器，改用后端 SSE API 执行脚本
- Monaco 编辑器语法高亮改为 Python 配色（自定义 `pythonDark` 深色主题），编辑器模块从 `MiniScriptEditor` 重命名为 `ScriptEditor`
- 定时任务支持 `shell` 和 `script` 两种类型，前端管理页面新增任务类型选择器与徽章展示
- 定时任务状态实时反馈：任务卡片底部显示执行状态徽章，页面每 15 秒拉取 `/admin/cmd/scheduled/status` 轻量接口
- 访问日志自动清理迁移至独立服务 `services/log_cleaner.py`（后台线程定期检查），不再在中间件中每 10 条检查一次
- 日志清理扩展为多表：`access_logs` / `cmd_run_logs` / `scheduled_task_logs` 均支持自动清理

### 重构（前端模块化拆分 + 稳定性优化）
- **`templates/base.html`** 拆分：内联 CSS 提取至 `static/css/base.css`，内联 JS 提取至 `static/js/base.js`，模板改用 `<link>` / `<script>` 引用，模板行数大幅下降
- **`static/js/cmd/editor.js`** 拆分为三个职责清晰的文件：
  - `editor-highlight.js` — Monaco Python 语法高亮、代码补全、自定义主题（`window.ScriptEditor.highlight`）
  - `editor-sse.js` — SSE 执行、事件分发、强制终止（`window.ScriptEditor.execute` / `abort`）
  - `editor.js` — 核心初始化、工具栏绑定、输出面板管理
  - 模板 `admin_cmd_editor.html` 按依赖顺序加载：`editor-highlight.js` → `editor-sse.js` → `editor.js`
- **`static/js/cmd/scheduled.js`** 拆分为两个文件：
  - `scheduled.js` — 任务核心管理（CRUD / 启停 / 触发 / 状态轮询），暴露 `window.ScheduledCore`（含 `escapeHtml`）
  - `scheduled-logs.js` — 执行日志查看（分页 / 详情），暴露 `window.ScheduledLogs.openLogsModal(taskId | null)`
  - 模板 `admin_cmd_scheduled.html` 按顺序加载：`scheduled.js` → `scheduled-logs.js`
- **`services/miniscript/executor.py` 稳定性优化**：`_terminate_process` / `_cleanup` 采用「SIGTERM → 等待 → SIGKILL → 等待」阶梯式终止策略，确保子进程在任何异常路径下都被回收，避免僵尸进程；`proc.start()` 失败时显式关闭未使用的子端管道，避免 fd 泄漏
- **`routes/cmd/script.py` SSE 稳定性优化**：新增 `_wait_for_response` 短轮询（2 秒间隔）替代单次长 `wait()`，客户端断开 / 执行器被终止时能及时退出等待；显式捕获 `GeneratorExit` 不再尝试向已断开的连接 `yield` 错误；`finally` 中唤醒响应事件避免死锁，防御性释放 `_running_lock`
- **`services/scheduler.py` 任务异常隔离**：调度主循环 / `_tick` / `_execute_task` / `trigger_now` 全链路异常隔离 — 数据库异常不冒泡到主循环、单个任务提交失败不影响其他任务、收尾失败也确保从 `_running_tasks` 移除（避免任务卡死无法再次调度）；所有异常均带 `traceback` 输出便于排查

### 删除
- 前端 JavaScript MiniScript 解释器（`static/js/cmd/script.js`，约 1082 行）
- SQLite 数据库支持（`site.db`）
- 旧的 `cmd_sync()` / `regex()` / `append()` / `push()` / `pop()` / `slice()` / `set_interval()` / `clear_timer()` 等已废弃脚本函数
- 前端实时语法诊断（改为后端执行时通过 SSE `error` 事件回传）
- 一次性迁移脚本 `migrate_sqlite_to_duckdb.py`

### 修复
- 修复弹窗（alert/prompt/confirm）按钮点击无反应：移除遮挡按钮的 `escapeLayer` 透明层，改为 `document` 级别监听 ESC 键；修复 `display:flex` 优先级高于 Tailwind `.hidden` 类的问题；`close()` 添加 300ms 超时 fallback

## [历史版本]

### 新增
- 定时 CMD 终端命令运行功能：支持间隔执行、每日定时、一次性执行三种调度模式
- 日志自动清除功能：访问日志、CMD 日志、任务日志超限自动删除最旧记录，上限可在 `config.py` 配置
- CMD 代码编辑器（Monaco Editor）：语法高亮、代码补全、查找替换、多光标编辑、Minimap
- 用户系统、社区投票、留言板（多附件上传）、模组介绍、管理后台、服务器性能监控
- 异步多线程架构改造：日志写入、IP 查询、命令执行日志全部改为异步多线程，不阻塞 Web 请求
- 用户信息查询优化：单次请求内缓存（Flask `g` 对象），避免 middleware 和路由重复 DB 查询
- CPU 使用率改为非阻塞模式（`psutil.cpu_percent(interval=None)`）
- 社区页面数据库查询优化：批量查询消除 N+1 问题，N 个投票 + M 个主题从 `1 + 3N + 2M` 次查询降至 `4` 次
- AJAX 双模式支持：社区路由同时支持表单提交（flash + 重定向）与 AJAX 请求（JSON 响应）
- 文档系统：`/docs` 页面渲染 Markdown 文档（marked.js + 侧边栏导航）
- CherryPy WSGI 服务器（内置 SSL 支持）
- 磨砂玻璃（Glassmorphism）设计风格：`backdrop-filter` 模糊、动态背景光球、鼠标光晕跟随、按钮水波纹、滚动淡入
