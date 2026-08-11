# 更新日志

## [Unreleased]

### 优化
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

### 修复
- 修复 DuckDB 多进程并发写入假阳性错误：`_is_mp_child_process()` 检测结果模块级缓存，避免多次调用时 `sys.argv` 或 `multiprocessing.current_process().name` 产生假阳性
- `AsyncLogWriter` 和 `LogCleaner` 容错增强：捕获 `get_db()` 抛出的 `RuntimeError`，在子进程中静默跳过而非崩溃

### 重构
- 图形验证码弹窗模块化：将验证码弹窗 HTML 提取到 `base.html`，JS 逻辑提取到 `base.js` 的 `CaptchaModal` 全局对象，消除 `register.html` 和 `forgot_password.html` 中的重复代码
- 邮箱唯一性检查：注册和修改邮箱时检查邮箱是否已被其他账号使用，确保一个邮箱仅可注册一个账号

### 新增
- 外部链接配置化：卫星地图网址、QQ 群链接可在管理后台在线编辑（热重载）
- 注册页面图形验证码改为点击"发送验证码"按钮后弹窗，优化交互流程
- `MAP_URL` 和 `QQ_GROUP_URL` 配置项，支持管理后台实时修改
- 广播邮件页面 Markdown 编辑器升级为分栏布局（编辑区 + 实时预览区），支持工具栏、滚动同步
- 一键更新功能：从 GitHub 自动获取并覆盖代码文件，智能代理检测，自动重启（`services/updater.py`）
- 代码块语法高亮：集成 highlight.js，支持 Python/JavaScript/Shell/JSON/YAML/SQL/CSS 等语言
- 代码块一键复制：鼠标悬停时显示复制按钮，点击复制代码并反馈"已复制"状态
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