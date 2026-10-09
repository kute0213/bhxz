# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用白色磨砂玻璃（White Frosted Glass）设计风格。提供用户系统、游戏账号注册申请、模组介绍、管理后台、服务器状态监控、全站背景图片、网站图标可配置等功能。

## 文档索引

| 文档                                                  | 说明                                   |
| --------------------------------------------------- | ------------------------------------ |
| 本文档                                                 | 项目总览、快速开始、功能特性、配置、API、架构               |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)          | 开发准则：分层规范、易错点、测试、路由检测、构建打包与发布、文档写入准则 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md)              | 更新日志                                 |
| [docs/SECURITY\_REPORT.md](docs/SECURITY_REPORT.md) | 安全风险自评估报告：OWASP 逐项评估、风险清单、改进建议       |

## 快速开始

### 环境要求

* Python 3.8+

* pip

### 安装与启动

```bash
pip install -r requirements.txt
python app.py
```

默认 HTTP 模式，端口 5000。

### 构建静态资源

首次运行或更新后，需要构建静态资源（将 CDN 库下载到本地）：

```bash
python scripts/build/build_static.py
```

这会下载以下资源到 `templates/static/lib/`：

* **Lucide Icons** — 图标库

* **Marked.js** — Markdown 渲染

* **JetBrains Mono** — 编程字体（代码编辑器 / 时间码）

* **ZCOOL QingKe HuangYou（站酷庆科黄油体）** — 正文中文字体，本地子集化 woff2（按 `unicode-range` 分片）

* **ZCOOL KuaiLe（站酷快乐体）** — 标题中文字体，同为本地子集化 woff2

> 中文字体使用自带字体：正文 **站酷庆科黄油体**（圆润活泼、笔画简洁），标题 **站酷快乐体**（更俏皮有活力），
> 均为本地分片子集，浏览器只按需下载用到的子集；字体文件随静态资源预构建提交，**零外部 CDN 依赖**。
> 静态资源（含 Tailwind 构建产物 `templates/static/css/tailwind.css`）已预构建并随代码提交，一键更新无需额外构建步骤。

### 打包发布 zip

需要离线分发时，可打包为发布 zip（排除敏感文件、数据库、上传、备份、SSL、日志与第三方库大文件）：

```bash
python scripts/build/package.py
```

输出到 `release/bhxz-YYYYMMDD-HHMMSS.zip`。`release/` 与 `*.zip` 已加入 `.gitignore`，不会提交到仓库。

### 默认管理员

首次启动自动创建：

| 用户名     | 密码          |
| ------- | ----------- |
| `admin` | `admin1324` |

> 登录后请立即修改默认密码。

## 项目结构

```
/workspace
├── app.py / config.py / requirements.txt   # 入口、配置、依赖
├── core/         # 基础设施层（DB/认证/中间件/错误页/共享工具）——不含业务逻辑
│   ├── db/                   #   数据库连接与 schema
│   │   └── connection.py, schema.py
│   ├── system/               #   系统层：日志、启动检查、应用初始化
│   │   └── init.py, logger.py, startup_checks.py
│   ├── shared/               #   共享工具（无业务逻辑，原 utils 收敛于此）
│   │   ├── ip.py, captcha.py, ratelimit.py, validation.py
│   │   ├── process_utils.py
│   │   └── scheduler/        #   统一任务注册表（task / executors / registry）
│   ├── auth.py               #   认证装饰器、密码哈希
│   ├── csrf.py               #   CSRF 防护
│   ├── middleware.py         #   请求中间件（安全标头、攻击扫描）
│   ├── server.py             #   WSGI 服务器与优雅关闭
│   ├── helpers.py            #   页面渲染辅助（render_page / admin_page）
│   ├── template_context.py   #   全局模板上下文注入
│   └── errors.py             #   统一精简错误页渲染（error_simple）
├── services/     # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/               #   数据备份（/uploads/ 全量 zip 极限压缩）
│   ├── buildings/      # 公共建筑（列表/搜索/收藏/评论分页）
│   ├── email/          # 异步邮件发送
│   ├── game_accounts/  # 游戏账号注册申请（审批/驳回/封禁）
│   ├── game_server_ban/ # 游戏服务器封禁申请（审批 → RCON ban → 到期自动 pardon）
│   ├── logging/        # 日志自动清理
│   ├── monitoring/     # CPU/内存/系统/性能追踪（后台线程采集）
│   ├── music/          # 大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/           # RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── updater/        # 自动更新（配置/核心逻辑）
│   ├── user/           # 用户（认证/资料/管理）
│   ├── background_service/  #   背景图片业务（WebP 转换 + 响应式变体）
│   ├── cleanup_service/     #   被驳回内容自动清理
│   ├── firewall/            #   高性能防火墙（DuckDB 引擎 + WSGI 门禁 + DDoS 防护）
│   │   ├── api_guard.py     #     接口频率限制
│   │   ├── service/         #     业务层（core / database / monitor）
│   │   ├── protection/      #     防护策略（content_filter / ddos / file_guard）
│   │   └── transport/       #     连接层（wrappers：WSGI 门禁）
│   ├── settings_manager/    #   系统设置管理
│   ├── security/            #   安全扫描（SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感探测 / 恶意 UA）
│   └── sitemap_cache/       #   Sitemap 缓存服务
├── routes/       # HTTP 路由层（Flask Blueprint）
│   ├── admin/          # 管理后台（用户/备份/设置/日志/更新/游戏账号/指南/音乐/背景/建筑等）
│   ├── api/            # 公开 API（性能/统计/验证码/邮箱）
│   ├── backgrounds/    # 背景图片页面
│   ├── buildings/      # 公共建筑（页面+API，搜索/标签/收藏/评论分页，发布需审核）
│   ├── community/      # 社区辅助（AJAX / 表单统一响应）
│   ├── docs/           # 文档页面
│   ├── game_accounts/  # 申请账号（页面+API，纯申请注册）
│   ├── guides/         # 服务器指南（页面+API）
│   ├── main/           # 主站（登录/注册/设置/音乐）
│   ├── public/         # 公开文件服务
│   └── sitemap/        # Sitemap & robots.txt（自动添加 Crawl-delay 防防火墙误判）
├── templates/    # Jinja2 模板（命名规范见 docs/DEVELOPMENT.md）
│   ├── admin/          # 管理后台页面（如 users.html、settings.html，无 admin_ 前缀）
│   ├── auth/           # 登录 / 注册 / 找回密码
│   ├── settings/       # 用户个人设置
│   ├── site/           # 站点级信息页（站点文档、服务器状态）
│   ├── backgrounds/    # 背景图片页面（index / upload）
│   ├── emails/         # 邮件模板（独立 Jinja2 loader）
│   ├── game_accounts/  # 游戏账号页面（apply / ban_apply）
│   ├── guides/         # 服务器指南页面（index / detail / form）
│   ├── buildings/      # 公共建筑（index / create / detail）
│   ├── music/          # 大喇叭音频页面（index / my / favorites / upload）
│   ├── macros/         # 通用模板宏（模态框/编辑器/进度条/音乐/页面内搜索）
│   ├── static/         # 静态资源（CSS/JS/本地化第三方库，随模板目录存放）
│   └── ...             # 根级通用页面（base.html 布局、index.html 首页、error_simple.html 精简错误页）
├── docs/         # 项目文档
├── scripts/      # 构建脚本（build/）与测试（tests/）
├── uploads/      # 运行期上传数据
│   ├── backgrounds/    # 全站背景图片
│   ├── music/          # 大喇叭音频（每个音频一个 ID 目录，含 m3u8、ts 分片与唱片 MP3）
│   └── db/             # 数据库文件（site.db + firewall.duckdb）
├── backups/      # 数据备份（默认 ../bhxz_backups，支持自定义路径与运行时热改）
│   └── uploads/        # /uploads/ 全量 zip 极限压缩备份（含 SQLite / DuckDB 一致快照）
└── ssl/          # HTTPS 证书（可选）
```

> 完整目录树与各层职责见下文 [架构](#架构)。

## 功能特性

### 用户系统

* 注册/登录（群内验证码 + 邮箱验证码 + 图形验证码三重验证）

* 找回密码（邮箱验证码 + 图形验证码双重验证）

* 账户设置（修改用户名/密码/邮箱/注销）

* 邮箱唯一性约束（一个邮箱仅可注册一个账号）

### 管理后台

* 用户管理、模组介绍管理（支持为每个模组设置跳转链接，前台点击卡片直达）

* 服务器指南 CRUD + 审核工作流 + 编辑封禁

* 大喇叭音频管理（公开申请审核、查看全部音频、一键下架）

* **公共建筑管理**（审核通过/拒绝、管理删除、处理举报）：列表每行提供「预览」按钮，无需跳转详情页即可在弹窗内查看完整内容（标题、领地名、标签、作者、浏览数、建筑描述、使用说明、注意事项、拒绝原因），并提供「前往详情页」入口

* 管理中心数据统计（含大喇叭音频总数与待审核数量）

* 系统设置（在线编辑，热重载，含网站图标选择、日志等级、背景图片开关、RCON 配置、MC 游戏文件夹）

* 系统日志（实时查看，SSE 推送，支持等级过滤、自动滚动；按时间顺序从上到下展示，与控制台一致；**可在页面顶部切换来源查看全局日志 / 严重错误日志 / 各模块单独日志**，页面内「日志设置」可为任意模块配置「是否落盘」「是否并入全局日志」，保存即时生效）。统一日志系统分为三类：**① 全局日志**（普通运行日志 → 控制台 + `logs/app.log` + 内存缓冲 + SSE）；**② 严重错误日志**（导致服务器退出的报错 → 单独写入 `logs/fatal.log`，**每次写入直接覆盖文件、只保留最后一次**，且始终打印到控制台，不受日志等级/控制台开关限制）；**③ 模块单独日志**（模块启动时向日志模块注册，→ 独立内存缓冲 + 可选 `logs/modules/<模块名>.log`；是否落盘、是否并入全局日志**均由设置在「日志页面 → 日志设置」决定，不在模块注册时写死**，支持任意模块；当前使用者为防火墙（`firewall`）、图形验证码（`captcha`）、邮箱验证码（`email_code`）、注册账号（`register`）、登录账号（`login`），其中后四者默认落盘、全部默认不并入全局；两个开关都关闭时日志仅存在于模块独立缓冲，不打印、不落盘、不进全局）。**每次启动自动清理日志**（全局日志文件、严重错误日志文件、所有模块日志文件与内存缓冲统一清空）。**403 响应不写入防火墙模块日志**（防火墙成功拦截与授权拒绝类 403 均不记录；仅保留 IP 封禁 / 自动封禁等封禁动作日志）

* 数据备份（手动/自动，极限压缩 zip，进度条；备份目录支持设置绝对/相对路径，默认 `../bhxz_backups`）

* 公开文件管理

* 广播邮件（富文本所见即所得编辑器 + 白名单 HTML 清洗，安全防 XSS）

* 一键更新脚本（`update.py` — 纯 Python 跨平台，只走下载覆盖，多线程同时测速镜像源（2 秒超时，整个测速 ≤ 2 秒），无需确认启动即更新，保留运行期数据）

* 游戏账号管理（注册申请审批、封禁列表管理）

* **游戏账号封禁**（用户申请 → 管理员审批 → RCON 自动执行）：用户在「申请封禁玩家」页提交封禁玩家名、QQ名、理由；管理员在管理中心「游戏账号封禁」页同意（可设封禁时长，留空为永久）或驳回；同意后经 RCON 执行 `ban 玩家游戏名`（无引号），到期由后台定时任务（每 60 秒检查一次，走 `(status, expires_at)` 索引，单周期最多处理 50 条）执行 `pardon 玩家游戏名`（无引号）自动解封；支持手动提前解封。玩家名经安全清洗杜绝 RCON 命令注入，RCON 执行失败自动保留状态下个周期重试

* 防火墙管理（IP 封禁/IP 白名单/IPv6 拦截/违规警告/防火墙日志：独立高性能 DuckDB 数据库，支持临时/永久封禁，全站拦截，后台一键解封；**IPv6 拦截**：开启后所有 IPv6 连接（除 ::1）在 WSGI 门禁层被直接断开；**防火墙日志**：作为「模块单独日志」写入独立内存缓冲（默认不落盘，可在「日志页面 → 日志设置」开启写入 `logs/modules/firewall.log`），不与系统日志混流，页面内「日志」Tab 从该缓冲读取，支持等级筛选、清空、自动滚动、3 秒轮询刷新；**防火墙成功拦截不记录日志**（IP 封禁兜底、可疑访问拦截均不写日志，避免被封 IP 反复请求时刷屏）；授权拒绝类 403（权限不足 / CSRF 校验失败等）同样不写入防火墙日志，仅保留 IP 封禁 / 自动封禁等封禁动作日志；自动识别可疑操作限流并自动封禁，各操作可独立开关、时长可配；**页面内直接编辑**自动封禁/可疑拦截/DDoS 防护/IPv6 拦截开关与时长、白名单，无需跳转系统设置）

* 可疑访问拦截（识别 SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感文件与漏洞端点探测 / 恶意扫描 UA 等攻击特征，命中即拦截并自动封禁来源 IP，总开关与各攻击类型子开关独立配置、封禁时长可配，白名单 IP 不受影响）

* DDoS 攻击防护（高性能防火墙模块 `services/firewall/`）：独立 DuckDB 数据库存储封禁/白名单/警告/攻击日志，WSGI 门禁在进入 Flask 前直接断开黑名单 IP 的连接（抛出 `waitress.channel.ClientDisconnected`，不写任何响应字节，客户端读到 0 字节后连接断开），不返回任何 HTTP 响应。按检测强度统计单位时间窗口内每个 IP 的请求数（低/中/高三档，检测窗口 10 秒），**防误判机制**：静态资源（`.css/.js/.ico`）、媒体文件（`.mp3/.ts/.m3u8/.webp`）、公共路径（`/static/`、`/music/<id>.mp3`、`/robots.txt`、`/sitemap.xml`）、**API 路径（`/api/`、`/admin/api/`）**不计入请求计数，音频下载与批量接口调用不会误判为 DDoS（批量 API 调用统一交由 API 防火墙限流处理，超限返回 429 而非断开连接）。超阈值自动封禁来源 IP（首次限时封禁；屡教不改升级永久封禁）。后台监控线程同步黑名单镜像、定时清理过期数据与 VACUUM。检测强度、封禁时长、永久封禁触发次数等可在线热更新，白名单 IP 不受影响。robots.txt 自动添加 Crawl‑delay 与敏感路径 Disallow 规则，防止合法爬虫被误封

* **API 调用限流（`services/firewall/api_guard.py`）**：所有 API 请求（`/api/` 前缀、带 `X-Requested-With: XMLHttpRequest` 或 `Accept: application/json`）按来源 IP 限流，**默认每分钟 60 次**；超限返回 429 JSON（含 `Retry-After`），计数存于内存缓存，刷新后随滚动窗口恢复；白名单 IP 与本地回环不受限。搜索、列表「加载更多」等前端 API 调用均纳入计数

* **上传文件防火墙（`services/firewall/protection/file_guard.py`）**：统一校验音频 / 图片上传——危险扩展名（html/svg/js/php/exe 等）直接拒绝；按上传场景限定扩展名白名单；校验文件头魔数，防止「改名伪装」（如 .html 改名 .png）；纯文本文件做内容嗅探拦截脚本标记。未知类型跳过魔数校验以尽可能不误判，被拦截的上传写入防火墙日志。已接入大喇叭音频、背景图片两条上传链路

* **防火墙数据库单写入线程**：所有写操作经队列提交给唯一写入线程顺序执行，相邻写操作合并为事务批量提交，彻底避免多线程并发写入 DuckDB 导致的锁表；封禁 / 白名单 / 账号封禁等高频查询走内存缓存（定期同步），查询性能显著提升

### 页面内搜索

* **就地搜索框（SiteSearch v8）**：**每个列表页使用自己的搜索框**（由 `templates/macros/search.html` 的 `inline_search()` 宏渲染），导航栏**不再放置**搜索输入框
* **点击搜索框即可展开**：点击搜索框任意位置（图标、文字或四周留白）都会展开，无需精准点中「搜索」文字
* **纯水平展开动画**：容器固定高度、无上下内边距，折叠态与展开态上下长度完全一致，展开只做左右伸缩，不会上下抖动
* **保持展开规则**：输入框内有文字 **或** 光标在输入框内 → 保持展开；无文字 **且** 失焦（点击外部）→ 平滑收起；Esc 一键清空并收起
* **结果就地渲染**：输入关键词后防抖（`220ms`）或回车，由搜索框在自身派发 `site-search` 事件；**各列表页监听该事件后直接刷新当前列表**，不再弹出下拉面板或独立搜索页，结果与页面风格完全一致
* **覆盖范围**：公共建筑 / 服务器指南 / 大喇叭音频三个列表页均支持就地搜索；关键词通过各列表 API 的 `q` 参数传入，匹配各自的标题/摘要/标签字段

### 服务器指南

* 卡片式列表页，支持置顶与按标题自动排序

* **指南搜索**：指南列表页顶部提供就地展开的搜索框（`inline_search` 宏）；列表 API `/api/guides/list` 与列表页均支持 `q` 关键词参数，按标题与摘要模糊匹配；列表接口**不返回正文 `content`**，仅返回标题、摘要等列表所需字段

* Markdown 详情页（标题锚点、代码一键复制）

* **富文本 / Markdown 统一编辑器**（全站唯一宏 `templates/macros/markdown_editor.html` + 引擎 `templates/static/js/pages/markdown-editor.js`）：
  * 默认「富文本（所见即所得）」模式，底层数据与保存内容**始终是 Markdown**，可视化界面只是渲染层；可一键无缝切换到「Markdown 源码 + 实时预览」模式，切换时内容与光标位置保留。
  * 工具栏按 **基础 / 段落 / 插入 三个常驻标签页**分类：基础（加粗/斜体/删除线/行内代码/清除格式）、段落（H1–H4/引用/无序/有序/任务列表/分割线/缩进）、插入（链接/代码块/表格）。
  * **上下文标签页**：另有「链接」「表格」两个标签页，仅在光标位于链接内、表格内（或刚点了「插入链接/表格」）时自动出现，离开对应上下文后自动隐藏并切回基础页。
  * **链接标签页**：可直接填写链接地址、显示文字、悬停标题与「新窗口打开」；**未选中文字时点击链接按钮会自动插入默认文字**（无需先选中文字）；提供独立「取消链接」按钮（仅保留文字、移除链接）。图片插入功能已移除。
  * **表格标签页**：增删行列 / 删除表格 / 当前列左中右对齐；插入表格后自动切到表格标签页，光标离开表格后自动收起。
  * **可切换样式**：再次点击已激活的样式按钮即**取消该样式**（加粗、斜体、删除线、行内代码、H1–H4、引用、任务列表等均支持「点一次加、再点一次取消」）；激活态高亮显示。
  * **按钮条件启用**：需选中文字的按钮（加粗等）仅在选中文字时亮起，表格按钮仅在光标位于表格内时亮起，否则置灰不可点。
  * **表格列宽拖拽（含移动端）**：拖拽表头列之间的手柄调整列宽，采用 Pointer Events 统一处理鼠标与触屏（`touch-action:none` + 指针捕获），移动端可正常拖动；结果**直接编码进 Markdown 表格分隔行的破折号数量**（列越宽该列破折号越多），往返编辑不丢失；表格对齐（左/中/右）同样映射到分隔行的 `:` 标记。
  * 支持全部标准 Markdown 语法的可视化编辑：标题、强调、行内代码、代码块（含语言）、引用、有序/无序/任务列表、链接、分割线、表格；Markdown 不支持的常见内联语义（`<sub>`/`<sup>`/`<mark>`/`<u>`/`<kbd>` 等）以原始内联 HTML 保留。
  * 与模板风格完全统一（白色磨砂玻璃、站点配色与字体），不引入任何第三方编辑器库或外部风格。

* 成员提交需审核，管理员直接发布

* 封禁机制（用户名/IP，限时或永久）

### 公共建筑

* 公共建筑列表页面，用户可发布自己的建筑（标题、领地名、介绍、使用方式、注意事项），**发布后进入待审核状态，管理员审核通过才公开**
* **搜索与标签**：列表页顶部提供就地展开的搜索框（`inline_search` 宏）；建筑列表 API `/api/buildings/list` 支持按标题与标签模糊搜索，标签可多选管理，列表默认**按收藏数量排序**；列表接口**不返回描述/使用方式/注意事项等正文**，仅返回列表所需字段（标题、领地名、标签、作者、收藏数、浏览数等）
* **收藏**：登录用户可收藏/取消收藏建筑，收藏数参与排序
* 一键复制传送指令 `/res tp 领地名`
* **浏览量统计**：访问建筑详情页时 `view_count` 自动 +1（作者本人访问不计入）；浏览数在列表卡片与详情页展示
* 评论功能：登录用户可发表评论，作者/管理员可删除评论；评论列表经 `GET /api/buildings/<id>/comments` 分段加载（每页条数由系统设置 `BUILDING_COMMENTS_PER_PAGE` 控制），滚动到列表底部自动加载下一页
* 举报功能：用户可举报违规建筑，管理员在后台可查看举报并删除建筑
* 接入防火墙内容检测、防刷机制和图形验证码

### 大喇叭音频

* 「大喇叭音频」板块：上传音频自动转码为 HLS（m3u8），生成 `http://<主机>/music/<编号>.m3u8` 播放链接；同时生成**唱片 MP3**（`http://<主机>/music/<编号>.mp3`），供游戏内「电脑」下载后烧录成唱片

* 支持 mp3 / wav / ogg / m4a / flac，单文件不超过 100MB（依赖 ffmpeg）

* 自动调用内置 ffmpeg：Windows 用 `scripts/ffmpeg/ffmpeg.exe`，Linux/macOS 用 `scripts/ffmpeg/ffmpeg`，未内置时回退系统 PATH 中的 `ffmpeg`

* **公开需审核**：申请公开的音频进入「待审核」，管理员通过后才在游戏内大喇叭展示；**驳回后音频自动转为私有**，用户可重新申请公开或删除；已公开转私有再申请公开需重新审核

* **私有仅「不公开列出」而非「限制访问」**：所有音频（含私有/待审核）均可**凭链接访问**（播放 m3u8 / 下载唱片 MP3 / 拉取 HLS 分片均无需登录，不再限制上传者或管理员），私有只表示该音频不会出现在公开音频列表中——上传者分享链接给任何人即可播放

* **审核结果邮件通知**：管理员通过/驳回公开申请后，自动向上传者邮箱发送磨砂玻璃风格的审核结果邮件（通过 / 未通过状态卡），邮件未启用或上传者无邮箱时自动跳过

* **公开音频列表整体走 API 获取**：公开音频列表**首屏 / 搜索 / 「加载更多」全部由前端调用 `GET /api/music/list` 获取**（页面仅渲染骨架，不再在服务端注入列表数据）；顶部搜索框为就地展开的 `inline_search` 组件，关键词同时匹配 `title` 与 `tags` 列，无结果时显示「没有找到匹配…的公开音频」

* **音频收藏**：公开音频列表 / 我的音频均提供「收藏」按钮，可收藏**别人上传的公开音频**，收藏后可在「我的收藏」页（`/music/my/favorites`）统一查看与播放；同一用户对同一音频仅一条收藏，重复点击即取消；删除音频时自动级联清理收藏记录

* **音频标签**：上传时可填标签（逗号分隔，自动去重、最多 10 个、每个 ≤12 字），「我的音频」与管理员后台可随时编辑（普通用户仅可编辑自己的，管理员可编辑任意），标签以金色徽章展示在音频卡片上，并参与搜索匹配

* 音频状态：私有 / 待审核 / 已公开（历史遗留的「已驳回」数据归并为私有），用户可在独立的「我的音频」页（`/music/my`）中查看并管理（播放链接、申请公开/转为私有、删除）

* **独立上传页与详细进度条**：上传入口跳转独立页面 `/music/upload`（`templates/music/upload.html` + `static/js/pages/music_upload.js`），异步上传并分两阶段展示进度条——文件上传百分比 + ffmpeg 转码进度条：`ffprobe` 探测音频时长，后台线程结合 ffmpeg `-progress` 文件输出（`out_time_us`）与 m3u8 已生成分片累计时长**双源计算真实百分比**并填充进度条（取两者较大值，避免快速转码时进度条跟不上；真实百分比未知时显示不确定态滑动动画，不再只有文字），成功后展示播放链接与唱片 MP3 链接，失败可一键重试

* **唱片 MP3 与源文件清理**：转码时一次生成 HLS 流与 192kbps 唱片 MP3（`libmp3lame` + ID3 标签），转码完成后**自动删除原上传音频源文件**与临时日志，目录内仅保留播放所需的 `index.m3u8`、`seg_*.ts` 与唱片 `index.mp3`；MP3 链接访问权限与 m3u8 播放链接一致（所有音频均可凭链接访问，私有仅表示不出现在公开列表）

* **复制时长（秒）按钮**：公开列表 / 我的音频 / 管理员审核队列中的每个音频都提供「时长 Ns」按钮，点击一键复制**以秒为单位的音频总时长**（如 `215`）；时长由 HLS 播放列表各分片 EXTINF 累计得出（`services/music_service.py` 的 `get_music_duration_seconds`），对所有音频（含历史数据）都适用，点击复制由 `static/js/core/base.js` 全局代理处理，Toast 提示已复制秒数

* 管理员可在后台审核公开申请、查看全部音频并一键下架（删除数据库记录并同步删除音频文件）

* 音频文件存放在 `uploads/music/<音频ID>/`，删除记录时自动清理对应目录，无文件残留

* **音频 ID 并发安全**：上传在持锁事务内完成数据库插入与 ID 读取（`with get_db()` + INSERT 后立即读 `lastrowid`），多用户同时上传也不会串号——文件目录名与数据库记录严格对应，播放链接与删除清理均可靠（修复历史并发上传导致编号错乱、无法播放、删除残留文件的问题）

* **ffmpeg 多线程转码**：上传转码统一加 `-threads` 参数（`FFMPEG_THREADS`），每个上传任务是独立 ffmpeg 子进程与独立输出目录，多用户同时上传天然并行，不会出现「文件正在使用」冲突

### 统一定时任务调度

* **统一任务注册模块（`core/shared/scheduler/`）**：全站所有定时执行功能的唯一入口（**防火墙除外**，防火墙保持独立实现）。任务按下次执行时间排序，注册表单线程每秒检测队首（最早到期）任务，到期即派发并检查下一个；派发不阻塞——执行走共享守护线程池（`pool`，默认）或独立守护线程（`thread`），任务执行期间从注册表取出、完成才重新入列，天然防重叠执行
* 两种调度模式：**固定间隔**（连续失败可按退避算法延长间隔）与**每日时间点**（`HH:MM`，支持配置热重载，当天至多执行一次，手动完成可跳过当天）
* 已接入：验证码清理、邮箱验证码清理、RCON 连接池清理、玩家列表追踪（含失败退避）、被驳回内容自动清理、每日 /uploads/ 全量 zip 备份、站点地图刷新、游戏服务器封禁到期自动解封、系统指标采样（CPU / 内存 / 网络速率）

### 服务器性能监控

* CPU 使用率、内存占用、网络上下行速率、运行时间

* 公开页面，无需登录即可查看

* 后台任务每 5 秒自动采集数据并缓存（`services/system_metrics/`，接入统一任务注册表），网络上下行速率在**服务端**由两次采样差值换算后缓存，前端直接读取，打开即有效（无需等待刷新一两次）

### Minecraft 在线玩家

* 通过 RCON 连接 Minecraft 服务器，实时获取在线玩家列表

* 后台线程每 5 秒执行 `/list` 命令，缓存结果

* 支持系统设置中配置 RCON 地址、端口、密码

### 申请服务器账号（导航分类）

* 主导航栏「导航」分类提供「申请服务器账号」入口（`/game-accounts/apply`），登录用户可申请注册 MC 游戏账号（需图形验证码）

* 提交后进入管理员审批队列，管理员在管理中心「账号注册申请管理」页批准/驳回申请、封禁恶意账号

* 已彻底移除游戏账号绑定/改密/解绑功能（**保留 RCON 服务**，用于在线玩家监控与申请审批后的白名单处理）

### 全站背景图片

* 上传图片自动转为 WebP 格式（保持自然宽高比，保存时写入数据库 `ratio` 列；LANCZOS 缩放），自动生成 768/1280/1920 三档响应式变体

* **缺失档位按需生成**：历史背景（开启响应式变体前上传）或变体生成失败时，请求的档位文件若不存在，服务端自动从主图按长边缩放生成并缓存为 WebP（不放大、原子写入、并发只生成一次），保证任意记录都能拿到与设备匹配的尺寸，不再一律回退主图

* **按屏幕比例最适配取图**：页面解析到背景元素后立即预加载（不等动画与其他脚本），自动获取屏幕宽高比与物理像素长边，携带 `size` + `ratio` 参数请求图片；服务端将所选档位中心裁剪到该比例后返回（结果缓存），横屏/竖屏均拿到与屏幕完全匹配且像素充足的图片，避免多余像素传输

* **支持一次上传多个图片文件**：拖放/选择批量上传，逐文件校验格式与大小，每个文件独立上传任务并聚合展示整体进度

* 上传文件统一命名为 `bg_<id>_<hash>.webp`，不再保留原始文件名，避免命名冲突

* 审核通过后自动启用为「当前显示」背景（同时取消其他背景激活状态），无需手动再开启

* 支持审核 / 驳回流程与审核结果邮件通知，管理员与上传者可预览未通过审核的图片

* **被驳回内容 24 小时自动删除**：被驳回超过 24 小时的服务器指南、背景图片等自动清理（删除数据库记录与关联本地文件，含背景主图与响应式变体）

### 文档系统

* Markdown 文档渲染（marked.js）

* 代码块一键复制按钮

* 侧边栏导航

## 配置说明

### 管理后台在线编辑（推荐）

所有运行时配置均可在 **管理后台 → 系统设置** 中在线编辑，修改后立即生效（热重载），无需重启服务器。

支持编辑的配置分类：

* **日志**：日志输出等级、是否打印日志到终端、是否存储防火墙模块日志

* **数据备份**：自动备份时间、保留份数、超时

* **Sitemap**：刷新时间、站点域名、多域名列表、搜索引擎爬虫策略（robots.txt：允许所有 / 仅主页 / 禁止所有）

* **安全配置**：会话有效期、登录失败锁定次数及时间

* **防火墙**：自动封禁总开关、封禁时长（分钟，0 为永久）、白名单、登录/注册/找回密码/邮箱验证码异常各自独立开关

* **可疑访问拦截**：总开关、封禁时长（分钟，0 为永久）、SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感文件与漏洞端点探测 / 恶意扫描 UA 各攻击类型独立开关

* **DDoS 防护**：总开关、检测强度（low=宽松 300 次/10 秒 / medium=中等 150 次/10 秒 / high=严格 80 次/10 秒）、首次封禁时长（分钟，0 为直接永久封禁）、永久封禁触发次数（违规记录时间窗口内多次触发自动升级永久封禁）、违规记录时间窗口（小时）

* **发布内容注入检测**：总开关、内容注入封禁时长（分钟，0 为永久封禁）

* **待审核数量限制**：总量上限 + 公共建筑 / 服务器指南 / 大喇叭音频 / 背景图片 单类型上限（0 = 不限制，管理员不受限制）

* **列表分页**：公共建筑 / 公共建筑评论 / 大喇叭音频 / 服务器指南 / 后台背景图片 / 后台账号申请 各列表每次加载条数（1–100，默认 5）。**分页大小仅可在此处或 `config.py` 修改，用户调用接口传入的参数一律被忽略**

* **外部链接**：卫星地图地址、QQ 群链接

* **邮件配置**：SMTP 服务器、端口、SSL、发件邮箱与授权码

* **背景图片**：显示开关、显示方式（cover/contain/auto）

* **网站图标**：favicon 图标选择（compass/mountain/star/heart），管理后台可在线切换

* **服务器配置**：监听地址、端口、调试模式、服务器工作线程数（Waitress；`0` 表示不限制，按 CPU 核数与可用内存智能推算）

* **RCON 配置**：服务器 RCON 地址/端口/密码、MC 游戏文件夹

* **网站备案**：工信部备案号、公安备案号、版权年份与站点名称

### config.py

| 配置项                           | 说明                                        | 默认值                                         |
| ----------------------------- | ----------------------------------------- | ------------------------------------------- |
| `DB_PATH`                     | 数据库文件路径                                   | `./uploads/db/site.db`                     |
| `UPLOAD_DIR`                  | 上传文件目录                                    | `./uploads`                                 |
| `UPLOAD_MUSIC_DIR`            | 大喇叭音频存放目录                                 | `./uploads/music`                           |
| `MUSIC_ALLOWED_EXTENSIONS`    | 大喇叭音频允许上传的格式                              | `mp3/wav/ogg/m4a/flac`                      |
| `FFMPEG_BIN`                  | 大喇叭音频转码用的 ffmpeg                          | 优先 `scripts/ffmpeg/ffmpeg(.exe)`，否则系统 PATH  |
| `FFPROBE_BIN`                 | 探测音频时长（转码进度百分比）用的 ffprobe                 | 优先 `scripts/ffmpeg/ffprobe(.exe)`，否则系统 PATH |
| `FFMPEG_THREADS`              | ffmpeg 音频转码线程数                            | `0`（自动按 CPU 核数）                             |
| `MAX_CONTENT_LENGTH`          | 最大上传大小                                    | 100 MB                                      |
| `BACKUP_DIR`                  | 备份根目录（支持绝对/相对路径，运行时可在后台热改）            | `../bhxz_backups`（项目上一级）                   |
| `SECRET_KEY`                  | Session 密钥                                | `mc_server_site_random_secret_key_2024`     |
| `REGISTER_VERIFY_CODE`        | 注册验证码                                     | `binhai_xz`                                 |
| `BACKUP_SCHEDULED_TIME`       | 每日自动备份时间                                  | `03:00`                                     |
| `MAX_BACKUPS`                 | 最大保留备份份数                                  | `30`                                        |
| `BUILDINGS_PER_PAGE`          | 公共建筑列表每页数量（1–100，接口传参无效）                 | `5`                                         |
| `BUILDING_COMMENTS_PER_PAGE`  | 公共建筑评论列表每页数量（1–100，接口传参无效）               | `10`                                        |
| `MUSIC_PER_PAGE`              | 大喇叭音频列表每页数量（1–100，接口传参无效）                | `5`                                         |
| `GUIDES_PER_PAGE`             | 服务器指南列表每页数量（1–100，接口传参无效）                | `5`                                         |
| `BACKGROUNDS_PER_PAGE`        | 后台背景图片列表每页数量（1–100，接口传参无效）               | `5`                                         |
| `GAME_ACCOUNTS_PER_PAGE`      | 后台游戏账号申请列表每页数量（1–100，接口传参无效）             | `5`                                         |
| `LOG_LEVEL`                   | 日志输出等级（DEBUG/INFO/WARNING/ERROR/CRITICAL） | `INFO`                                      |
| `LOG_CONSOLE_ENABLED`         | 是否将全局日志打印到终端（模块单独日志默认不打印，仅在「全局」开关打开时随此开关打印） | `1`（开启）                                    |
| `FAVICON_ICON`                | 网站图标（可选 compass/mountain/star/heart）      | `compass`                                   |
| `MAP_URL`                     | 卫星地图地址                                    | `https://map.bhxz.tw.kg`                    |
| `QQ_GROUP_URL`                | QQ 群链接                                    | 空                                           |
| `FIREWALL_WHITELIST`          | 封禁白名单（逗号分隔），白名单 IP 不会被封禁                    | `112.82.136.172`                            |
| `AUTO_BAN_ENABLED`            | 自动 IP 封禁总开关                                 | `1`（开启）                                    |
| `AUTO_BAN_DURATION_MINUTES`   | 自动封禁时长（分钟，0 为永久封禁）                          | `30`                                        |
| `SUSPICIOUS_BLOCK_ENABLED`    | 可疑访问拦截总开关（命中攻击特征自动封禁 IP）                    | `1`（开启）                                    |
| `SUSPICIOUS_BLOCK_DURATION_MINUTES` | 可疑访问封禁时长（分钟，0 为永久封禁）                    | `60`                                        |
| `SUSPICIOUS_BLOCK_SQLI_ENABLED` | SQL 注入拦截子开关                                       | `True`                                      |
| `SUSPICIOUS_BLOCK_XSS_ENABLED` | XSS 跨站脚本拦截子开关                                    | `True`                                      |
| `SUSPICIOUS_BLOCK_PATH_TRAVERSAL_ENABLED` | 路径穿越拦截子开关                           | `True`                                      |
| `SUSPICIOUS_BLOCK_COMMAND_INJECTION_ENABLED` | 命令注入拦截子开关                      | `True`                                      |
| `SUSPICIOUS_BLOCK_SENSITIVE_PROBE_ENABLED` | 敏感文件/漏洞端点探测拦截子开关               | `True`                                      |
| `SUSPICIOUS_BLOCK_MALICIOUS_UA_ENABLED` | 恶意扫描 UA 拦截子开关                        | `True`                                      |
| `DDOS_GUARD_ENABLED` | DDoS 防护总开关（超阈值自动封禁来源 IP） | `1`（开启） |
| `DDOS_GUARD_INTENSITY` | DDoS 检测强度（low=宽松 300 次/10 秒 / medium=中等 150 次/10 秒 / high=严格 80 次/10 秒） | `medium` |
| `DDOS_GUARD_BAN_MINUTES` | DDoS 首次封禁时长（分钟，0 为直接永久封禁） | `30` |
| `DDOS_GUARD_PERMANENT_AFTER` | 违规记录时间窗口内多次触发达到该次数后永久封禁（屡教不改） | `3` |
| `DDOS_GUARD_OFFENSE_WINDOW_HOURS` | 违规记录时间窗口（小时），超过后违规次数重新累计 | `24` |

### 环境变量

| 变量名          | 说明       | 默认值     |
| ------------ | -------- | ------- |
| `FIREWALL_WHITELIST` | 封禁白名单（逗号分隔） | `112.82.136.172` |
| `AUTO_BAN_ENABLED` | 自动 IP 封禁总开关 | `1`（开启） |
| `AUTO_BAN_DURATION_MINUTES` | 自动封禁时长（分钟，0 为永久） | `30` |
| `SUSPICIOUS_BLOCK_ENABLED` | 可疑访问拦截总开关 | `1`（开启） |
| `SUSPICIOUS_BLOCK_DURATION_MINUTES` | 可疑访问封禁时长（分钟，0 为永久） | `60` |
| `DDOS_GUARD_ENABLED` | DDoS 防护总开关 | `1`（开启） |
| `DDOS_GUARD_INTENSITY` | DDoS 检测强度（low/medium/high） | `medium` |
| `DDOS_GUARD_BAN_MINUTES` | DDoS 首次封禁时长（分钟，0 为永久） | `30` |
| `DDOS_GUARD_PERMANENT_AFTER` | 永久封禁触发次数 | `3` |
| `DDOS_GUARD_OFFENSE_WINDOW_HOURS` | 违规记录时间窗口（小时） | `24` |

### HTTPS / SSL

应用层**不再内置 SSL**，证书与 HTTPS 统一由**内网穿透 / 反向代理层**终结，应用自身仅监听 HTTP（默认 `0.0.0.0:5000`）。此时需在穿透 / 代理层配置证书，并把 HTTPS 流量回源到本应用的 HTTP 端口。

## API 接口

所有 JSON 接口统一收敛到 `api` 路由段：公开接口为 `/api/...`，管理后台接口为 `/admin/api/...`，不在业务路径中间插入 `api`（如不使用 `/music/api/list` 这类写法），返回 JSON。

### 公开接口

| 端点                             | 说明                        |
| ------------------------------ | ------------------------- |
| `GET /api/stats`               | 网站统计数据                    |
| `GET /api/server-status`       | 服务器实时状态（在线玩家/CPU/内存/网络）      |
| `GET /api/captcha/generate`    | 生成图形验证码                   |
| `POST /api/captcha/verify`     | 验证图形验证码                   |
| `POST /api/email/send-code`    | 发送邮箱验证码                   |
| `GET /api/email/check-enabled` | 检查邮件功能是否启用                |
| `GET /api/username/check`      | 注册页实时检测用户名是否可用            |
| `POST /api/verify-group-code`  | 校验注册用群内验证码                |
| `GET /api/verify-group-code/check` | 查询群内验证码是否已通过             |
| `GET /api/docs/list`           | 文档列表                      |
| `GET /api/docs/content/<file>` | 文档正文                      |

### 申请账号 API（需登录）

| 方法   | 路径                                   | 说明                 |
| ---- | ------------------------------------ | ------------------ |
| GET  | `/game-accounts/apply`               | 申请注册页面             |
| POST | `/api/game-accounts/apply-register`  | 提交注册申请（需图形验证码）    |
| GET  | `/game-accounts/ban-apply`           | 申请封禁页面             |
| POST | `/api/game-accounts/ban-apply`       | 提交封禁申请（需图形验证码）    |

### 申请账号管理 API（管理员）

| 方法     | 路径                                                   | 说明               |
| ------ | ---------------------------------------------------- | ---------------- |
| GET    | `/admin/game-accounts`                               | 游戏账号管理页面         |
| GET    | `/admin/api/game-accounts/applications`              | 获取注册申请列表         |
| GET    | `/admin/api/game-accounts/applications/list`         | 分页获取注册申请（每页条数由 `GAME_ACCOUNTS_PER_PAGE` 控制，可选 `status` 筛选） |
| POST   | `/admin/api/game-accounts/applications/<id>/approve` | 批准申请（自动 RCON 注册） |
| POST   | `/admin/api/game-accounts/applications/<id>/reject`  | 驳回申请             |
| GET    | `/admin/api/game-accounts/bans`                      | 获取封禁列表           |
| POST   | `/admin/api/game-accounts/bans`                      | 封禁账号申请资格         |
| DELETE | `/admin/api/game-accounts/bans/<username>`           | 解除封禁             |

### 管理后台列表 API（管理员，分页）

管理后台「用户 / 指南 / 音乐列表 / 背景图片 / 游戏账号申请」列表均为点击「加载更多」无刷新追加，页面路由仅渲染第 1 页；每页条数由系统设置「列表分页」分类下的对应配置项控制，接口不接受前端传入的数量参数。

| 方法 | 路径                                          | 说明                          |
| -- | ------------------------------------------- | --------------------------- |
| GET | `/admin/api/users/list`                     | 用户分页列表（`page`）              |
| GET | `/admin/api/guides/list`                    | 指南分页列表（`page`）              |
| GET | `/admin/api/music/list`                     | 音频分页列表（`type=all\|pending`，`page`） |
| GET | `/admin/api/firewall/bans`                  | 合并封禁列表（`page`）              |
| GET | `/admin/api/backgrounds`                    | 背景图片分页列表（`page`，可选 `status` 筛选） |
| GET | `/admin/api/game-accounts/applications/list` | 注册申请分页列表（`status=pending\|approved\|rejected\|all`，`page`） |

### 公共建筑 API（搜索 / 标签 / 收藏 / 评论）

公共建筑列表经 `GET /api/buildings/list` 无刷新搜索与分页加载（每页条数由 `BUILDINGS_PER_PAGE` 控制，接口不接受前端传入的数量参数），搜索关键词同时匹配标题与标签；列表默认按收藏数量排序。详情页评论经 `GET /api/buildings/<id>/comments` 分段加载（每页条数由 `BUILDING_COMMENTS_PER_PAGE` 控制，接口不接受前端传入的数量参数）。所有接口均纳入 API 防火墙计数。

| 方法   | 路径                                  | 说明                              |
| ---- | ----------------------------------- | ------------------------------- |
| GET  | `/api/buildings/list`                    | 搜索/分页列表（`q` 关键词、`tag` 标签、`page` 页码、`my=1` 我的建筑） |
| GET  | `/api/buildings/<id>/comments`           | 评论分段列表（`page` 页码，返回 `has_more` / `total`） |
| POST | `/buildings/<id>/favorite`          | 收藏 / 取消收藏（需登录）                  |
| POST | `/buildings/<id>/tags`              | 编辑标签（作者本人或管理员）                  |
| POST | `/buildings/<id>/comment`           | 发表评论（需登录）                       |
| POST | `/buildings/comment/<id>/delete`    | 删除评论（作者/建筑作者/管理员）               |
| POST | `/buildings/<id>/report`            | 举报建筑                            |

### 页面内搜索 API

各列表页的搜索框不调用独立聚合接口，而是由页面脚本监听 `site-search` 事件后就地调用对应列表 API（均通过 `q` 参数传关键词）：

| 方法  | 路径                   | 说明                                                    |
| --- | -------------------- | ----------------------------------------------------- |
| GET | `/api/buildings/list`     | 公共建筑列表（`q` 匹配标题与标签）                                   |
| GET | `/api/guides/list`   | 服务器指南列表（`q` 匹配标题与摘要）                                  |
| GET | `/api/music/list`    | 大喇叭音频列表（`q` 匹配名称与标签）                                  |

### 服务器指南 API

| 方法  | 路径                   | 说明                                                    |
| --- | -------------------- | ----------------------------------------------------- |
| GET | `/api/guides/list`   | 指南列表（`page` 页码、`my=1` 我的指南、`q` 关键词匹配标题与摘要；每页条数由 `GUIDES_PER_PAGE` 控制） |

### 大喇叭音频 AJAX 端点

| 方法   | 路径                                 | 说明                              |
| ---- | ---------------------------------- | ------------------------------- |
| GET  | `/api/music/list`                  | 公开音频列表（`q` 关键词匹配名称与标签、`page` 页码；每页条数由 `MUSIC_PER_PAGE` 控制，接口不接受前端传入的数量参数）；公开列表页首屏 / 搜索 / 加载更多均调用此接口 |
| POST | `/music/upload`                    | 开始异步上传（返回 `{task_id}`，转码在后台执行）  |
| GET  | `/music/upload/progress/<task_id>` | 查询上传/转码进度（JSON）                 |
| GET  | `/music/<id>.mp3`                  | 下载唱片 MP3（游戏内烧录唱片；权限同 m3u8 播放链接） |
| POST | `/music/<id>/toggle`               | 申请公开 / 转为私有                     |
| POST | `/music/<id>/delete`               | 删除音频（本人或管理员）                    |
| POST | `/music/<id>/favorite`             | 收藏 / 取消收藏（仅已公开音频，需登录）           |
| POST | `/music/<id>/tags`                 | 编辑音频标签（本人或管理员，需登录）              |
| GET  | `/music/my/favorites`              | 我的收藏页（需登录）                      |

## 前端特性

### 白色磨砂玻璃效果（White Frosted Glass）

* **白色页面 + 黑色控件**：`#f3f6fa` 浅色底色搭配 `#1a2230` 深色正文、`#0284c7`（蓝）/`#7c3aed`（紫）强调色，按钮、输入框、导航栏均为深色控件，白色磨砂玻璃卡片承载内容

* **真实酸蚀刻玻璃质感**：`background: linear-gradient()` 渐变背景替代纯色，模拟光线透过玻璃的漫射效果

* `backdrop-filter: blur(28px) saturate(140%)` — 玻璃卡片高通透，自然融入浅色背景

* 高透明度 `rgba(255,255,255,0.74)` 背景 + 光线散射伪元素（`radial-gradient` 模拟漫射光）

* 边缘光晕伪元素（`mask-composite` 渐变边框，模拟玻璃切割面折射）

* 全局细微噪点纹理（SVG `feTurbulence`），模拟蚀刻玻璃表面微观散射

* **桌面端悬停下拉导航栏**：大屏端（≥1024px）主导航为「首页 / 导航 / 服务器互动 / 账号」，其中「导航 / 服务器互动 / 账号」为悬停下拉菜单（CSS 过渡动画，`cubic-bezier` 弹性曲线流畅展开）；小屏端保持右侧滑出菜单不变

* **邮件模板同款磨砂玻璃**：`templates/emails/base.html` 统一白色磨砂玻璃卡片（背景光晕 + 噪点纹理 + 光线散射层 + 顶部高光描边 + 状态卡），验证码 / 指南审核 / 音频审核 / 广播邮件共用同一外层与样式

* **自定义音频播放器（磨砂玻璃风格）**：大喇叭音频列表（`/music`）、我的音频（`/music/my`）、管理员审核页（`admin/admin_music.html`）均使用自研播放器替代浏览器默认控件，含进度条（点击/拖动 seek、缓冲显示，**圆点（thumb）跟随进度实时移动**）、倍速（0.5x~2x）、音量（按钮+滑块弹层，音量记忆在 localStorage）与播放/暂停，窄屏（≤480px）自动占满整行，且倍速/音量弹层窄屏时改为右对齐，避免超出卡片/视口被裁切；每个 `.music-player` 独立实例化并拥有独立的 HLS 实例与 `Audio` 元素，同一时间只允许一个播放器出声，列表内多个音频均可独立播放；样式见 `static/css/base.css` 的 `.music-player`（倍速/音量弹层 `z-index:100` 向上展开；内含播放器的卡片使用 `.pixel-card.music-card` 显式解除 `contain:paint`/`content-visibility` 的溢出裁切，弹层不被遮挡/裁切），逻辑见 `static/js/pages/music_player.js`，HLS 播放依赖本地 `static/lib/hls/hls.min.js`（构建脚本 `scripts/build/build_static.py` 自动下载）

* **全站响应式适配所有屏幕**：竖屏/窄屏（≤640px）下音频卡片操作按钮组（复制广播 m3u / 唱片 MP3 / 时长 Ns / 审核操作）通过 `.music-card-actions` 自动占满整行并换行排列，不再横向溢出被裁切导致「穿模」、无法点击；全局 `body` 增加 `overflow-wrap: break-word` 兜底长文本换行，配合 `overflow-x: clip` 杜绝横向滚动；小屏端导航使用右侧滑出菜单，大屏端使用悬停下拉导航，管理员数据表格统一 `overflow-x-auto` 横向滚动、指南/文档 `pre/table` 自带横向滚动，全站各页面均可适配任意屏幕尺寸

* **模板宏复用**：`templates/macros/music_macros.html` 提取音频状态徽章、复制广播 m3u 链接按钮、复制唱片 MP3 按钮、复制时长（秒）按钮、自定义播放器（`music_audio_player`）与播放器脚本（`music_player_assets`）为公共宏，`music/list.html`、`music/my.html` 与 `admin/admin_music.html` 统一调用，消除重复代码

* **统一弹窗模板系统**：`templates/macros/modal.html` 提供 `modal_overlay`（CustomModal 骨架）、`modal_shell`（页面级弹窗容器，支持尺寸/图标/颜色自定义）、`modal_captcha`（图形验证码弹窗）、`modal_close_script`（全局 `openModal`/`closeModal` 控制器）四组宏，配合 `base.js` 的 `CustomModal`（alert/confirm/prompt）统一全站所有弹窗样式，取代全部原生 `alert`/`confirm`/`prompt` 及手写弹窗；图形验证码弹窗改为**按需加载**（见下文「前端资源按需加载」）

* **统一标签列表输入框**：`templates/macros/forms.html` 的 `tags_field()` 宏 + `base.js` 的 `TagInput` 模块，提供全站统一的「列表类」输入体验——输入一项后回车或点「添加」即新增一个标签，已添加标签以胶囊展示、点叉号即可删除，支持粘贴「a, b, c」自动拆分；底层始终用一个隐藏 input 保存**逗号分隔字符串**，与后端解析、表单提交完全兼容（零迁移成本）。建筑发布 / 建筑详情编辑标签 / 音频上传 / 音频标签编辑等所有列表输入均已统一使用该控件，用户无需再手动输入逗号分隔；全局「编辑标签」弹窗（`#tag-edit-modal`）复用同一控件供各场景调用

### 交互效果

| 效果       | 实现方式                                                                                                                                                 |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 鼠标光晕跟随   | `requestAnimationFrame` 平滑插值                                                                                                                         |
| 按钮水波纹    | CSS `ripple` 动画                                                                                                                                      |
| 滚动淡入     | `IntersectionObserver`                                                                                                                               |
| 页面过渡     | `requestAnimationFrame` 控制 `.page-ready` 类切换                                                                                                         |
| 统一弹窗系统  | 磨砂玻璃风格，CSS 过渡动画 + 全局 `openModal`/`closeModal` 控制；CustomModal 提供 alert/confirm/prompt（Promise + 回调双风格），自动拦截 `onsubmit="return confirm(...)"` 表单；`modal_shell` 宏支持页面级内容弹窗，全站无原生弹窗 |
| Toast 提示 | 四种类型（success/error/warning/info）                                                                                                                     |

### 性能优化

* **零外部依赖**：所有 CDN 资源（Lucide、Marked.js）下载到本地，无外部网络请求

* **前端资源按需加载**：页面级内容通过 `base.html` 的独立块按需引入，避免每个页面都加载用不到的资源——
  * 图形验证码弹窗（`modal_captcha`）由全站固定渲染改为 `captcha_modal` 块，**仅注册 / 找回密码 / 建筑发布 / 指南投稿 / 账号申请等需要验证码的页面加载**；
  * `purify.min.js` 由 `<head>` 移至页面底部脚本，且**仅在 Markdown 渲染页引入**（不再阻塞首屏）；
  * `uploader.js` / `search.js` 通过 `page_scripts` 块仅在实际上传页 / 搜索页加载；
  * 移除 `admin/broadcast.html` 中重复引入的 `base.js`（已在 `base.html` 全局加载），避免重复执行与拉取旧版本。

* **本地自定义字体（站酷庆科黄油体 + 站酷快乐体）**：正文与标题分别使用本地子集化 woff2（`lib/fonts/zcool-*-*.woff2`），按 `unicode-range` 分片 + `font-display: swap`，浏览器只下载页面实际用到的子集，无外部 CDN 请求；字体缺失时自动回退系统字体栈

* **分段列表滚动自动加载**：所有分段加载列表（公共建筑 / 公共建筑评论 / 大喇叭音频 / 服务器指南 / 后台各列表）的「加载更多」按钮带 `data-autoload-more` 属性，`base.js` 用 `IntersectionObserver` 监听——按钮进入视口即自动点击加载下一页；按钮隐藏 / 禁用时不触发，加载后按钮被新内容推出视口，滚动到底再次自动加载，始终只自动加载后面的内容

* `overflow-x: clip` 替代 `hidden`（消除滚动回弹）

* 尊重 `prefers-reduced-motion`（无障碍用户自动禁用动画）

* 触控设备降级光晕效果

* `IntersectionObserver` 触发后立即 `unobserve`

### 静态资源与引用规则

#### 静态资源更新

当升级第三方库版本时：

1. 修改 `scripts/build/build_static.py` 中的版本号
2. 运行 `python scripts/build/build_static.py` 重新下载
3. 提交 `templates/static/lib/` 目录到 Git（`templates/static/lib/monaco/` 除外）

#### 添加新的外部资源

1. 在 `scripts/build/build_static.py` 中添加下载函数
2. 在模板中使用 `url_for('static', filename='lib/...')` 引用
3. 确保更新前已运行构建脚本

#### 引用规则

所有静态资源必须通过 `url_for('static', filename='...')` 引用，禁止硬编码路径或外部 CDN URL。

## 部署

部署方式、构建静态资源、打包发布详见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

* 内置 Waitress WSGI 服务器，`python app.py` 即可独立运行（生产级多线程）

* HTTPS 由内网穿透 / 反向代理层终结，应用自身仅监听 HTTP

* 生产环境推荐前置 Nginx 反向代理，且必须关闭缓冲以支持 SSE 长连接

* 构建、打包与发布流程见 [DEVELOPMENT.md 构建与发布](docs/DEVELOPMENT.md)

* 一键更新机制原理见下文 [一键更新机制](#一键更新机制)

## 架构

> 本文档描述项目的**架构分层、目录结构与技术栈**。代码编写与部署发布规范见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

### 架构分层

项目严格遵循 **MVC 式分层架构**，各层职责互不重叠：

```
app.py ──→ routes/ ──→ services/ ──→ core/
  │            │            │            │
  │         HTTP 层     业务逻辑层    基础设施层
  │            │            │            │
  Flask    蓝图/路由   纯 Python 函数    DB/认证/防火墙
             │            │
         main/        user/（auth / profile）
         docs/        game_accounts/（registration_service）
         public/      music/（constants / queries / crud / upload / favorites）
         admin/       rcon/（client / pool / easy_auth）
         api/         mail/（service / verification / templates / sanitize）
         guides/      updater/（config / core）
         buildings/   backup/（manager / scheduler）
         backgrounds/ background_service/（背景图片业务）
         sitemap/     cleanup_service/（被驳回内容自动清理）
         community/   settings_manager/（系统设置管理）
                      sitemap_cache/（Sitemap 缓存）
                      monitoring/（系统性能监控）
                      logging/（日志自动清理）
```

| 层级     | 目录          | 职责                                              | 禁止                                |
| ------ | ----------- | ----------------------------------------------- | --------------------------------- |
| **入口** | `app.py`    | Flask 实例、蓝图注册、WSGI 服务器                          | 不得包含业务逻辑                          |
| **路由** | `routes/`   | HTTP 请求解析、参数校验、Session 管理、响应构造                  | 不得包含 SQL、事务、业务逻辑                  |
| **核心** | `core/`     | 数据库连接、认证装饰器、中间件、CSRF、服务器入口、共享工具（验证码/IP/限流/调度器/错误页/模板上下文/页面渲染） | 不得包含业务逻辑，不导入 services |

### 目录结构

```
workspace/
├── app.py                    # Flask 入口 + WSGI 服务器
├── config.py                 # 全局配置
├── requirements.txt          # Python 依赖
├── update.py                 # 一键更新脚本
├── core/                     # 核心基础设施层（含共享工具，不含业务逻辑）
│   ├── db/                   #   数据库连接与 schema
│   ├── system/               #   系统层：日志、启动检查、应用初始化
│   │   ├── init.py, logger.py, startup_checks.py
│   ├── shared/               #   共享工具（原 utils 收敛于此）
│   │   ├── ip.py, captcha.py, ratelimit.py, validation.py
│   │   ├── process_utils.py
│   │   └── scheduler/        #   统一任务注册表（task / executors / registry）
│   ├── auth.py               #   认证装饰器、密码哈希
│   ├── csrf.py               #   CSRF 防护
│   ├── middleware.py          #   请求中间件（安全标头、攻击扫描）
│   ├── server.py             #   WSGI 服务器与优雅关闭
│   ├── helpers.py            #   页面渲染辅助（render_page / admin_page）
│   ├── template_context.py   #   全局模板上下文注入
│   └── errors.py             #   统一错误页渲染（error_simple）
├── services/                 # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/               #   数据备份（/uploads/ 全量 zip 极限压缩）
│   ├── buildings/            #   公共建筑（列表/搜索/收藏/评论分页）
│   ├── email/                #   异步邮件发送
│   ├── game_accounts/        #   游戏账号注册申请
│   ├── monitoring/           #   系统监控（CPU/内存/系统/性能追踪）
│   ├── music/                #   大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/                 #   RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── updater/              #   自动更新（配置/核心逻辑）
│   ├── user/                 #   用户（认证/资料/管理）
│   ├── background_service/   #   背景图片业务（WebP 转换 + 响应式变体）
│   ├── cleanup_service/      #   被驳回内容自动清理（统一定时调度）
│   ├── firewall/             #   高性能防火墙（DuckDB 引擎 + WSGI 门禁 + DDoS 防护）
│   │   ├── __init__.py       #     公共 API re-export（ban_ip / firewall 单例等）
│   │   ├── api_guard.py      #     接口频率限制（每 IP 每分钟）
│   │   ├── service/          #     业务层：core（封禁/白名单/警告）/ database（DuckDB）/ monitor（后台监控）
│   │   ├── protection/       #     防护策略：content_filter（内容注入）/ ddos / file_guard
│   │   └── transport/        #     连接层：wrappers（WSGI 门禁，直接断开连接）
│   ├── settings_manager/     #   系统设置管理
│   ├── sitemap_cache/        #   Sitemap 缓存服务
├── routes/                   # HTTP 路由层
│   ├── main/                 #   首页、登录、注册、设置、音乐
│   ├── admin/                #   管理后台（用户/备份/设置/日志/更新/游戏账号/指南/音乐/广播/背景/公共建筑等）
│   ├── api/                  #   JSON API（性能/统计/验证码/邮箱）
│   ├── backgrounds/          #   背景图片页面
│   ├── community/            #   社区辅助（AJAX / 表单统一响应）
│   ├── docs/                 #   文档页面
│   ├── game_accounts/        #   申请账号（页面+API，纯申请注册）
│   ├── guides/               #   服务器指南（页面+API）
│   ├── public/               #   公开文件服务
│   └── sitemap/              #   站点地图 & robots.txt
├── templates/                # Jinja2 模板（命名规范见 docs/DEVELOPMENT.md）
│   ├── admin/                #   管理后台页面（无 admin_ 前缀）
│   ├── auth/                 #   登录 / 注册 / 找回密码
│   ├── settings/             #   用户个人设置
│   ├── site/                 #   站点级信息页（站点文档、服务器状态）
│   ├── backgrounds/          #   背景图片页面（index / upload）
│   ├── emails/               #   邮件模板（独立 loader）
│   ├── game_accounts/        #   游戏账号页面（apply / ban_apply）
│   ├── guides/               #   服务器指南页面（index / detail / form）
│   ├── buildings/            #   公共建筑（index / create / detail）
│   ├── music/                #   大喇叭音频页面（index / my / favorites / upload）
│   ├── macros/               #   通用模板宏（模态框/编辑器/进度条/音乐/页面内搜索）
│   ├── static/               #   静态资源（CSS/JS/本地化第三方库，构建生成 lib/）
│   └── ...                   #   根级：base.html / index.html / error_simple.html
├── docs/                     # 项目文档
└── scripts/
    ├── build/                #   构建脚本
    └── ...                   #   工具脚本
```

### 技术栈

| 类别       | 选型                            |
| -------- | ----------------------------- |
| 后端框架     | Flask 3.x                     |
| WSGI 服务器 | Waitress（内置，生产级多线程）           |
| 数据库      | SQLite（WAL 模式，嵌入式单文件）         |
| 模板引擎     | Jinja2                        |
| CSS      | Tailwind CSS + 自定义样式（白色磨砂玻璃） |
| 图标       | Lucide（本地化）                   |
| Markdown | marked.js / Python Markdown   |

### 异步架构

| 组件      | 异步方式                               |
| ------- | ---------------------------------- |
| 日志写入    | 统一入口 `_emit()`：追加写文件 + 内存环形缓冲（全局 / 严重错误 / 模块三类） |
| 统一任务注册表 | 单 tick 线程每秒检测 + 共享线程池派发（`core/shared/scheduler/`，全站定时任务共用，防火墙除外） |
| IP 地理信息 | 后台线程异步更新缓存                         |
| CPU 监控  | 后台线程定期采样（2 秒）                      |

### 数据库

使用 **SQLite**（嵌入式单文件数据库），启用 **WAL 模式**（`PRAGMA journal_mode=WAL`）+ `synchronous=NORMAL` + `busy_timeout=30000`，读写并发性能优秀且崩溃可恢复；单例共享连接 + 可重入锁保证多线程安全。首次启动自动建表，共 19 张表：

> ⚠️ **切勿删除 `uploads/db/site.db-wal` 与 `site.db-shm`。**
> WAL 模式下，「已经 `commit` 成功、但尚未 checkpoint 合并进主库」的数据全部保存在 `-wal` 文件里。删除它 = 丢掉最近写入的数据（曾导致「公共建筑审核通过后重启服务器又变回待审核」）。
> SQLite 打开数据库时会自动重放 WAL 完成恢复，最后一个连接关闭时也会自动 checkpoint 并清理，无需任何人工干预。

| 表名                        | 说明       | 关键约束                                                                                                            |
| ------------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `users`                   | 用户       | `username` 唯一, `email` 唯一                                                                                       |
| `mod_intros`              | 模组介绍     | `link` 模组跳转链接（可空），首页卡片带链接时可点击新窗口跳转                                                                                  |
| `db_backups`              | 备份记录     | 状态/大小/耗时                                                                                                        |
| `settings`                | 系统设置     | key 唯一，支持热重载                                                                                                    |
| `public_paths`            | 公开文件路径   | 路径唯一                                                                                                          |
| `server_guides`           | 服务器指南    | 支持 Markdown，审核工作流                                                                                               |
| `guide_edit_bans`         | 编辑封禁     | 用户名/IP，限时/永久                                                                                                    |
| `broadcast_logs`          | 广播邮件日志   | —                                                                                                               |
| `music`                   | 大喇叭音频    | `status` 状态机（0=私有/1=待审核/2=已公开，驳回后自动转为私有；旧库 `gain` 列仅保留不再使用），`tags` 逗号分隔标签列，删除记录时同步删除 `uploads/music/<ID>/` 文件目录 |
| `music_favorites`         | 大喇叭音频收藏  | 联合主键 `(user_id, music_id)`（同一用户对同一音频仅一条收藏）                                                                      |
| `backgrounds`             | 背景图片     | `status` 审核状态，WebP 格式，响应式变体，`rejected_at` 记录驳回时间（超 24h 自动删除）                                            |
| `game_account_registrations` | 游戏账号注册申请 | 申请注册 MC 账号，管理员审批                                                                                               |
| `game_account_bans`       | 游戏账号封禁   | 封禁 MC 账号申请资格                                                                                                    |
| `game_server_ban_applications` | 游戏服务器封禁申请 | 用户申请 → 管理员审批 → RCON ban，到期自动 pardon                                                                             |
| `public_buildings`        | 公共建筑     | 标题/领地名/介绍/使用方式/注意事项，审核工作流（pending→approved/rejected）                                                        |
| `building_comments`       | 建筑评论     | 外键 `building_id`，支持作者/管理员删除                                                                                       |
| `building_reports`        | 建筑举报     | 外键 `building_id`，待处理→驳回流程                                                                                         |
| `building_favorites`      | 建筑收藏     | 联合主键 `(user_id, building_id)`                                                                                   |
| `guide_favorites`         | 指南收藏     | 联合主键 `(user_id, guide_id)`                                                                                      |

#### 数据备份

每日凌晨 3:00（可配置）自动执行：

1. 扫描 `/uploads/` 目录下所有文件 → 极限压缩打包为 zip（ZIP_DEFLATED, level 9）→ 校验 zip 完整性 → 清理旧备份
2. **数据库以「一致快照」写入 zip**（`uploads/db/`）：主站 SQLite（`site.db`）用在线备份 API 导出，WAL 中「已提交但未 checkpoint」的数据会一并合并进快照；防火墙 DuckDB（`firewall.duckdb`）用引擎级导出（`ATTACH` + `COPY FROM DATABASE`）。运行期的 `-wal` / `-shm` / 原始 `.duckdb` 文件不直接复制（正被独占锁定且状态不一致），其数据已全部包含在快照里，恢复时单文件即可独立使用。

管理后台可手动触发，显示实时进度条；备份目录（`BACKUP_DIR`）支持在「系统设置」或「数据备份」面板设置**绝对路径或相对路径**（相对路径基于网站根目录解析，默认 `../bhxz_backups`），更改后新备份将写入新目录，旧备份自动迁移。已取消一键解压恢复功能，历史备份仅作留存与下载。

### 一键更新脚本

项目根目录下提供了一键更新脚本 [`update.py`](update.py)，纯 Python 全平台兼容，**只走下载覆盖**（不依赖 git），启动即更新、无需确认：

1. 运行 `python update.py`（可选 `--branch dev` 指定分支，默认 `main`，失败自动回退 `master`）
2. 脚本**多线程同时测速**全部镜像源（24 个：官方直连 / codeload / 前缀型代理 / 主机替换型镜像），单个镜像 2 秒超时，**整个测速环节最多 2 秒**；优先选取能返回合法 ZIP 且速度最快的镜像
3. 自动下载最新源码 ZIP（含 PK 魔数与 CRC 完整性校验，可识别镜像返回的 HTML 错误页），逐个镜像 × 逐个分支回退重试
4. 解压后**合并覆盖**项目代码（`_merge_copy`：同名覆盖、目标多余文件保留），随后进入第 5 步统一清理
5. **清理「GitHub 上已被删除」的文件与目录**：合并覆盖只会新增/覆盖，反映不了「新版删除」，故覆盖完成后按最新 ZIP 的文件清单递归清理——被移除的文件会删除、被移除的目录会整棵删除（例如更换字体后，旧字体的 woff2 子集一并清掉，不再残留）。`PROTECTED_PATHS` 中的路径**强制跳过、绝不删除**，包括：
   - 用户数据：`uploads/`（音频、背景图、sitemap，数据库也在 `uploads/db/`）
   - 运行期数据 / 本地配置：`db`、`backups`、`logs`、`ssl`、`release`、`.env`、`.env.local`、`.git`、`.venv`、`node_modules`
   - 本地生成物：`templates/static/lib/monaco`、`scripts/ffmpeg`（运行期下载，`.gitignore` 已排除）
   - 本地启动脚本：`start.bat`（未提交到仓库，本地自建）
   - 任意层级：`__pycache__`、`.pytest_cache`、`node_modules`、`.DS_Store`、`Thumbs.db`
6. 自动安装/更新 Python 依赖
7. **更新完成后提示手动重启服务器，不会自动启动**

> 字体等静态资源已随代码提交进仓库（`templates/static/lib/fonts/`），因此一键更新即可同步字体，服务器无需联网构建、也无需额外步骤。
> ⚠️ 清理以「最新 ZIP 里的文件清单」为准：**既未提交到仓库、又不在保护名单内**的本地文件会被当作「已删除」而移除。请勿把自建脚本/资源直接放在项目目录下，放到 `uploads/` 等受保护目录即可。
> 镜像路径按各源格式正确拼接：前缀型代理为 `<代理前缀>https://github.com/<repo>/archive/refs/heads/<branch>.zip`，主机替换型为 `https://<镜像域名>/<repo>/archive/refs/heads/<branch>.zip`。
> 如果遇到依赖变化，更新后执行 `pip install -r requirements.txt`。

### 安全要点

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 图形验证码服务端内存存储，一次性删除防重放
5. Session Cookie 启用 `HttpOnly` + `SameSite=Lax`（HTTPS 下自动加 `Secure`）
6. 邮箱唯一性检查（一个邮箱仅可注册一个账号）
7. IP 频率限制（注册/登录）
8. **全站安全响应标头**（`core/web/middleware.py` 集中下发，覆盖 HTML/API/SSE/静态资源）：

   * `Content-Security-Policy`：仅允许本站脚本/样式/资源，禁用 `object`，限制 `form-action`/`frame-ancestors` 等（已放行内联脚本/样式与 HLS blob worker，避免误伤自身功能）

   * `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`（防点击劫持）

   * `Referrer-Policy: strict-origin-when-cross-origin`（防 Referer 泄露）

   * `Permissions-Policy`：默认禁用摄像头/麦克风/定位/传感器等，仅放行本域剪贴板写入

   * `Cross-Origin-Opener-Policy: same-origin`（跨源隔离，防 Spectre 类窗口攻击）

   * `Strict-Transport-Security`（HSTS）：**仅 HTTPS 请求下发**，避免 HTTP 部署被强制升级而无法访问

9. **极高性能多线程防火墙**（`services/firewall/`，运行于 WSGI 入口、先于一切 Flask 逻辑）：黑名单 IP 的请求不参与任何业务处理，**直接断开连接且不返回任何数据**（`FirewallWSGIWrapper` 抛出 `waitress.channel.ClientDisconnected`，waitress 捕获后关闭连接、不写任何响应字节，客户端读到 0 字节后连接断开）；后台监控线程周期性从数据库同步黑名单镜像；配套 DDoS 攻击检测按强度自动封禁（详见上文功能特性）。

## 开发注意事项

编写新代码前必查的**分层规范、易错点清单与测试要求**，详见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 更新日志

详见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 最近更新

* **统一编辑器交互优化 + 统一标签输入框 + 前端资源按需加载**（`templates/macros/markdown_editor.html`、`templates/static/js/pages/markdown-editor.js`、`templates/macros/forms.html`、`templates/static/js/core/base.js`、`templates/base.html` 等）：
  * **编辑器**：移除编辑器下方的「所见即所得」提示与「插入图片」功能；工具栏改为「基础 / 段落 / 插入」三个常驻标签页 + 「链接」「表格」两个**上下文标签页**（点击链接/表格按钮或光标进入链接/表格时出现，离开即隐藏）。链接改为独立标签页，可直接设置地址、显示文字、悬停标题、新窗口打开，并新增**取消链接**；**未选中文字时点链接按钮自动插入默认文字**。表格插入后自动切到表格页、离开自动收起。**再次点击已激活的样式按钮即取消该样式**（加粗/斜体/删除线/行内代码/标题/引用/任务列表等）。表格列宽拖拽改用 **Pointer Events + 指针捕获**（`touch-action:none`），**修复移动端无法拖动列宽的问题**。
  * **统一标签输入框**：新增 `tags_field()` 宏与 `base.js` 的 `TagInput` 模块，所有列表类输入（建筑标签、音频标签、音频标签编辑等）统一改为「回车/点添加新增、胶囊叉号删除」，不再需要用户手动以逗号分隔；底层仍保存逗号分隔字符串，后端零改动。
  * **前端资源按需加载**：图形验证码弹窗改为 `captcha_modal` 按需块（仅验证码页面加载）、`purify.min.js` 移出 `<head>` 且仅在 Markdown 页加载、移除 `admin/broadcast.html` 重复引入的 `base.js`。

* **修复 Waitress 下「逐跳标头」导致的 500（实时日志流 + 封禁响应）**（`routes/admin/logs/__init__.py`、`core/middleware.py`）：日志页 `/admin/api/logs/stream`（SSE 实时日志）反复报 `AssertionError: Connection is a "hop-by-hop" header; it cannot be used by a WSGI application (see PEP 3333)`、实时日志无法推送。原因是 `Connection` 属 PEP 3333 禁止 WSGI **应用**下发的逐跳标头，旧版 Cheroot 容忍、Waitress 会直接抛错（SSE 此前写 `Connection: keep-alive`、封禁响应写 `Connection: close`）。现移除这两处 `Connection` 标头——HTTP/1.1 默认即持久连接，长连接由服务器维护，无需应用声明。

* **数据备份纳入数据库完整快照 + DuckDB 关键索引自愈**（`services/backup/manager/__init__.py`、`services/firewall/service/database.py`）：`/uploads/` 全量 zip 备份原先跳过 `-wal` / `-shm` / `.duckdb`（运行期独占锁定），导致备份里**没有可用数据库**。现改为备份时生成**一致快照**写入 zip：主站 SQLite 用**在线备份 API**（WAL 中已提交数据一并合并，单文件即可独立恢复）、防火墙 DuckDB 用**引擎级导出**（`ATTACH` + `COPY FROM DATABASE`，规避文件锁定）。另修复 DuckDB ART 索引在异常退出后可能与数据行不一致、导致「解封静默失败」的问题——初始化时自动重建 `firewall_bans(ip_address)` 与 `firewall_account_bans(user_id)` 两个关键索引实现自愈。

* **修复 Waitress 剥离代理头导致的「DDoS 防火墙再次失效」**（`core/server.py`、`core/shared/ip.py`）：Waitress 3.x 默认 `clear_untrusted_proxy_headers=True`，会在请求进入应用前**剥离来自非可信来源的 `X-Forwarded-For` / `X-Forwarded-Proto` / `X-Real-IP` 等代理头**。内网穿透 / 反向代理正是靠这些头传递客户端真实 IP，被剥离后 `REMOTE_ADDR` 恒为回环地址，防火墙会把所有外部请求当作本机访问而跳过 DDoS 计数与黑名单拦截（Session Cookie 的 `Secure` 判断同样失效）。现于 `create_server()` 显式设置 `clear_untrusted_proxy_headers=False`，把代理头的可信性判断交回应用自身（`is_trusted_proxy` 只采信回环 / 内网 / `TRUSTED_PROXIES` 转发的头，公网直连伪造的头一律忽略）。同时修正 `is_public_ip()` 对 IPv4-mapped IPv6（`::ffff:1.2.3.4`）的误判——此前首字符为 `:` 会被当成内网地址，进而被当作可信代理采信其伪造的代理头。实测：真实 Waitress 服务下第 151 次请求（10 秒内超过 150 次）即触发封禁，后续连接被直接断开（0 字节响应）。

* **服务器工作线程数可配置 + 热加载**（`core/server.py`、`config.py`、`routes/admin/firewall/__init__.py`、`templates/admin/firewall.html`）：原 `WORKER_THREADS=4` 改为 `WAITRESS_THREADS=100`（Waitress 实际工作线程数上限，`0` 表示不限制，按 CPU 核数与可用内存智能推算 32~512）；「系统设置」与「防火墙设置」修改的是同一项配置，保存后通过 `apply_thread_count()` 调 `task_dispatcher.set_thread_count()` **即时热加载**，无需重启服务器。

* **Waitress 内部日志改写到「waitress」模块单独日志**（`core/system/logger.py`）：接管 waitress 的 `logging` 日志器，把 `Task queue depth is xx` 等内部记录转发进「waitress」模块独立缓冲（默认不落盘、不并入全局日志，可在「日志页面 → 日志设置」开启），不再刷屏。验证码清理日志（`清理过期验证码 N 个`）同样改走「captcha」模块单独日志。

* **修改用户名支持实时可用性检测**（`routes/main/auth/__init__.py`、`services/user/auth/__init__.py`、`templates/settings/index.html`）：新增 `exclude_self=1` 参数，检查时排除当前登录账号自身（填成自己现在的用户名不算被占用），前端交互与注册页一致（防抖查询、可用/不可用状态提示、未通过检查时阻止提交），服务端写入时仍会再次校验。

* **前端资源按需加载**（`templates/base.html` 及列表页 / 详情页）：`uploader.js`、`search.js`、`purify.min.js` 由全站加载改为通过 `page_scripts` / `extra_head` 块**仅在实际用到的页面加载**；移除重复的 favicon `rel="alternate icon"` 链接，避免一次请求取两遍服务器图标。

* **修复触屏设备导航栏动画卡顿**（`templates/static/js/pages/main.js`、`templates/static/css/base.css`）：触屏端的鼠标光晕改用 `requestAnimationFrame` 合并 DOM 写入（避免每个 `touchmove` 都触发一次合成，与导航栏 `backdrop-filter` 抢占合成资源）；移动菜单增加 `will-change: transform, opacity` 与 `backface-visibility: hidden` 独立合成层。动画外观与时长完全不变。

* **修复加入 QQ 群链接始终指向当前页**（`routes/main/pages/__init__.py`）：首页 `qq_group_url` 默认值改为读取 `QQ_GROUP_URL` 配置，不再因默认空串而回落到当前页面地址。

* **全面改用 Waitress 生产服务器 + 移除应用层 SSL**（`core/server.py`、`requirements.txt`、`app.py`、`core/middleware.py`、`startup_checks.py`）：WSGI 服务器由 Cheroot 迁移到 **Waitress**（生产级多线程，工作线程数由 `WAITRESS_THREADS` 配置、默认 100，其余 `connection_limit=1000` / `channel_timeout=300`），启动方式与对外端口不变；**删除应用层全部 SSL 功能**（`ENABLE_SSL` 环境变量、`ssl/` 证书目录、Cheroot `BuiltinSSLAdapter`、HTTPS 强制跳转与相关启动检查），HTTPS 改由内网穿透 / 反向代理层统一终结，应用仅监听 HTTP；防火墙不再依赖服务器私有连接对象，被拦截请求通过抛出 `waitress.channel.ClientDisconnected` 由 Waitress 关闭连接、**不写任何响应字节**。Session Cookie 的 `Secure` 标志改由 `_ProxyAwareSessionInterface` 按可信代理下发的 `X-Forwarded-Proto` 动态决定（HTTPS 访问自动开启、本地 HTTP 直连自动关闭）。

* **服务器状态页网络监控改为「服务端采样缓存」**（`services/system_metrics/`、`routes/api/public/__init__.py`、`templates/site/server_status.html`）：新增后台采样服务（每 5 秒采样 `psutil` 的 CPU / 内存 / `net_io_counters()`），在服务端用相邻两次采样的累计字节差换算上行 / 下行速率并写入内存缓存；`/api/server-status` 新增 `net_up` / `net_down` 速率字段，页面**打开即显示速率**（不再需要等一两次刷新），`formatBytes` 单位补充 `TB`。

* **修复 DDoS 防护失效与攻击后报错（防火墙真实 IP / 白名单 / SQLite 并发 / 模板空值）**：
  * **穿透环境下 DDoS 统计与封禁失效**（`services/firewall/transport/wrappers.py`、`core/shared/ip.py`）：网站经 natfrp 内网穿透对外服务，外部请求的 `REMOTE_ADDR` 恒为本机回环地址，而 WSGI 门禁此前硬编码放行回环 IP，导致攻击请求既不计入 DDoS 窗口也不被黑名单拦截。现于 WSGI 层解析真实客户端 IP：仅当直连来源为可信代理（回环 / 内网地址，或 `config.py` 的 `TRUSTED_PROXIES`）时才采信 `X-Forwarded-For` / `X-Real-IP` 等头部，取链路中**最右侧公网 IP**；公网直连一律忽略代理头，防止伪造头部绕过防护。
  * **删光白名单后默认 IP 仍被永久放行**（`services/firewall/service/database.py`、`services/firewall/service/core.py`）：白名单缓存此前读取 `config.py` 的常量而非设置，且「移除」只删 DuckDB 表——硬编码默认 `112.82.136.172` 被缓存同步反复加回，删不掉、删光后攻击仍不被拦截。现改为读取设置值并区分「未配置」（回退默认基线）与「清空」（真正清空），白名单页面的「移除」同步清理设置，删除即时生效。
  * **攻击后报 `sqlite3.InterfaceError: bad parameter or other API misuse`**（`core/db/connection.py`）：跨线程共享的单连接 + SQLite 预处理语句缓存，并发执行相同 SQL 时相互 `reset` 触发该错误并导致全站 500。现关闭语句缓存（`cached_statements=0`），24 线程 × 4000 次查询压测 0 错误。
  * **建筑详情页报 `TypeError: 'NoneType' object is not subscriptable`**（`templates/buildings/detail.html`）：日期字段为 `None` 时取切片报错，补 `or ''` 兜底。

* **修复背景图不按屏幕大小取图（`templates/base.html`）**：此前用 `max(视口宽, 视口高) × devicePixelRatio` 计算目标像素再取「不小于它的最小档位」，导致手机（390×844@3x → 2532）、平板（2360）、1366 笔记本（1366）等**几乎所有设备都被算成 1920 档**，768 / 1280 两档形同虚设——任何设备拿到的都是同一张主图；且尺寸只在页面解析时计算一次，缩放窗口、手机旋屏后永不重新取图。现改为按**屏幕 CSS 长边**取「不小于它的最小档位」（全屏背景由半透明遮罩覆盖，无需按物理像素取图），并监听 `resize` / `orientationchange`（300ms 防抖）在视口变化后自动改取当前最合适的档位与裁剪比例。实测：iPhone SE → 768、iPhone 14 → 1280（竖屏 ratio 0.46 / 横屏 2.16）、iPad → 1280、1366 及以上桌面 → 1920。

* **一键更新自动清理已删除文件（`update.py`）**：合并覆盖只会新增/覆盖文件，无法反映「GitHub 上已删除」，导致换字体后服务器上旧字体的 woff2 子集长期残留。现覆盖完成后按最新 ZIP 清单**递归清理**过时文件与整个被移除的目录；`PROTECTED_PATHS` 中的路径强制跳过、绝不删除——`uploads/`（含数据库）、`db`、`backups`、`logs`、`ssl`、`release`、`.env`、`.git`、`.venv`、`node_modules`、`templates/static/lib/monaco`、`scripts/ffmpeg` 等运行期数据与本地生成物都在保护名单内。同时移除了上一版针对字体目录的临时清理代码。`start.bat` 等本地自建启动脚本也加入保护名单，不会被误删。

* **字体换成站酷活泼字体 + 终端日志配色调整**：
  * **正文改用站酷庆科黄油体、标题改用站酷快乐体**：替换此前的霞鹜文楷——正文（含导航、按钮）改用 **ZCOOL QingKe HuangYou（站酷庆科黄油体）**，圆润活泼且笔画简洁；`h1/h2/h3`（及 `.font-display` / `.font-title`）改用 **ZCOOL KuaiLe（站酷快乐体）**，更俏皮有活力。两者均取自 npm 包 `@fontsource/*`（本地镜像），`scripts/build/build_static.py` 下载后按 `unicode-range` 展开约 93 个子集（**只落地 CSS 实际引用的子集**，包内自带的 2.4MB 整包文件不会写入仓库），仍为本地零 CDN；构建脚本新增**废弃字体文件自动清理**（本轮清掉 194 个旧霞鹜文楷子集），避免换字体后旧文件长期残留。
  * **终端日志配色调整**（`core/system/logger.py`）：`[INFO]` 改为**绿色**（`\033[92m`），`[DEBUG]` 恢复**原色**（终端默认前景色，不再着色）；`WARNING` / `ERROR` / `CRITICAL` 维持黄 / 红 / 加粗红不变，仍只给等级标签着色、不整行着色。

* **音频播放 404 自愈 + 自定义字体 + 终端日志彩色标签**：
  * **HLS 播放改为「点击才加载」+ 错误退避重试**（`static/js/pages/music_player.js`）：hls.js 设置 `autoStartLoad: false`，页面加载不再预取分片，避免列表页一次性发起大量分片请求而出现成片瞬时 404；新增致命错误分级处理——媒体错误走 `recoverMediaError()`，网络类错误（清单/分片加载失败）按 700ms×次数退避自动重试（最多 3 次），瞬时 404 可自愈；**修复「一次报错就永久锁死播放按钮」的问题**，重试耗尽后仅提示错误态，用户再次点击播放会重新加载清单，不再始终无法播放。分片缺失时后端 `routes/main/music/__init__.py` 记录 WARNING（含音频 ID / 分片名 / 标题 / IP）便于定位磁盘上确实缺失的文件。
  * **新增本体内置字体 LXGW WenKai（霞鹜文楷）**：`scripts/build/build_static.py` 新增下载 `lxgw-wenkai-webfont` 并生成按 `unicode-range` 分片的本地 `woff2` 子集与 `fonts.css`；`base.html` / `base.css` 字体栈正文优先使用 `LXGW WenKai`（标题 / 按钮仍优先 `JetBrains Mono`），缺失时回退系统字体栈，全程零外部 CDN。
  * **终端日志彩色高亮**（`core/system/logger.py`）：仅给 `[DEBUG]/[INFO]/[WARNING]/[ERROR]/[CRITICAL]` **标签**着色（不整行着色），配色与网页日志页 `LEVEL_COLORS` 一致（灰/蓝/黄/红/加粗红）；自动探测终端是否支持 ANSI（含 Windows 虚拟终端开启，支持 `NO_COLOR` / `FORCE_COLOR` 覆盖）；颜色只作用于控制台，日志文件与内存缓冲始终保持无颜色纯文本。

* **就地搜索框交互优化（SiteSearch v8）**：点击搜索框任意位置即可展开（不再需要点中「搜索」文字）；展开动画改为纯水平伸缩，折叠/展开两态上下长度一致、不再上下抖动；移除尾部箭头按钮（搜索仍由输入防抖与回车触发）。

* **修复备份报错与启动残留问题**：
  * **备份跳过被锁定的 DuckDB 文件**：`services/backup/manager` 新增备份跳过规则（`.duckdb` / `.duckdb.wal` / `.duckdb.tmp` 及 SQLite 的 `-wal` / `-shm` / `-journal`）。DuckDB 运行期对主库文件持有独占锁，Windows 下读取会 `Permission denied (Errno 13)`；现改为备份前统一跳过并汇总为一条 INFO 日志，不再报 WARNING。
  * **启动自愈清理废弃目录**：`core/system/startup_checks.py` 在模块导入检查前清理旧版本残留的 `routes/firewall/` 目录，修复「`cannot import name 'record_spam'`」导入误报（在线更新为覆盖式，不会删除上游已移除的旧文件）。
  * **不再自动创建 `./backups`**：从启动检查的必需目录中移除 `backups`，备份目录统一由可配置项 `BACKUP_DIR`（默认 `../bhxz_backups`）决定。

* **删除「发布频率限制」功能 + 修复配置表自增 ID 空耗**：
  * **删除发布频率限制**：移除 `services/firewall/protection/spam.py`（内存计数 + 超限自动封禁）及全部调用点——公共建筑发布、建筑评论、服务器指南发布/编辑、大喇叭音频上传、背景图片上传、后台邮件广播；防火墙设置页移除「发布频率限制」板块，`FIREWALL_CONFIG_KEYS` 与保存接口同步移除全部 `SPAM_LIMIT_*` 配置项。同时清理底层残留：`services/firewall/service/core.py` 移除已无调用方的 `record_spam` / `get_spam_log` / `get_user_spam_count` / `clear_spam_log`，`services/firewall/service/database.py` 移除 `firewall_spam_log` 表与 `seq_firewall_spam_log` 序列。
  * **修复配置表自增 ID 空耗**：`settings` 表原先用 `INSERT ... ON CONFLICT(key) DO UPDATE` 保存，SQLite 在走「更新」分支时仍会消耗一个 `AUTOINCREMENT` ID（实测 23 行配置把计数器推到 500）。改为「先 UPDATE，未命中再 INSERT」，重复保存不再消耗 ID。

* **待审核数量限制（总量 + 单类型）+ 防火墙设置面板卡片化**：
  * **发布数量限制 → 待审核数量限制**：原「发布数量限制」改为对**待审核状态内容数量**的限制，并支持**总量上限 + 单类型上限**双重校验（先达到者先生效），任一上限设为 `0` 表示不限制，管理员不受限制。
  * **配置入口**：`config.py` 的 `SETTINGS_REGISTRY` 新增 `MAX_PENDING_CONTENT`（总量）、`MAX_PENDING_BUILDING` / `MAX_PENDING_GUIDE` / `MAX_PENDING_MUSIC` / `MAX_PENDING_BACKGROUND`（单类型），并可在**管理后台 → 防火墙 → 设置**在线热改。
  * **校验逻辑**：重写 [`core/helpers.py`](core/helpers.py) 的 `check_pending_limit(user, content_type=None)`，按 `_PENDING_TYPES` 统一统计公共建筑（`pending`）/ 服务器指南（`pending`）/ 大喇叭音频（`status=1`）/ 背景图片（`status=0`）的待审核数量；修复原实现对 `music` / `backgrounds` 误用 `author_id` 列的问题。
  * **接入发布流程**：公共建筑发布（`routes/buildings/pages`）、服务器指南发布（`routes/guides/pages`）、大喇叭音频上传申请公开（`routes/main/music`）与私有转公开（`services/music/crud`）、背景图片上传（`routes/backgrounds/pages`）均按对应类型校验。
  * **防火墙设置面板整理**：设置页所有配置按板块重构为统一的卡片式布局（与「发布内容注入检测」样式一致）——IPv6 拦截 / 自动 IP 封禁 / 可疑访问拦截 / DDoS 防护 / 发布内容注入检测 / **待审核数量限制（新增）**。

* **移除一次性迁移 / 清理临时代码**：最新版已完整启动过一次，所有一次性迁移与清理逻辑已完成使命，全部删除，避免长期携带历史包袱：
  * **防火墙数据库迁移**：删除 `services/firewall/service/database.py` 的 `_LEGACY_DB_PATH` / `_migrate_legacy_db()`（旧路径数据已搬到 `uploads/db/firewall.duckdb`）。
  * **启动废弃模块清理**：删除 `core/system/startup_checks.py` 的 `_cleanup_obsolete_modules()` 与 `_OBSOLETE_MODULE_DIRS`（残留目录已清理，启动检查不再删除任何文件）。
  * **配置键名迁移**：删除 `core/system/startup_checks.py` 的 `_migrate_settings()`（旧键 `IP_BAN_WHITELIST` 已迁移为 `FIREWALL_WHITELIST`）。
  * **旧数据库 / 旧备份目录迁移**：删除 `core/db/connection.py` 的旧 `site.db` 迁移与 `services/backup/manager` 的 `_migrate_old_backups()` / `_rewrite_backup_paths()`。
  * **数据库表删除**：删除 `core/db/schema.py` 中的 `game_account_bindings` 与讨论区三表 `DROP TABLE` 逻辑。
  * **历史列 / 状态迁移**：删除 `add_column_if_not_exists()` 及全部调用、music `is_public → status` 迁移、`server_guides.rejected_at` 回填——相关列（`users.login_attempts` / `locked_until`、`game_account_bans.user_id`、`music.tags`、`backgrounds.ratio` / `rejected_at`）已直接内联进 `CREATE TABLE` 建表语句，新装库自带、老库此前已补齐。
  * **独立迁移脚本**：删除 `scripts/migrate_db/`（DuckDB → SQLite 迁移）与 `scripts/uploads/`（一次性清理迁移脚本）。

* **防火墙数据库重启不丢 + 项目结构分层优化 + 日志设置独立页面**：
  * **修复防火墙数据库重启后全部丢失**：`services/firewall/service/database.py` 数据库路径原先经多层 `os.path.dirname` 计算，迁移后层级变深导致实际写入 `services/uploads/db/`（代码目录，不在备份范围、更新时被覆盖）。现改为基于 `APP_ROOT` 直接指向 `uploads/db/firewall.duckdb`（与主站 SQLite 同目录，随站点备份并受更新排除保护）。
  * **项目结构分层优化**：跨业务的基础能力统一放入 `core/`（日志 `core/system/logger.py`、监控 `services/firewall/service/monitor.py`、调度 `core/shared/scheduler/`）；有业务语义的模块放入 `services/`——安全扫描从 `core/shared/security_scanner.py` 迁至 `services/security/`，防火墙完整下沉至 `services/firewall/`（`service/` 业务层、`protection/` 防护策略、`transport/` 连接层、`api_guard.py`），`routes/firewall/` 只保留 HTTP 路由入口、实际逻辑全部调用服务层，全站导入同步更新。
  * **修复部分模块单独日志仍打印到全局日志**：排查确认各模块统一走 `log_module()` 接口、模块设置 `LOG_MODULE_*_GLOBAL` 均关闭后，确保模块单独日志仅写入独立缓冲与文件，不混入全局日志（控制台 / `logs/app.log` / SSE）。
  * **日志设置改为独立页面**：从日志查看页弹窗重构为独立页面 `/admin/logs/settings`（`templates/admin/log_settings.html`），按模块展示「存储 / 全局」开关并即时保存，日志查看页改为链接跳转。

* **修复启动时「9 个模块导入失败」误报（废弃模块残留一次性清理）**：现象是启动日志出现 `routes.admin.discussion`、`routes.discussion`、`services.discussion`、`services.attachment_service` 等模块 `cannot import name 'UPLOAD_ATTACHMENTS_DIR' from 'config'`。这些功能已在上一版彻底删除，报错源自**文件同步只覆盖不删除**在本地遗留的旧模块目录（`.py` 已被删除但目录仍在，启动扫描时被导入）。`core/system/startup_checks.py` 曾新增一次性的 `_cleanup_obsolete_modules()`：按精确路径（`routes/discussion`、`routes/admin/discussion`、`routes/community/pages`、`services/discussion`、`services/attachment_service`）幂等删除废弃残留目录（含 `__pycache__`）；**该一次性清理步骤已在后续版本移除**。

* **彻底删除讨论区功能 + 建筑评论改分段加载 + 分段列表滚动自动加载**：
  * **删除讨论区**：移除 `routes/discussion/`、`services/discussion/`、`templates/discussion/`、`routes/admin/discussion/`、`templates/admin/discussion.html` 与 `discussion_categories.html`，以及数据库表 `discussion_categories` / `discussion_topics` / `discussion_replies`（旧库的一次性 `DROP` 已随后移除）；同步清理导航栏讨论入口、系统设置「讨论区配置」及 `DISCUSSION_REFRESH_INTERVAL` / `DISCUSSION_TOPICS_PER_PAGE` / `REPLIES_PER_PAGE` 配置项、`templates/macros/upload.html` 与 `services/attachment_service/`；并删除仅供讨论附件使用的死代码——社区蓝图与其 `/uploads/<filename>` 附件下载路由、`UPLOAD_ATTACHMENTS_DIR` / `UPLOAD_COMMUNITY_DIR` 配置与 `uploads/attachments`、`uploads/community` 遗留目录，无残留。
  * **建筑评论分段加载**：新增 `GET /api/buildings/<id>/comments`（分页由 `BUILDING_COMMENTS_PER_PAGE` 控制，返回 `has_more` / `total`），详情页评论区改为 API 分段加载，删除原实时刷新逻辑。
  * **分段列表滚动自动加载**：`base.js` 新增 `initAutoLoadMore`——任何带 `data-autoload-more` 的「加载更多」按钮进入视口即自动点击一次加载下一页（隐藏 / 禁用时不触发，加载后按钮被新内容推出视口，滚动到底继续加载）。

* **修复大喇叭音频管理页「待审核公开申请」标题后原样显示 HTML 文本**：`templates/macros/page_header.html` 的 `section_title` 宏以 `{{ extra }}` 输出 `extra` 参数，在 Jinja 自动转义下把 `templates/admin/music.html` 传入的 `<span data-pending-count ...>` 标签当成纯文本渲染，页面出现「待审核公开申请 `<span ...>0</span>`」。现改为 `{{ extra | safe }}` 按 HTML 渲染（`extra` 由模板开发者提供、非用户输入，且仅此一处使用），待审核数量角标正常显示。

* **防火墙拦截与授权拒绝的 403 均不写入防火墙模块日志**：`ip_ban_check_hook`（IP 封禁兜底）与 `suspicious_request_check_hook`（可疑访问拦截）返回 403 时**直接不调用日志函数**（删除原通用 `after_request` 钩子 `log_403_response`，不再需要任何布尔标记）；授权拒绝类 403（权限不足 / CSRF 校验失败等）同样不写防火墙日志。仅保留 IP 封禁 / 自动封禁等封禁动作日志（`可疑访问自动封禁生效` / `自动封禁生效`），被封 IP 反复请求不再刷屏。

* **日志页面支持多来源查看 + 按模块配置日志行为 + 启动自动清理**：日志页面（`/admin/logs`）顶部新增「日志来源」下拉，可切换查看**全局日志 / 严重错误日志 / 任意模块单独日志**（`source=global|fatal|module:<名称>`，全局走 SSE 实时推送，其余来源 3 秒轮询）；新增「日志设置」面板，列出所有已注册模块并各自提供「存储」（落盘到 `logs/modules/<模块名>.log`）与「全局」（并入全局日志：控制台 + `app.log` + SSE）两个开关，实时保存即时生效（`GET/POST /admin/api/logs/modules`）。**模块单独日志的行为不再由模块注册写死**——`register_module_log(name)` 只声明存在，是否落盘、是否并入全局一律由设置 `LOG_MODULE_<模块名>_STORE` / `_GLOBAL` 决定（因此从「系统设置」移除，统一收到日志页）；默认落盘仅保留图形验证码 / 邮箱验证码 / 注册 / 登录，全部默认不并入全局。**每次启动自动清理日志**：`purge_logs_on_startup()` 在应用初始化最开始清空全局日志文件与缓冲、严重错误日志文件、所有 `logs/modules/*.log` 与各模块缓冲，保证每轮启动都从干净状态开始（`core/system/init.py`）。

* **图形验证码 / 邮箱验证码 / 注册账号 / 登录账号改为模块单独日志**：这四类日志不再进入全局日志（控制台 / `logs/app.log` / 全局缓冲 / SSE），改为在各自模块启动时注册独立日志器（`register_module_log`），并用统一入口 `log_module(name, level, event, detail, **kwargs)` 输出到独立内存缓冲并默认落盘到 `logs/modules/{captcha,email_code,register,login}.log`。注册位置：图形验证码 [routes/api/captcha/\_\_init\_\_.py](file:///workspace/routes/api/captcha/__init__.py)、邮箱验证码 [routes/api/email_code/\_\_init\_\_.py](file:///workspace/routes/api/email_code/__init__.py)、注册与登录 [services/user/auth/\_\_init\_\_.py](file:///workspace/services/user/auth/__init__.py)（「找回密码」仍为全局日志）。新增设置项 `LOG_MODULE_CAPTCHA_STORE` / `LOG_MODULE_EMAIL_CODE_STORE` / `LOG_MODULE_REGISTER_STORE` / `LOG_MODULE_LOGIN_STORE`，均默认开启、可在系统设置热切换并即时生效。

* **修复系统设置页下拉选择框被裁切 + 开关无法切换**：`templates/admin/settings.html` 动态生成的分类卡片带有 `overflow-hidden`，会把自绘下拉 `.custom-select-dropdown`（绝对定位，`z-index:2000`）裁掉，导致选项被遮挡/看不全；同时开关容器缺少全局开关脚本依赖的 `data-switch` 属性（`base.js` 只对 `[data-switch]` 生效），点击与键盘都无法切换。现移除卡片 `overflow-hidden`（标题栏补 `rounded-t-2xl` 保持顶部圆角），并为开关补上 `data-switch`，下拉可完整展开、开关可正常切换并触发自动保存。

* **修复防火墙设置页所有开关显示为关闭且无法点击切换**：`templates/admin/firewall.html` 设置区 15 个开关的 Jinja 表达式被误写成 `{ { ... } }`（多一个空格，Jinja 不识别而原样输出为文本），导致 `is-on` 类与 `aria-checked` 从未正确渲染，无论实际配置为何一律显示为关闭；同时这些开关缺少全局开关脚本依赖的 `data-switch` 属性（`base.js` 只对 `[data-switch]` 生效），点击/键盘均无法切换。现已全部改为标准 `{{ ... }}` 并补上 `data-switch`（并修掉内容注入拦截开关 `else '' else ''` 的语法错误），开关按实际配置正确回显、可正常切换；`/admin/firewall/settings/save` 的布尔键集合补入 `CONTENT_INJECTION_BAN_ENABLED`。

* **防火墙从路由层迁至服务层 + 修复「服务器正常启动但完全无法访问」**：防火墙模块由 `routes/firewall/` 迁至 `services/firewall/`（`service/` 业务层、`protection/` 防护策略、`transport/` 连接层；原路径保留 shim 转发，所有外部 `from routes.firewall.xxx import` 零改动）。迁移中 `BanFilterConnection.communicate()` 误把返回 `(banned, reason)` **元组**的 `is_banned(ip)` 当布尔判断——非空元组恒为真，导致**每个 TCP 连接都被判定为黑名单并在请求解析前强制断开**，表现为进程/端口正常监听、日志无任何报错但所有请求均无响应；已改为显式解包 `banned, _reason = is_banned(ip)` 后再判断，实测 `/`、`/favicon`、`/api/stats`、`/login` 全部返回 200。

* **修复 robots.txt 的 Sitemap 域名错误 + 邮件模板路径 + 指南编辑 500**：`/robots.txt` 的 `Sitemap:` 原先写死站点配置域名（`https://bhxz.tw.kg/sitemap.xml`），访问 `https://binhai.cloud/robots.txt` 时地址不一致。`routes/sitemap/__init__.py` 新增 `_robots_base_url()`：优先匹配与当前 `Host` 一致的已配置域名（`SITE_URL` / `SITEMAP_DOMAINS`），未匹配则直接反映当前访问域名，确保 Sitemap 始终指向当前域名下的 `/sitemap.xml`（`services/sitemap_cache` 同步新增 `base_url_for_host()`）。修复邮件发送 `TemplateNotFound: 'verification_code.html'`——`services/mail/templates/__init__.py` 的模板目录层级少算一级，指向了不存在的 `services/templates/emails`，已修正为项目根 `templates/emails`。修复 `/guides/<id>/edit` 提交 500（`NameError: get_client_ip`）——`routes/guides/pages/__init__.py` 漏导入 `get_client_ip`，已补上并全站排查同类漏导入。

* **评论与发布全面 API 化 + 上传进度统一**：删除评论确认改为网页内弹窗（`CustomModal.confirm`，替代原生 `confirm`）；**发布评论不再需要图形验证码**；公共建筑发布/评论等发布操作统一走无刷新 `AjaxForm`（自动携带身份与 CSRF）；新增统一上传组件 [`uploader.js`](templates/static/js/core/uploader.js)（`FilePicker` / `UploadProgress` / `AjaxForm`），所有文件上传均带进度条。

* **修复 `/buildings/<id>` 页面 500（`modal_shell is undefined`）+ 规范 Jinja2 宏导入**：`templates/buildings/detail.html` 原先用 `{% include 'macros/modal.html' %}` 引入弹窗宏，而 `include` 只渲染模板文件、**不会把宏注入当前命名空间**，导致访问公共建筑详情页时 `modal_shell is undefined` 直接 500。改用 `{% from 'macros/modal.html' import modal_shell, modal_close_script %}` 显式导入，并统一放在 `{% extends %}` 之后、第一个 `{% block %}` 之前；同步修正 `admin/guides.html`、`admin/firewall.html`、`admin/broadcast.html`、`admin/guide_form.html`、`auth/register.html`、`guides/form.html` 的宏导入位置，并修正 `admin/buildings.html` 拒绝弹窗把标题误传为 `size` 参数的问题。开发准则（`docs/DEVELOPMENT.md`）新增「宏导入方式（`import` 而非 `include`）」章节，并已用脚本对全站模板做语法编译 + 宏调用/导入一致性校验（0 处未导入）。

* **修复管理员删除用户失败 + 清理废弃代码**：修复管理后台删除用户时因引用已删除的 `poll_votes`、`board_topics`、`board_replies` 表导致数据库操作失败的问题，改为级联清理相关业务表；同步修复用户注销功能的相同问题，修复 `_clean_user_attachments` 函数引用废弃表的问题；优化 `routes/admin/mod_intros/__init__.py` 中三处嵌套 try-except 屎山代码为单层。

* **防火墙迁移至路由层 + 公共建筑去审核 + robots.txt 安全增强**：防火墙模块从 `core/firewall/` 整体迁移至 `routes/firewall/`（路由层，更合理的分层），所有导入引用同步更新；公共建筑**发布即公开**，彻底移除管理员审核流程（删除 approve/reject 路由、模板按钮、仪表盘统计），管理员 403 问题一并修复；全站验证码统一使用 `core.shared.captcha.captcha_service` 单例；robots.txt 路由升级为函数式生成，根据策略自动附加 Crawl‑delay（5 秒）与敏感路径 Disallow 规则，配合 DDoS 防护的 `/robots.txt` 白名单，防止合法爬虫被防火墙误封；更新所有过期注释引用。

* **修复公共建筑验证码与防火墙增强**：修复公共建筑发布页验证码提交无反应（脚本块 `extra_js`→`extra_script` 匹配+阻止默认提交）；发布页「验证并提交」按钮触发图形验证码弹窗，通过验证后自动提交表单；建筑评论新增图形验证码验证，提交前弹出验证码弹窗；防火墙设置页新增「发布频率限制」配置区域（公共建筑/建筑评论/话题/回复/指南/背景/音乐等 7 种内容类型均可独立配置次数与检测窗口），settings API 支持所有频率限制项热保存；`core/firewall/spam.py` 新增 `get_spam_limit()` 函数优先读取系统设置动态配置。

* **数据库迁移至 `uploads/db/` + 备份改为全量 zip 极限压缩**：`db/` 文件夹整体移至 `uploads/db/`，所有路径引用更新；备份方式由 SQLite 在线备份改为扫描 `/uploads/` 目录下全部文件，使用 ZIP_DEFLATED+level 9 极限压缩打包为 zip，存放于 `backups/uploads/`；管理后台备份页面同步更新，支持一键解压恢复、进度条与历史管理。

* **统一任务注册模块（`core/shared/scheduler/` 包）**：全站所有定时执行功能的唯一入口（**防火墙除外**，防火墙保持独立实现）。任务按下次执行时间排序（`ScheduledTask`），注册表单线程（`TaskRegistry`）**每秒检测队首最早到期任务**，到期即取出派发并继续检查下一个；派发走 `TaskExecutor` 两种后台执行方式（`pool` 共享守护线程池 / `thread` 独立守护线程），**tick 线程永不阻塞**；任务执行期间从注册表取出、完成才重新入列，**天然防重叠执行**；基于 `time.monotonic()` 计时，不受系统时间跳变影响。保留两种调度模式：固定间隔（连续失败按 `backoff_factor/backoff_max` 退避）与每日时间点 `HH:MM`（支持配置热重载、当天去重、`mark_done()` 手动跳过当天）。8 个既有定时任务（验证码清理、邮箱验证码清理、RCON 连接池清理、玩家列表追踪、被驳回内容自动清理、每日数据库备份、站点地图刷新、游戏服务器封禁到期自动解封）全部迁移到注册表，行为与原逻辑一致；删除旧 `core/shared/scheduler.py`。全局 API：`register_task / unregister_task / start_task_scheduler / stop_task_scheduler`

* **新增 DDoS 攻击防护与极高性能多线程防火墙**：`core/firewall/` 在 WSGI 入口（先于一切 Flask 逻辑）拦截黑名单 IP，命中即返回最小 403 并利用 Cheroot 连接特性（`linger=False` + `close()`）强制关闭其现存连接（含 keep-alive 空闲与处理中的请求），客户端表现为连接被重置而非收到页面；后台监控线程每 0.5 秒从数据库同步黑名单镜像并扫描关闭黑名单连接；内置 DDoS 检测按强度（low=300/medium=150/high=80 次每 10 秒）统计单位窗口内请求数，超阈值自动封禁来源 IP（首次限时封禁、时长可配，违规记录时间窗口内屡教不改自动升级永久封禁），检测强度/封禁时长/触发次数等配置在线热更新；管理后台 → 系统设置新增「DDoS 防护」分类，白名单 IP 不受影响。

* **移除 CPU 温度检测功能**：`routes/api/public.py` 删除跨平台温度采集（WMI/PowerShell/sysctl/psutil 传感器）与 `/api/server-status` 的 `cpu_temp` 字段，`templates/server_status.html` 移除 CPU 温度展示板块与刷新逻辑。

* **「申请账号」调整**：从导航栏「互动」分类移至「导航」分类，并更名为「申请服务器账号」（桌面端主导航与移动端侧栏同步调整）。

* **修复 /admin/settings 500 错误**：系统设置模板 `admin_settings.html` 因缺少 `{% endblock %}` 闭合标签导致 Jinja2 `TemplateSyntaxError`，已基于完整版本重写，恢复设置项动态渲染、自动保存、恢复默认与确认弹窗等功能，页面正常访问。

* **自动更新重启支持自定义启动指令**：新增 `RESTART_COMMAND` 配置（`config.py` 默认空，环境变量/系统设置/一键更新配置页均可设置）。一键更新重启时**优先使用自定义指令**（支持 `uv run app.py`、`python app.py --host 0.0.0.0` 等任意写法，含参数解析，裸 `python`/`python3` 自动替换为当前真实解释器），留空则自动用「当前解释器 + app.py + 原启动参数」重建——彻底修复 uv / venv 环境下更新后无法自动重启的问题。

* **IP 封禁管理页内联编辑配置**：IP 封禁管理页面（`/admin/ip-bans`）新增自动封禁开关与时长、可疑访问拦截开关与时长、封禁白名单的内联编辑与保存（新接口 `POST /admin/ip-bans/settings`），白名单通过 `get_whitelist()` 实时读取数据库配置，修改立即生效，无需再跳转系统设置。

* **新增可疑访问拦截功能**：新增攻击特征扫描器（`services/security_scanner.py`），在请求进入业务处理前识别 SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感文件与漏洞端点探测 / 恶意扫描 UA 等攻击特征，命中即拦截请求（403）并自动封禁来源 IP（复用 IP 封禁白名单与缓存，原因标注攻击类型与命中片段，操作人显示「系统」）；管理后台 → 系统设置新增「可疑访问拦截」分类（总开关、封禁时长、各攻击类型独立子开关，热更新即时生效），IP 封禁管理页同步展示可疑访问拦截状态；静态资源与用户生成内容（Markdown 代码块等）不会误判，URL 层全量扫描 + 请求体仅扫描高置信度特征（文本类且 ≤1MB）；新增扫描器与自动封禁单元测试（96 项安全用例全部通过）。

* **subprocess 编码统一 UTF-8（补全 Windows 10 场景）**：`services/process_utils.py` 的 `make_env()` 新增 `PYTHONUTF8=1`（强制 Python 子进程启用 UTF-8 模式），与既有 `PYTHONIOENCODING=utf-8` 一起从源头消除 Windows 10 下子进程 GBK 输出乱码 / `UnicodeDecodeError`；已覆盖 CPU 温度获取、ffmpeg/ffprobe 转码、数据库备份恢复、一键更新等全部子进程场景

* **自动更新重启改为通用启动命令（修复 uv 运行下无法自动启动）**：重启逻辑不再写死 `[python, app.py]`，改为用「当前真实解释器 + 原启动脚本 + 原启动参数（sys.argv）」重建完整启动命令——无论服务器用 `python`、venv 还是 `uv run` 启动，解释器路径与 uv/虚拟环境变量天然一致，不针对 uv 做任何特殊处理，同时完整保留 `--host/--port` 等命令行参数

* **服务器状态页整合玩家板块**：`/server-status` 在线玩家、最大玩家数、服务器状态三个小卡片移入「在线玩家列表」卡片头部，以紧凑徽章展示（在线=绿 / 状态=红/绿），页面更简洁

* **图形验证码进一步优化（字更大 + 干扰更丰富 + 颜色更多）**：字号比例提升至 `min(120, height*0.76)`；干扰横线/斜线增至 5~8 条、干扰字符增至 30~50 个，新增 2~5 个随机彩色圆点干扰；干扰线色池 14 色、字符深色池 12 色、浅色干扰字符池 14 色，随机性更强、更难被机器识别，同时保持人类可读

* **修复背景图片与评论等删除失败问题**：背景图片删除时 `remove_background_files` 对 `sqlite3.Row` 使用 `.get()` 导致 `AttributeError`，已改为按键访问；前端删除错误提示统一为「删除失败，请重试。」。删除权限校验正常返回 JSON 失败结果而非 500。

* **背景图片按屏幕比例最适配取图**：保存时自动记录图片自然宽高比（`backgrounds.ratio`，不再强制裁剪 16:9）；客户端在页面解析到背景元素后立即预加载（不等动画与其他脚本），自动携带屏幕宽高比与物理像素长边请求图片；服务端将所选档位中心裁剪到该比例后返回（结果缓存）。横屏/竖屏均获得与屏幕比例完全匹配且像素充足的图片，移动端清晰度大幅提升。

* **统一定时调度算法**：新增 `utils/shared/scheduler/` 统一定时调度（固定间隔含失败退避 / 每日时间点、优雅停止），已接入被驳回内容自动清理、每日备份、玩家列表追踪、验证码清理、连接池清理、站点地图刷新，行为与原逻辑一致。

* **导航栏动画流畅度优化**：下拉 caret 与滚动收缩动画补上 `will-change: transform` 合成层提示，动画更流畅，视觉效果与时长完全不变。

* **新增 IP 封禁功能**：管理后台新增「IP 封禁」页面（`/admin/ip-bans`），支持添加/解除封禁 IP（IPv4/IPv6/CIDR 段），可设置临时封禁时长或永久封禁并填写原因；被封禁 IP 的所有请求由中间件统一拦截返回 403；内置 30 秒缓存降低查询压力，临时封禁到期自动清理。

* **背景图片优化**：审核通过后自动设为「当前显示」背景（无需手动再开启）；上传文件统一按 `bg_<id>_<hash>.webp` 命名，不再保留原始文件名。

* **全站 UI 优化为白色浅蓝磨砂玻璃风格**：主页由深色海洋风格全面转换为白色浅蓝主题（滚动时背景图片保持可见，标题深色 + 浅蓝渐变强调）；全站图标统一为浅蓝色；进度条与滚动条改为浅蓝渐变磨砂玻璃风格；修复 `/backgrounds` 页面「当前显示」按钮与状态徽章浅色文字浅色底融合不可见的问题，黄色/绿色等状态文字改为深色可读版本。

* **控件全面改为白色略微透明磨砂玻璃**：主按钮（`.btn-primary`）由黑色渐变改为白色半透明磨砂玻璃（深色文字 + 蓝色强调边），次按钮/危险按钮/输入框/导航/弹窗/Toast 等控件统一为白色磨砂玻璃质感，更好适配全站背景图片；深色工具类（`.bg-forest-900` 系列）全局映射为白色半透明背景；Markdown 编辑器面板、指南正文的代码块保持深色卡片保证可读性，行内代码改为浅蓝底深蓝字；浅色状态文字（红/黄/绿/蓝 300/400 系列）全局映射为深色可读版本（代码块内除外）；指南卡片、广播富文本编辑器、更新日志面板等同步改为白色磨砂玻璃。

* **同步 GitHub 代码 + 上传**：本地改动已与 GitHub 仓库同步并提交。

* **修复大屏端重复显示汉堡菜单**：`>=900px` 大屏端桌面导航（首页/导航/互动/账号）已足够，隐藏汉堡菜单按钮（`.nav-more-button`），避免出现两个菜单入口；小屏端仍保留右侧滑出菜单。

* **数据备份增强**：新增「下载备份」能力——备份历史中成功备份可一键下载到本地（新增 `admin/api/db-backup/<id>/download` 接口，后端 `send_file` 流式下发，前端下载按钮在静态与 JS 动态渲染中均已接入）。

* **撤回更新优先 Git，改回优先代理下载**：一键更新顺序调整为「① 代理下载 → ② GitHub 直连 → ③ Git（仅当前目录是 git 仓库且系统有 git 时兜底）」，回到代理下载为主、稳定优先的同步方式。

* **整体风格统一为现代化白色磨砂玻璃**：登录页由旧深色主题整体改造为白色磨砂玻璃风格（`.auth-*` 全部改用白色玻璃卡片 + 深色文字 + 蓝色强调色，与全站一致）；基础输入框 `.input-field` 及弹窗输入框同步由深色改为白色磨砂玻璃控件。

* **彻底修复图形验证码文字太小**：登录页内嵌验证码原先被压缩至 136px/112px 且 `object-fit: cover` 裁切，文字几乎不可读；现放大为桌面端 200×72、小屏端 168×64，并改为 `object-fit: contain` 完整显示整幅验证码，文字清晰可辨（弹窗验证码维持 `max-w-[420px]` 原尺寸）。

* **整体界面改为纯白主题**：页面背景色从偏冷灰 `#f3f6fa` 调整为纯白系 `#f8fafc`，白色磨砂玻璃质感更干净

* **修复手机端汉堡栏弹出弹性动画**：侧边菜单起始状态加入 `scale(0.92)` + 新缓动曲线 `cubic-bezier(0.32,1.72,0.56,1)`（更强过冲），弹出时先越过终点再回位，同时配合 overlay `0.35s` 淡入，观感更有"弹簧"弹性

* **自动更新：优先 Git，兜底代理+直连**：检测到 `.git` 目录 + 系统有 `git` 时直接 `git fetch --all --tags && git reset --hard origin/main`（UTF-8 编码统一），完全绕开代理；Git 不可用时才回落到代理+GitHub 直连

* **自动更新启动命令默认使用 `{python路径} {项目根目录}/app.py`**：重启脚本与直接兜底都使用 `sys.executable + APP_ROOT/app.py`，不依赖 shell 命令

* **修复迁移脚本列不匹配报错**：旧 DuckDB `music` 表仍有 `is_public` 等遗留列，迁移脚本改为读取 SQLite 目标表的列清单（`PRAGMA table_info`），只复制新旧库共有列，自动跳过已废弃的 `is_public` 等列并在输出中注明跳过内容

* **彻底删除 MinIO 对象存储**：移除 `services/object_storage.py`、MinIO 相关配置与依赖，背景图片改回本地文件存储。

* **彻底删除 CMD 控制台**：移除快捷命令、定时任务、脚本执行/终端等全部功能（路由、服务、模板、前端脚本、数据库表、xterm.js 依赖与构建下载逻辑），管理后台不再显示终端控制台入口。

* **UI 改回白色页面 + 黑色控件**：全站由深色主题改为白色磨砂玻璃风格（白色卡片 + 深色控件），磨砂玻璃质感保留；导航栏大屏端（≥1024px）改为「首页 / 导航 / 互动 / 账号」悬停下拉菜单（导航=指南/服务器状态，互动=大喇叭音频/背景图片/游戏账号，账号=设置/管理/退出），小屏端保持右侧滑出菜单；下拉使用 CSS 过渡动画流畅展开

* **数据库迁移到 SQLite（WAL 模式）**：从 DuckDB 迁移到 SQLite，启用 `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` + `busy_timeout=30000`，单例共享连接 + 可重入锁保证多线程安全；备份改用 SQLite 在线备份 API（`Connection.backup()`）；新增迁移脚本 `scripts/migrate_db.py`（自动备份旧库后一键迁移）

* **修复自动更新关闭后无法自动启动**（Windows 10 + uv）：重启逻辑不再依赖批处理/Shell 脚本，改为独立 Python 辅助脚本等待旧进程退出后拉起新进程，完整继承原环境变量（含 uv/虚拟环境），跨平台统一且无需特殊处理

* **背景图片功能优化**：上传图片自动转为 WebP 格式（智能裁剪 16:9 + LANCZOS 缩放），自动生成 768/1280/1920 三档响应式变体；前端按设备屏幕宽度（含 DPR）请求最合适的尺寸，实现按设备最佳缩放；修复未通过审核图片无法预览的问题（管理员/上传者可预览）

* **subprocess 编码统一 UTF-8（修复 Windows 10 下 GBK 乱码/UnicodeDecodeError）**：所有 `subprocess` 调用统一添加 `encoding='utf-8', errors='replace'`（或 `env=make_env()` + 显式解码），覆盖 CPU 温度获取、ffmpeg/ffprobe 转码、备份恢复、更新器构建等全部子进程场景

* **图形验证码优化（修复「验证码太小」）**：默认尺寸 360x128 → 420x150，字号增大（`font_size = min(96, int(height*0.68))`）；干扰元素升级——3~6 条明快色系彩色干扰横线/斜线、字符后方 20~40 个浅色小号干扰字符（数字/字母/短横线/点）、背景噪点数量增加并随机浅色着色；字符颜色从深色系（深蓝/深红/深绿/深紫/墨黑/深棕）随机选取，保持清晰可辨；位数（4 位）与字符集不变，`generate()`/`verify()`/`consume()` 接口不变，弹窗图片宽度放宽至 `max-w-[420px]`

* **游戏账号绑定机制改造**：一个网站账号只能绑定一个服务器账号（绑定页提示文案同步更新）；绑定/验证游戏内密码前需先完成图形验证码（复用全局 `CaptchaModal` 弹窗，前端先弹窗验证、后端再次校验并消耗）；`easyauth_bind.py` 解析 `Player Info: {...}` 容错增强（兼容冒号后有无空格、无 uuid 字段、密码为空等场景）

* **恢复密码强度规则**：网站密码恢复为 8-30 位且必须包含大小写字母、数字和特殊字符，拒绝弱密码（常见易猜密码、单一重复字符、连续序列）；游戏账号密码（AuthMe）为 6-30 位且至少包含字母和数字。统一收敛到 `services/validation.py`，注册/找回密码/修改密码均复用 `validate_password_strength`，移除 `services/user/auth.py` 中重复的本地校验函数

* **服务器状态页面重构**：CPU 使用率、内存使用率、CPU 温度改为各占一行独立板块，展示更清晰醒目；新增内存详情（已用/总计）、刻度标签、三色渐变温度条

* **彻底修复 Windows 10 CPU 温度获取**：改用 `MSAcpi_ThermalZoneTemperature` WMI 类（Windows 10 最可靠），新增 PowerShell 兜底策略，多层级重试确保最大兼容性

* **修复汉堡侧边栏无法滚动**：移动端菜单 nav 添加 `overflow: hidden`，解决 `border-radius` 与 `backdrop-filter` 组合时内容溢出破坏滚动行为的问题

* **修复邮件文字颜色**：邮件模板 `base.html` 中 `.mail-content` 区域文本颜色改为 `#e5e7eb`，解决黑色文字在暗灰蓝背景下看不清的问题
* **修复一键更新自动重启**：重写重启脚本启动逻辑，修复 `devnull` 变量未定义导致崩溃的严重 Bug，添加进程组隔离参数确保子进程独立于父进程存活
* **修复一键更新源兼容性**：移除过于激进的 `Content-Type` 检查，重构 URL 构建逻辑，支持多种代理 URL 格式自动尝试，修复代理检测的测试 URL 错误
* **清理屎山代码**：重构 `core.py` 下载逻辑，消除重复代码（提取 `_build_download_urls`、`_try_download` 函数），移除未使用的 `session` 变量，删除冗余的 `Content-Type: text/html` 拦截
* **测试代码优化**：将测试从手动打印输出改为使用 pytest 框架，使用 `@pytest.mark.parametrize` 参数化测试，添加 `validate_email_format` 和 `validate_ban_reason` 测试用例，76 个测试全部通过
* **游戏账号解绑功能**：MC 账号列表新增「解绑」按钮，支持确认弹窗和淡出消除动画，绑定服务层新增 `unbind_account`、`create_binding`、`is_bound_to_user` 等服务函数

* **路由层分层规范全面修复**：移除 `routes/game_accounts/__init__.py` 和 `routes/game_accounts/bind.py` 中所有直接 SQL 查询，改用服务层函数调用，彻底消除路由层 `conn.execute()`，严格遵循 MVC 分层架构

* **修复潜在 NameError 运行时错误**：`routes/game_accounts/__init__.py` 中三个路由函数使用 `get_db()` 但未导入，现通过服务层替代已消除该隐患

* **代码清理**：移除未使用的导入（`request`、`abort`、`redirect`、`url_for`）、死代码注释、未使用函数参数和未使用变量，提升代码可维护性。

* **项目结构优化**：将大文件按功能模块拆分为子包，`services/music_service.py` → `services/music/`（常量/查询/CRUD/上传/收藏），`services/user_service.py` → `services/user/`（认证/资料/管理），`services/updater.py` → `services/updater/`（配置/核心逻辑）；保留原文件作为兼容性重导出层，旧代码无需修改导入路径。

* **一键更新重写**：重写 `services/updater/core.py` 更新逻辑，实现跨平台独立重启脚本（Windows 批处理 / Linux Shell），通过 `tasklist` 检测旧进程退出后启动新进程，解决 Windows 环境下更新后服务器无法正常重启的问题。修复前端日志重复显示问题，调整重启检测时机避免误判。

- **启动健康检查**：`core/system/startup_checks.py` 每次启动固定运行服务器健康检查——模块导入完整性、数据库完整性、文件结构、配置完整性、uploads 目录结构检查，只创建不删除、自动修复；`core/system/init.py` 集成该检查，在数据库初始化前执行。

- **错误页面修复**：修复 403/404 错误页面未传递 `user` 上下文变量，导致登录用户显示"请登录"的问题。

- **MC 游戏账号注册改为白名单模式**：重写注册申请功能，审批通过后改为通过 RCON 发送 `/easywhitelist add <玩家名>` 命令添加白名单，不再需要密码。移除前端密码表单字段、后端密码验证、密码加密存储逻辑。新增 `services/rcon/easy_auth.whitelist_add_player()` 函数，使用 `sanitize_rcon_username` 清洗输入防止注入。

- **优化绑定账号操作逻辑**：
  - 绑定账号改为通过 RCON `/auth getPlayerInfo` 指令获取 BCrypt 哈希验证密码，无需用户输入服务器路径
  - 错误信息更精确：区分 RCON 连接失败、玩家未注册、密码错误、未设置密码等场景
  - 后端合并为单次 DB 连接，减少资源开销
  - 前端按钮增加加载动画和防重复提交，绑定成功后仅清空密码字段，保留用户名便于确认
  - 使用 `CustomModal` 全局弹窗确认和提示，支持 Toast 辅助反馈

- **RCON 连接池优化**：
  - 新增 `services/rcon/pool.py` 线程安全连接池，自动复用 TCP 连接
  - 池满时自动创建临时连接（用完即关），实现理论无限并发
  - 空闲连接超时自动回收（默认 60 秒），后台守护线程定期清理
  - 连接失效自动检测并丢弃，不影响其他线程
  - 非默认 RCON 配置（host/port/password 覆盖）使用一次性连接，兼容旧逻辑

- **修复背景图片不显示 + 新增审核邮件通知**：
  - 修复 `serve_background` 路由，增加文件存在性检查，文件不存在时返回 404 而非 500
  - 启动检查 `startup_checks.py` 新增 `uploads/backgrounds` 目录自动创建
  - 新增背景图片审核结果邮件通知 `background_review_result` 模板
  - 审核通过/驳回时自动发送邮件通知上传者

