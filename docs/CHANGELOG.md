# 更新日志

## [Unreleased]

### 优化
- 文档体系二次整合，最终精简为单一入口：
  - 将 `docs/ARCHITECTURE.md` 与 `docs/cmd-guide.md` 内容完整并入 `README.md`（架构、目录结构与技术栈；CMD 控制台使用说明），删除两文件
  - `README.md` 成为唯一综合文档入口（总览/快速开始/功能/配置/API/架构/CMD 使用说明），`docs/` 仅保留开发准则与更新日志
  - `docs/DEVELOPMENT.md` 新增「文档写入准则」章节，明确文档结构、命名规范、内容组织与更新流程
  - 修正各处指向已删除文档的链接（README 文档索引、DEVELOPMENT 引用）
- 导航栏性能优化：`.glass-nav-inner` 的 `translateX(-50%)` 改为 `translate3d(-50%,0,0)` 提升为独立合成层，并 `will-change: transform, backdrop-filter` 缓存磨砂模糊，滚动时不再逐帧重模糊；移除无益的 `will-change: width, border-radius`
  - 视觉与磨砂玻璃效果保持不变，仅降低滚动期的重绘/重合成开销
- 重构项目文档结构，按职责拆分，消除"乱塞"：
  - 新增 `docs/ARCHITECTURE.md`：架构分层、目录结构、技术栈、异步架构、数据库设计、一键更新机制（从 README/DEVELOPMENT/DEPLOYMENT 迁移）
  - `docs/DEVELOPMENT.md` 整合为「开发与部署规范」：分层规范/易错点/测试/路由检测 + 构建打包与发布流程 + 更新规则（吸收原 README 开发注意事项与 DEPLOYMENT 内容）
  - 移除 `docs/DEPLOYMENT.md`（一键更新机制并入 ARCHITECTURE，其余并入 DEVELOPMENT）
  - `README.md` 精简为总览 + 快速开始 + 功能特性 + 配置 + API，并补充「文档索引」统一入口
- 图形验证码字体加大：`services/captcha.py` 字体从 40 提升到 52，画布增至 300×96，并增加左右留白避免旋转后裁切；弹窗/表单中验证码图片显示高度从 `h-16` 提升到 `h-20`，整体更清晰易读
- 指南提交改为「点击提交审核后再弹验证码」：移除 `guides/form.html` 内联验证码字段，改为隐藏字段 + 全局 `CaptchaModal` 弹窗
  - 点击「提交审核」按钮后才弹出图形验证码，验证通过才真正提交表单
  - 验证码出错时弹窗内直接刷新验证码，**不刷新页面**，保留已填写的标题/摘要/正文内容

### 修复
- 修复 `/admin/guides` 预览弹窗无法滚动：预览卡片作为 flex 子项默认 `min-height:auto` 导致内容撑破 `max-h-[85vh]`，`overflow-y-auto` 失效；为卡片补加 `min-h-0` 使其可收缩，预览内容超长时可正常纵向滚动
- 修复打开首页白屏：页面入场动画改用纯 CSS animation 自动播放，不再依赖 `base.js` 在 `DOMContentLoaded` 添加类显示
  - 原实现用 `.js .page-content{opacity:0}` 常驻隐藏内容，显示依赖 body 末尾同步脚本 `base.js`；脚本加载慢/失败时内容长时间不可见 → 白屏
  - 新实现元素首次渲染即自动播放入场动画，脚本加载问题不再导致白屏；JS 禁用时内容默认可见
  - 同步更新 `DEVELOPMENT.md` 易错点 #4，记录避免白屏的方法

### 优化
- 导航栏收缩动画流畅化修复：改用 `width` 数值过渡 + `translateX(-50%)` 居中，替代无法插值的 `max-width:auto`/`margin:auto`，彻底消除切换跳变
  - 弹性曲线 `cubic-bezier(0.34, 1.3, 0.64, 1)` + 0.45s，更迅捷自然，带轻微回弹
  - 新增 `will-change` 提升合成层，动画更顺滑
- 导航栏增强：向下滚动后收缩为居中漂浮的椭圆胶囊，细腻磨砂玻璃质感
  - 滚动前为顶部通栏磨砂条，滚动超过 32px 后收缩为居中椭圆胶囊（`max-width: 68rem` + `border-radius: 999px`），两侧留白
  - 磨砂质感更凝实：提高背景不透明度、`backdrop-filter: blur(40px) saturate(140%)`、顶部渐变高光细线、双层内阴影
  - 弹性缓出动画（`cubic-bezier(0.22, 1, 0.36, 1)`），滚动状态切换流畅
  - 尊重系统「减少动态效果」偏好（`prefers-reduced-motion`）
  - 新增 `initNavShrink()`（`main.js`）监听滚动，`base.html` 导航栏包裹 `.glass-nav-inner` 胶囊容器
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