# 更新日志

## [Unreleased]

### 优化
- 一键更新下载进度条优化：成功开始下载 ZIP 压缩包后进度条正常实时推进
  - 服务器未返回 `Content-Length` 时按估算大小推进进度，避免进度条卡死
  - 改用"变化阈值"触发回调（每 1% 或每 512KB），进度平滑且不漏最终值
  - 下载完成时强制回调 100，避免进度跳变
  - 直连 GitHub 下载路径同样接入进度回调，不再无进度显示
  - 新增 `scripts/tests/test_updater.py` 覆盖 Content-Length 已知/未知两种下载场景
- 磨砂玻璃 UI 全面升级：去除塑料感，模拟真实酸蚀刻玻璃效果
  - 卡片/按钮/弹窗/输入框/导航栏改用 `linear-gradient` 渐变背景，替代纯色 `rgba`
  - 降低 `backdrop-filter` 饱和度（`saturate(220%)` → `saturate(100%)`），效果更自然通透
  - 添加光线散射伪元素（`radial-gradient` 模拟漫射光），模拟磨砂玻璃内部光线散射
  - 添加边缘光晕伪元素（`mask-composite` 渐变边框），模拟玻璃切割面折射
  - 降低背景透明度（`0.18` → `0.08~0.10`），让背景光晕充分透出
  - 全局噪点纹理优化（`fractalNoise` 频率降低、增加去饱和度），微观蚀刻感更真实
  - 添加环境光晕叠加（`body::after`），模拟玻璃微弱冷色/暖色环境反光
  - 背景光球透明度降低（`0.85` → `0.50`），模糊半径增大（`60px` → `80px`），光晕更柔和
  - 统一所有页面内联玻璃样式（`index.html`、`settings.html`、`guides/index.html`、`register.html`、`admin/admin_mod_intros.html`、`admin/admin_cmd.html`、`base.html`）

### 重构
- 统一 Markdown 编辑器组件：新建 `templates/macros/markdown_editor.html` 宏 + 共享脚本 `static/js/markdown-editor.js`，覆盖广播邮件、指南编辑、讨论帖创建等 4 个页面，消除重复的内联样式与脚本
- 移除 highlight.js 代码语法高亮（CSS/JS/语言包约 200KB），代码块改为原生 `<pre><code>` 渲染，性能与资源体积优化，保留一键复制功能（`base.js` 的 `CodeBlocks` 模块）
- 邮件 Markdown 渲染移除 `codehilite` 扩展，改用邮件客户端兼容的基础 HTML 标签，修复自定义 Markdown 邮件无法正常显示的问题
- 图形验证码弹窗模块化：将验证码弹窗 HTML 提取到 `base.html`，JS 逻辑提取到 `base.js` 的 `CaptchaModal` 全局对象，消除 `register.html` 和 `forgot_password.html` 中的重复代码
- 邮箱唯一性检查：注册和修改邮箱时检查邮箱是否已被其他账号使用，确保一个邮箱仅可注册一个账号

### 修复
- 彻底修复端点名不一致导致的 500：除 `/settings` 外，`routes/discussion/api.py` 的 `delete_reply`/`toggle_pin`/`toggle_lock`/`delete_topic` 原带 `_view` 后缀，与模板 `url_for('discussion.delete_reply')` 等端点不匹配，讨论区删除/置顶/锁定操作会抛 `BuildError`。已统一移除 `_view` 后缀并对 service 导入用别名（`svc_*`）避免递归
- 新增回归测试防止此类低级 bug 再现：`test_routes.py` 增加「登录后渲染关键页面返回 200」与「模板中所有 `url_for` 端点必须已注册」两项检测
- 修复管理后台「删除用户」接口对任何用户均返回 500：`routes/admin/users.py` 漏导入 Flask 的 `request` 对象导致 `NameError`
- 修复静态资源构建脚本 `build_static.py` 项目根目录路径计算错误：原 `SCRIPT_DIR/..` 指向 `scripts/`，导致构建产物写入错误目录，全新部署无法加载静态资源
- 新增静态检查脚本 `scripts/tests/check_undefined_names.py` 并集成进测试套件，自动扫描"使用但未定义/未导入"的名字，防止同类 NameError 运行时错误回归
- 修复 DuckDB 多进程并发写入假阳性错误：`_is_mp_child_process()` 检测结果模块级缓存，避免多次调用时 `sys.argv` 或 `multiprocessing.current_process().name` 产生假阳性
- `AsyncLogWriter` 和 `LogCleaner` 容错增强：捕获 `get_db()` 抛出的 `RuntimeError`，在子进程中静默跳过而非崩溃

### 新增
- 外部链接配置化：卫星地图网址、QQ 群链接可在管理后台在线编辑（热重载）
- 注册页面图形验证码改为点击"发送验证码"按钮后弹窗，优化交互流程
- `MAP_URL` 和 `QQ_GROUP_URL` 配置项，支持管理后台实时修改
- 广播邮件页面 Markdown 编辑器升级为分栏布局（编辑区 + 实时预览区），支持工具栏、滚动同步
- 一键更新功能：从 GitHub 自动获取并覆盖代码文件，智能代理检测，自动重启（`services/updater.py`）
- 代码块一键复制：Markdown 代码块使用原生 `<pre><code>` 渲染，鼠标悬停时显示复制按钮，点击复制代码并反馈"已复制"状态
- 图形验证码（服务端内存存储、一次性删除防重放）
- 邮箱验证码（SMTP）
- IP 频率限制
- 异步日志写入与自动清理
- DuckDB 数据库兼容层

### 修复
- 修复发布指南/编辑指南时图形验证码缺失的问题：在表单中添加验证码字段，路由中增加 `captcha_service.verify()` 校验
- 修复控制台日志（`services/logger.py`）显示 `127.0.0.1` 的问题：`log()` 函数自动使用 `get_client_ip()` 获取真实客户端 IP，统一与访问日志的 IP 判断逻辑
- 修复验证码文字渲染：每个字符独立随机颜色 + 轻微上下抖动，增强安全性
- 删除首页顶部导航栏（特色玩法、模组介绍、服务器理念、加入我们）
- 一键更新：移除空命令时系统自动处理启动的 fallback 逻辑，统一使用 `{python} app.py` 默认命令
- 修复 `/performance` 页面 500 错误：`url_for` 端点名从 `api.performance` 修正为 `api.api_performance`
- 修复 `/admin/broadcast` 发送广播按钮无反应：脚本移入 `extra_script` 块，确保 `page_modals` 中的弹窗元素已加载
- 广播邮件页面移除了 `var body` 与 `document.body` 的变量名冲突
- 注册页面移除内联图形验证码，统一为弹窗方式
- 注册表单提交不再重复验证图形验证码（已在邮箱发送时验证）
- 讨论区回复实时刷新功能（默认 5 秒间隔，仅后台可配置）
- 讨论区回复分段加载（分页加载 + "加载更多"按钮）
- 发表回复窗口移至回复列表上方，优化交互流程
- 删除回复改为 AJAX 异步操作，无需刷新页面
- 回复实时刷新只获取最新回复，不对已加载内容重复请求

### 优化
- 图形验证码逻辑精简：仅在邮箱验证码发送时校验，不再冗余校验
- 数据库查询仅返回必要字段，减少网络传输
- 前端 `Set` 去重机制，避免重复渲染
- 回复列表改为 JS 动态渲染，减少初始页面加载时间
- 管理后台模板统一移入 `templates/admin/` 子目录，按功能分类整理模板文件
- 新增 `templates/emails/` 邮件模板目录，与页面模板分离
- 重新生成 Tailwind CSS 静态文件（`static/css/tailwind.css`）

---

## [2024-01-15] 之前版本

### 新增
- 指南编辑功能重构为独立页面，修复弹窗滚动问题
- 统一网页弹窗系统，替换浏览器原生 alert/confirm
- 前端移动端彻底适配
- 统一邮件 HTML 模板模块
- 公开文件/目录管理功能
- 数据库在线备份功能（DuckDB ATTACH + COPY FROM DATABASE）
- 持久交互式终端（session-based shell 子进程）
- MiniScript 脚本执行引擎
- 定时任务调度引擎
- 服务器指南系统（审核工作流、封禁管理）
- 讨论帖子系统（分类、标签、附件、置顶、锁定）
- 征集系统（多附件上传）
- 投票系统
- 模组介绍
- 服务器性能监控
- CMD 控制台
- 用户系统（注册、登录、密码修改）
- 图形验证码（服务端内存存储、一次性删除防重放）
- 邮箱验证码（SMTP）
- IP 频率限制
- 异步日志写入与自动清理
- DuckDB 数据库兼容层

### 修复
- 注册页面验证码弹窗居中问题
- 用户注册验证码重复验证失败问题
- 讨论详情页操作后重定向到社区页问题
- 管理页面预览按钮无响应问题
- 指南编辑后重定向错误问题
- 前端 Lucide 图标名错误
- 实时预览不能在窗口内滚动问题
- 验证码安全性增强（扩大答案空间、服务端存储）
- 跨平台子进程兼容性（Windows/Unix）
- Windows 终端输出重复问题
- DuckDB 多进程并发文件锁定问题
- 日志服务包导入错误
- 邮件 SMTP 连接参数错误
- MiniScript 编辑器输出重复问题
- 终端与 MiniScript 架构重构（稳定性提升）

### 优化
- 整体代码结构优化，删除无用代码
- Tailwind CDN 迁移为本地静态构建
- 前端模块化拆分（editor.js、scheduled.js）
- 跨平台子进程基础设施统一迁移到 core/
- 多线程异步架构