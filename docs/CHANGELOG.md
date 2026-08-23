# 更新日志

## [Unreleased]

### 新增
- **音频独立上传页与详细进度条**：上传从列表页内嵌面板拆分为独立页面 `/music/upload`（`templates/music/upload.html` + `static/js/music_upload.js`），列表页/「我的音频」页改为跳转独立上传页；采用「异步任务 + 轮询进度」——上传请求立即返回 `task_id`，后台线程执行 ffmpeg 转码，前端分两阶段展示进度条（文件上传百分比 + 转码百分比），`ffprobe` 探测音频时长、解析 ffmpeg `-progress` 输出实时计算转码进度，成功后展示播放链接并可复制/再传一个，失败展示错误并可一键重试（`services/music_service.py` 新增 `start_upload`/`_run_upload_task`/`get_upload_progress`/`_probe_duration`，`config.py` 新增 `FFPROBE_BIN`，每个上传任务独立临时目录与 ffmpeg 子进程，多用户并发互不冲突）
- **自定义音量增益**：上传前可拖动滑块或点快捷预设设置音量增益（-12 ~ +12 dB，0 为不调整），转码时经 ffmpeg `volume` 滤镜写入 HLS 产物；上传后上传者本人或管理员可在「我的音频」/管理后台重新调整并即时重新转码（`POST /music/<id>/gain`，`music_service.update_gain()` 在独立临时目录重新转码后一次性替换产物、保留源文件）；`music` 表新增 `gain` 字段持久化（含迁移）
- **「我的音频」页与管理后台音量增益编辑**：`templates/music/my.html` 与 `templates/admin/admin_music.html` 为每个音频新增增益输入框与「音量」应用按钮，`next` 参数保持跳回来源页
- **音频列表与公开控制**：板块内展示全部公开音频与「我的音频」列表，用户可随时切换公开/私有；公开后所有用户（含未登录）可在游戏内大喇叭音频列表看到并播放
- **管理员后台管理**：新增「大喇叭音频管理」页，管理员可查看全部音频并一键下架（删除）
- **删除同步清理文件**：音频在数据库删除记录时同步删除 `uploads/music/<ID>/` 目录，无文件残留；数据库表 `music` 记录上传者/标题/公开状态/时间
- **内置 ffmpeg 自动调用**：Windows 调用 `scripts/ffmpeg/ffmpeg.exe`，Linux/macOS 调用 `scripts/ffmpeg/ffmpeg`，未内置时回退系统 PATH 中的 `ffmpeg`（config 新增 `FFMPEG_DIR`/`FFMPEG_BIN`）
- **公开音频审核机制**：申请公开的音频进入「待审核」，管理员在后台可试听并选择通过/驳回；通过后才在游戏内大喇叭展示，驳回后用户可转为私有或删除；已公开转私有再申请公开需重新审核。`music` 表以 `status`（0=私有 1=待审核 2=已公开 3=已驳回）替代 `is_public`，历史公开数据自动迁移为「已通过」
- **音频审核结果邮件通知**：管理员通过/驳回公开申请后，自动向上传者邮箱发送审核结果邮件（后台线程异步发送，不阻塞请求）；邮件未启用或上传者无邮箱时自动跳过。`services/email/templates.py` 新增 `music_review_result()` 构建函数与 `templates/emails/music_review_result.html` 模板，`services/music_service.py` 新增 `get_author_email()` 查询上传者邮箱
- **公开音频名称搜索**：公开音频列表支持按名称模糊搜索（`GET /music?q=关键词`，`get_public_musics()` 新增 keyword 参数），展示搜索结果数与无结果空态，支持一键清除
- **「我的音频」独立页面**：原内嵌在公开列表页的「我的音频」拆分为单独页面 `/music/my`（`templates/music/my.html` + `static/js/music_my.js`），公开页顶部提供入口；公开/私有切换与删除操作通过 `next` 参数跳回来源页；公开页上传面板支持 `#upload-panel` 锚点自动展开
- **一键更新支持子目录不替换**：不替换列表现支持子目录路径（如 `scripts/ffmpeg`），命中后该子目录删除/复制阶段均跳过，完全保持本地现状（不被覆盖、不新增仓库文件、本地独有文件保留）；重构同步为 `_sync_item`（`_rmtree_skip_protected`/`_copy_tree_skip_protected`，删除带 Windows 文件占用重试），新增 3 个子目录/本地独有文件保护测试
- **ffmpeg 多线程转码**：新增 `FFMPEG_THREADS` 配置（0=自动按 CPU 核数，1=单线程降级），上传转码统一加 `-threads` 参数；每个上传任务是独立 ffmpeg 子进程与独立输出目录，多用户同时上传天然并行，不会出现「文件正在使用」冲突
- **一键更新保护本地资产**：更新同步新增「本地独有文件暂存恢复」机制——同步前暂存本地存在而仓库中没有的文件（如 `scripts/ffmpeg/` 下未入库的二进制），复制完成后自动恢复，解决更新后 ffmpeg 文件夹等本地资产被误删的问题（`services/updater.py` 新增 `_preserve_local_only`/`_restore_local_only`）

### 优化
- **管理中心数据统计调整**：移除已删除功能（投票活动/投票次数/征集/征集回复）的统计卡片，修复因 `polls`/`board_*` 表已从 schema 移除导致的管理中心 500 错误；新增「大喇叭音频」总数与「待审核大喇叭音频」数量统计（`routes/admin/pages.py` 与 `templates/admin/admin.html`）
- **邮件模板统一磨砂玻璃风格**：`templates/emails/base.html` 重做为暗绿金黄玻璃卡片，新增背景光晕、噪点纹理、光线散射层、顶部高光描边与通过/失败状态卡样式（`.mail-status-success` / `.mail-status-fail`），验证码 / 指南审核 / 音频审核 / 广播邮件共用同一外层与样式
- **邮件 HTML 全面统一风格**：`guide_review_result.html` 改用通过/失败状态卡（与音频审核邮件一致），`guide_review_pending.html` 新增待审核状态卡（`.mail-status-pending` 金黄色样式 + 时钟图标），`broadcast_message.html` 移除内联样式改为复用基础样式类（`mail-muted`/`mail-content`），所有邮件模板视觉风格统一
- **大喇叭音频页充分使用模板宏**：新增 `templates/macros/music_macros.html`，提取音频状态徽章（`music_status_badge`）、复制链接按钮（`music_copy_link_button`）、HLS 播放器（`music_audio_player`）为公共宏，`music/list.html` 与 `admin/admin_music.html` 统一调用，消除重复的内联代码；播放器补充磨砂玻璃质感样式（`.music-audio`）
- **统一全站进度条为磨砂玻璃质感**：新增 `.progress-track` / `.progress-fill` 组件（半透明磨砂轨道 + 渐变流光扫过动画 + 顶部高光 + 柔光晕），提供 `gold / green / blue / purple / red / yellow` 六种颜色变体与 `xs / sm / md / lg` 四档尺寸；一键更新、数据库备份、CPU/内存监控、背景上传、附件上传等所有进度条统一改用该组件，视觉一致且不削弱原有动效
- **充分使用模板宏**：新增 `templates/macros/progress.html` 进度条宏 `progress_track()`，`admin_update.html`、`admin_db_backup.html`、`performance.html`、`index.html` 统一通过宏生成进度条，消除重复的内联样式代码

### 重构
- **清理模板冗余**：移除 `base.html` 中未被任何页面覆写的空 `{% block nav %}`；进度条颜色切换由内联 `background` 改为语义化的 `progress-fill <variant>` 类

### 移除
- **彻底删除大喇叭实时直播台**：移除 `services/live_service.py`、`routes/main/live.py`、`templates/music/live.html`、`static/js/live.js`、`scripts/tests/test_live.py`，删除 `config.py` 中 `LIVE_BROADCAST_DIR`/`LIVE_HLS_SEGMENT_SECONDS`/`LIVE_HLS_LIST_SIZE`/`LIVE_IDLE_TIMEOUT`/`LIVE_MAX_DURATION` 等直播配置，`app.py` 移除 `live_service` 引用与清理，`routes/main/__init__.py` 移除直播路由，音频列表与管理后台移除「实时直播台」入口按钮；**保留 ffmpeg 多线程转码**（`FFMPEG_THREADS` 继续用于音频上传转码，多用户同时上传互不冲突）
- **彻底删除 MinIO 对象存储**：移除 `services/object_storage.py`、`config.py` 中 MinIO 相关配置、`app.py` 中 MinIO 初始化检查、`routes/main/media.py` 中 MinIO 引用改为本地文件存储、`services/user_service.py` 中 MinIO 清理逻辑改为本地文件清理；删除 `.env.example` 和 `docs/MINIO.md`
- **移除系统设置中的背景图片开关**：从 `SETTINGS_REGISTRY` 中移除 `ENABLE_BACKGROUND_IMAGE` 和 `BACKGROUND_FADE_IN_MS`，首页背景只保留上传按钮 + 图片预览弹窗
- **删除投票与征集功能**：彻底移除 `routes/community/polls.py`、`routes/community/board.py`、`services/poll_service.py`、`services/board_service.py`、`templates/community.html`，从数据库 schema 中移除 `polls`、`poll_options`、`poll_votes`、`board_topics`、`board_replies` 表，从导航和首页移除入口链接

### 优化
- **首页背景图片交互优化**：上传改用 XHR 异步 + 进度条，新增预览弹窗，点击预览按钮即可查看大图
- **全站文件上传进度条**：全局进度条自动拦截所有 `multipart/form-data` 表单提交，显示实时上传进度
- **指南卡片金色上边框优化**：渐变两端淡出，增加柔光晕效果，与玻璃质感卡片更融合

### 重构
- **终端彻底升级为 xterm.js**：用业界标准的分享终端模块 `terminal-xterm.js` 替代旧版自制 ANSI 字符网格渲染器，彻底修复「回车只输入不执行」「字符排版错乱」。字符绘制、光标、清屏、行宽、输入回显与本地终端完全一致；输入走 `term.onData` 将原始字节直送后端 PTY 驱动，回车即可执行；尺寸自适应（`xterm-addon-fit`）将行列数同步到 PTY，避免换行错位与黑屏
- **「CMD」全面改名为「脚本」**：后端包 `routes/cmd`→`routes/script`、蓝图 `cmd_bp`→`script_bp`、URL `/admin/cmd*`→`/admin/script*`，前端 `static/js/cmd`→`static/js/script`、模板 `admin_cmd_*.html`→`admin_script_*.html`，同步更新快捷命令/定时任务/终端/编辑器全部入口与可见文案，并同步测试用例与文档

### 新增
- **更新脚本机制**：创建 `scripts/uploads.py`，每次一键更新完成后自动执行（不存在则跳过），用于清理旧数据、迁移文件等；`scripts/migrate_uploads.py` 委托 `uploads.py` 并可触发静态资源构建
- **复原「弹窗终端」且无独立入口**：脚本控制台不再有「实时终端」按钮；点击任意快捷命令/脚本卡片的「运行」即自动打开弹窗终端（`terminal-modal.js`）并在其中执行——Shell 命令发到共享持久 PTY 会话、脚本走后端 SSE 独立子进程。顶栏提供「中断/清屏/重置/关闭」，`Esc` 或点击遮罩可关闭
- **MiniScript 解除安全限制**：删除 AST 沙箱校验、危险函数黑名单、双下划线属性保护、循环次数限制与运行时长限制，脚本可无限循环、无限运行；仅保留独立子进程隔离与资源访问控制作为「防误炸服务器」底线
- **退出网页即强制终止脚本**：前端监听 `visibilitychange`/`pagehide`/`beforeunload` 主动上报终止，后端以心跳监控线程兜底，覆盖意外关闭浏览器/tab 崩溃场景
- **定时任务调度优化**：改为按到期时间升序排队、每秒判断一次，不再每轮全表扫描；新增「运行中任务」面板，实时查看已触发的脚本
- **直接运行任务**：任务卡片「立即执行」直接运行，不受超时限制，可一路运行到底，并在「运行中任务」中查看
- **任务级最大超时**：创建/编辑定时任务时可单独设置「最大超时时间（秒）」，超时自动终止（直接运行不受此限制）

### 修复
- **修复实时终端「回车只输入不执行」与排版错乱**：改用 xterm.js 渲染 + PTY 字节级输入，输入回车由终端驱动真实执行并回显（详见上方「重构」）
- **修复弹窗终端初始黑屏/尺寸为 0**：为终端容器固定高度、每次显示弹窗时重新 `fit`、并限制后端 `/resize` 只在合法尺寸（≥2×2）时回传，杜绝初始零尺寸容器触发 `400`
- **修复 DuckDBRow 在 Debian 下 `description` 列数多于实际行数据导致 `dict(r)` 崩溃**：构造时自动以 `None` 补齐，确保 `dict(行)` 总是安全返回
- 修复定时任务「创建定时任务」「执行日志」按钮无反应：`scheduled.js`/`scheduled-logs.js` 移入 `extra_script` 块，确保在 `page_modals` 弹窗 DOM 渲染后再加载绑定
- 修复快捷命令「运行/编辑/删除」按钮无反应：`presets.js` 事件绑定读取 ID 时改用与模板一致的 `dataset.scriptId`（原误用 `dataset.cmdId`），模态框选择器同步为 `script-modal`/`script-form`
- 修复脚本编辑器输入区无法输入：Monaco 加载路径由不存在的 `loader.min.js` 改为正确的 `loader.js`

### 优化
- **终端升级为伪终端（跨平台）**：SSH 式交互体验，Python `input()`/readline 原生可用、输入回显与行编辑正确、清屏与 ANSI 光标控制真实响应、输出实时流式返回；移除前端强制插入的 `$` 提示符，只保留真正的命令提示符。Unix/macOS 走原生 `os.openpty()`，**Windows 无 pty/termios，改用 pywinpty（ConPTY）提供同等的真伪终端**（未安装 pywinpty 时自动回退到管道实现，避免启动失败；`requirements.txt` 已按平台标记引入 `pywinpty`）
- 构建脚本 `build_static.py` 新增 xterm.js 本地化下载（`xterm.min.js`/`xterm.min.css`/`addon-fit.min.js`），写入 `static/lib/xterm/`
- **清理历史遗留命名**：`CmdPresets`→`ScriptPresets`、`__abortCmdScript`→`__abortRunningScript`，删除编辑器退出上报中一处无意义的错误兜底逻辑
- 文档体系二次整合，最终精简为单一入口：
  - 将 `docs/ARCHITECTURE.md` 与 `docs/cmd-guide.md` 内容完整并入 `README.md`（架构、目录结构与技术栈；CMD 控制台使用说明），删除两文件
  - `README.md` 成为唯一综合文档入口（总览/快速开始/功能/配置/API/架构/CMD 使用说明），`docs/` 仅保留开发准则与更新日志
  - `docs/DEVELOPMENT.md` 新增「文档写入准则」章节，明确文档结构、命名规范、内容组织与更新流程
  - 修正各处指向已删除文档的链接（README 文档索引、DEVELOPMENT 引用）
  - 复制 `README.md` 到 `docs/README.md` 作为镜像副本，并修正其内部相对链接使其在 docs/ 目录下可用
  - 精简 CMD 控制台说明中的 MiniScript 介绍：删除大段 Python 语法教程（变量/运算/条件/循环/列表/字典/函数/类/异常等），改为一句「语法与 Python 一致」，具体语法参考 Python 文档
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
  - 统一所有页面内联玻璃样式
- `uploads/` 目录按功能分类重组：附件归 `uploads/attachments/`、背景图片归 `uploads/backgrounds/`、社区文件归 `uploads/community/`，根目录不再堆文件
- 新增**全站背景图片**功能：可在 `config.py` 或管理后台「系统设置→背景图片」中开启/关闭
  - 背景图片存放在 `uploads/backgrounds/`，命名规范 `bg_<比例>.jpg/webp/png`（如 `bg_16_9.jpg`）
  - 前端自动检测屏幕宽高比（`16:9`/`16:10`/`4:3`/`9:16`/`3:4`/`1:1`），请求匹配的背景图
  - CSS `background-size: cover` + 暗化覆层（`rgba(7,18,12,0.35)`）确保文字可读性，加载时淡入过渡
  - 图片由 `background/<比例>` 路由提供，服务端精确匹配或降级到第一张可用背景图，无图片时静默不显示
  - 关闭时完全恢复默认玻璃光晕背景，零开销（`index.html`、`settings.html`、`guides/index.html`、`register.html`、`admin/admin_mod_intros.html`、`admin/admin_cmd.html`、`base.html`）

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