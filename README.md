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

这会下载以下资源到 `static/lib/`：

* **Lucide Icons** — 图标库

* **Marked.js** — Markdown 渲染

* **JetBrains Mono** — 编程字体（代码编辑器 / 时间码）

* **ZCOOL QingKe HuangYou（站酷庆科黄油体）** — 正文中文字体，本地子集化 woff2（按 `unicode-range` 分片）

* **ZCOOL KuaiLe（站酷快乐体）** — 标题中文字体，同为本地子集化 woff2

> 中文字体使用自带字体：正文 **站酷庆科黄油体**（圆润活泼、笔画简洁），标题 **站酷快乐体**（更俏皮有活力），
> 均为本地分片子集，浏览器只按需下载用到的子集；字体文件随静态资源预构建提交，**零外部 CDN 依赖**。
> 静态资源（含 Tailwind 构建产物 `static/css/tailwind.css`）已预构建并随代码提交，一键更新无需额外构建步骤。

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
│   │   ├── snowflake.py      #   全站统一雪花 ID 生成器（非用户表主键唯一入口）
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
│   ├── backup/               #   自动维护（/uploads/ 全量 zip 极限压缩 + 日志清理）
│   ├── buildings/      # 公共建筑（列表/搜索/收藏/评论分页）
│   ├── mail/           # 异步邮件发送
│   ├── game_accounts/  # 游戏账号注册申请（审批/驳回/封禁）
│   ├── game_server_ban/ # 游戏服务器封禁申请（审批 → RCON ban → 到期自动 pardon）
│   ├── system_metrics/ # CPU/内存/系统/性能追踪（后台线程采集）
│   ├── music/          # 大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/           # RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── user/           # 用户（认证/资料/管理）
│   ├── background_service/  #   背景图片业务（WebP 转换 + 按屏幕比例挑选）
│   ├── cleanup_service/     #   被驳回内容自动清理
│   ├── content_limits/      #   待审核内容上限业务规则
│   ├── firewall/            #   高性能防火墙（DuckDB 引擎 + WSGI 门禁 + DDoS 防护）
│   │   ├── api_guard.py     #     接口频率限制
│   │   ├── service/         #     业务层（core / database / monitor）
│   │   ├── protection/      #     防护策略（content_filter / ddos / file_guard）
│   │   └── transport/       #     连接层（wrappers：WSGI 门禁）
│   ├── settings_manager/    #   系统设置管理
│   ├── security/            #   安全扫描（SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感探测 / 恶意 UA）
│   └── sitemap_cache/       #   Sitemap 缓存服务
├── routes/       # HTTP 路由层（Flask Blueprint）
│   ├── admin/          # 管理后台（用户/自动维护/设置/日志/更新/游戏账号/指南/音乐/背景/建筑等）
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
├── static/       # 唯一的前端文件夹：静态资源 + Jinja2 模板（命名规范见 docs/DEVELOPMENT.md）
│   ├── css/            #   样式（base.css / tailwind.css 构建产物）
│   ├── js/             #   前端脚本（core/ 通用组件、pages/ 页面脚本）
│   ├── favicons/       #   站点图标（可配置）
│   ├── lib/            #   本地化第三方库与字体（构建生成，含 lib-version.json）
│   └── templates/      #   Jinja2 模板（Flask template_folder）
│       ├── admin/          #     管理后台页面（如 users.html、settings.html，无 admin_ 前缀）
│       ├── auth/           #     登录 / 注册 / 找回密码
│       ├── settings/       #     用户个人设置
│       ├── site/           #     站点级信息页（站点文档、服务器状态、网页地图）
│       ├── backgrounds/    #     背景图片页面（index / upload）
│       ├── emails/         #     邮件模板（独立 Jinja2 loader）
│       ├── game_accounts/  #     游戏账号页面（apply / ban_apply）
│       ├── guides/         #     服务器指南页面（index / detail / form）
│       ├── buildings/      #     公共建筑（index / create / detail）
│       ├── music/          #     大喇叭音频页面（index / my / favorites / upload）
│       ├── macros/         #     通用模板宏（模态框/编辑器/进度条/音乐/页面内搜索）
│       └── ...             #     根级通用页面（base.html 布局、index.html 首页、error_simple.html 精简错误页）
├── docs/         # 项目文档
├── scripts/      # 构建脚本（build/）与测试（tests/）
├── uploads/      # 运行期上传数据
│   ├── guides/         # 服务器指南（每个指南一个目录：guide.md + assets/ 视频等资源，单个指南资源上限 50MB）
│   ├── backgrounds/    # 全站背景图片
│   ├── music/          # 大喇叭音频（每个音频一个 ID 目录，含 m3u8、ts 分片与唱片 MP3）
│   └── db/             # 数据库文件（site.db + firewall.duckdb）
├── backups/      # 自动维护备份目录（默认 ../bhxz_backups，支持自定义路径与运行时热改）
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

* 自动维护（手动/自动，数据备份 + 日志文件清理，极限压缩 zip，进度条；备份目录支持设置绝对/相对路径，默认 `../bhxz_backups`）

* 公开文件管理

* 广播邮件（复用全站统一编辑器，富文本 / Markdown 双模式 + 白名单 HTML 清洗，安全防 XSS）

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

* **就地搜索框**：每个列表页使用自己的搜索框（`static/templates/macros/search.html` 的 `inline_search()` 宏），导航栏不放置搜索输入框
* **点击展开、Esc 收起**：点击搜索框任意位置即可展开；输入框有内容或光标在内时保持展开，失焦且无内容时平滑收起，Esc 清空并收起
* **结果就地渲染**：输入后防抖或回车，由搜索框派发 `site-search` 事件，各列表页监听后直接刷新当前列表，不弹出下拉面板或跳转独立搜索页
* **覆盖范围**：公共建筑 / 服务器指南 / 大喇叭音频三个列表页；关键词通过各列表 API 的 `q` 参数匹配标题、摘要或标签

### 服务器指南

* 卡片式列表页，支持置顶与按标题自动排序

* **指南搜索**：指南列表页顶部提供就地展开的搜索框（`inline_search` 宏）；列表 API `/api/guides/list` 与列表页均支持 `q` 关键词参数，按标题与摘要模糊匹配；列表接口**不返回正文 `content`**，仅返回标题、摘要等列表所需字段

* Markdown 详情页（标题锚点、代码一键复制）

* **指南文件化存储**：每条指南对应独立目录 `uploads/guides/<指南ID>/`，正文保存为 `guide.md`（唯一内容来源），视频等资源放在 `assets/`；数据库 `server_guides.content` 只保留空串，读取时以文件优先、文件缺失时回退数据库旧内容。每个指南的全部资源合计上限 **50MB**，支持 mp4 / webm / ogv / ogg / mov / m4v。
  * **新建即生成目录（草稿工作流）**：新建指南只需填写标题与摘要，提交后立即创建指南 ID 与目录，正文暂为空，并可在「我的指南」看到该指南；随后进入编辑页撰写内容、上传视频（资源直接写入 `uploads/guides/<ID>/assets/`）。新建后的指南状态为 **草稿（draft）**，草稿计入「未通过指南数量」，超过上限则禁止新建。
  * **发布**：在「我的指南」或指南详情页点击「发布」（`POST /api/guides/<id>/publish`），草稿即变为待审核（pending）状态，正文非空即可发布；草稿保存无需验证码，正式提交仍需验证码。
  * **迁移脚本**：`python scripts/migrate_guides.py` 把数据库中已有指南正文自动写入 `guide.md` 并清空数据库正文；支持 `--dry-run` 演练与 `--overwrite` 覆盖，可重复执行（幂等）。
  * **资源访问**：`/guides/<ID>/assets/<文件名>`；已审核通过的指南公开可访问，未通过的仅作者与管理员可访问。
  * 旧版 `uploads/guides/_drafts/` 草稿 token 机制已移除，仅在自动维护时清理历史残留目录。

* **富文本 / Markdown 统一编辑器**（全站唯一宏 `static/templates/macros/markdown_editor.html` + 引擎 `static/js/pages/markdown-editor.js`）：
  * 默认「富文本（所见即所得）」模式，底层数据与保存内容**始终是 Markdown**，可视化界面只是渲染层；可一键无缝切换到「Markdown 源码」模式（单栏，无实时预览），切换时内容与光标位置保留。
  * **本地静默草稿**：编辑内容实时防抖写入浏览器 `localStorage`（按编辑器 id + 页面路径区分），**仅存本机、不上传云端**；刷新或误关闭后自动恢复，表单成功提交后自动清除，避免残留旧草稿。
  * **高频交互不卡顿**：选区变化经签名去重后合并到同一帧刷新工具栏，表格检测按当前行预判，避免大文档下反复全量重排 / 重建 DOM。
  * 工具栏按 **基础 / 段落 / 插入 三个常驻标签页**分类：基础（加粗/斜体/删除线/行内代码/清除格式）、段落（H1–H4/引用/无序/有序/任务列表/分割线/缩进）、插入（链接/代码块/表格/视频）。
  * **上下文标签页**：另有「链接」「表格」「视频」三个标签页，仅在光标位于链接内、表格内、视频内（或刚点了「插入链接/表格/视频」）时自动出现，离开对应上下文后自动隐藏并切回基础页。
  * **视频标签页**：在指南编辑器中可直接上传视频（写入 `assets/`，按指南 50MB 配额校验）、查看当前视频列表并点击插入正文；点击正文中已有的视频即可打开视频标签页，再点列表中的其它视频可一键更换地址。视频以原始 HTML `<video src=... controls preload=metadata>` 写入 Markdown。
  * **链接标签页**：可直接填写链接地址、显示文字、悬停标题与「新窗口打开」；**未选中文字时点击链接按钮会自动插入默认文字**（无需先选中文字）；提供独立「取消链接」按钮（仅保留文字、移除链接）。图片插入功能已移除。
  * **表格标签页**：增删行列 / 删除表格 / 当前列左中右对齐；插入表格后自动切到表格标签页，光标离开表格后自动收起。
  * **可切换样式**：再次点击已激活的样式按钮即**取消该样式**（加粗、斜体、删除线、行内代码、H1–H4、引用、任务列表等均支持「点一次加、再点一次取消」）；激活态高亮显示。
  * **按钮条件启用**：需选中文字的按钮（加粗等）仅在选中文字时亮起，表格按钮仅在光标位于表格内时亮起，否则置灰不可点。
  * **表格列宽拖拽（含移动端）**：拖拽表头列之间的手柄调整列宽，采用 Pointer Events 统一处理鼠标与触屏（`touch-action:none` + 指针捕获），移动端可正常拖动；结果**直接编码进 Markdown 表格分隔行的破折号数量**（列越宽该列破折号越多），往返编辑不丢失；表格对齐（左/中/右）同样映射到分隔行的 `:` 标记。
  * 支持全部标准 Markdown 语法的可视化编辑：标题、强调、行内代码、代码块（含语言）、引用、有序/无序/任务列表、链接、分割线、表格；Markdown 不支持的常见内联语义（`<sub>`/`<sup>`/`<mark>`/`<u>`/`<kbd>` 等）以原始内联 HTML 保留。
  * 与模板风格完全统一（白色磨砂玻璃、站点配色与字体），不引入任何第三方编辑器库或外部风格。
  * **自带文本选择样式**：编辑器（富文本区与 Markdown 源码区）定义独立的 `::selection` 配色（更贴近站点主色的蓝色选区），不被全站默认选区样式覆盖；同时富文本区禁用移动端长按弹出的「复制 / 粘贴 / 全选」原生选择菜单（`-webkit-touch-callout: none`），选区交互完全由编辑器自身样式与工具栏承载。

* 成员提交需审核，管理员直接发布

* 封禁机制（用户名/IP，限时或永久）

### 公共建筑

* 公共建筑列表页面，用户可发布自己的建筑（标题、领地名、介绍、使用方式、注意事项），**发布后进入待审核状态，管理员审核通过才公开**
* **列表整体走 API 获取**：`/buildings` 页面首屏 / 搜索 / 标签筛选 / 「加载更多」/ 收藏全部由前端调用 `GET /api/buildings/list` 无刷新完成，页面仅渲染骨架（与音频 / 指南列表一致）
* **搜索与标签**：列表页顶部提供就地展开的搜索框（`inline_search` 宏）；建筑列表 API `/api/buildings/list` 支持按标题与标签模糊搜索，标签可多选管理，列表默认**按收藏数量排序**；列表接口**不返回描述/使用方式/注意事项等正文**，仅返回列表所需字段（标题、领地名、标签、作者、收藏数、浏览数等）
* **审核邮件提醒**：用户发布建筑后自动向所有管理员发送待审核提醒；管理员通过 / 拒绝后自动向作者发送审核结果邮件（拒绝含原因）
* **收藏**：登录用户可收藏/取消收藏建筑，收藏数参与排序
* 一键复制传送指令 `/res tp 领地名`
* **浏览量统计**：访问建筑详情页时 `view_count` 自动 +1（作者本人访问不计入）；浏览数在列表卡片与详情页展示
* 评论功能：登录用户可发表评论，作者/管理员可删除评论；评论列表经 `GET /api/buildings/<id>/comments` 分段加载（每页条数由系统设置 `BUILDING_COMMENTS_PER_PAGE` 控制），滚动到列表底部自动加载下一页
* 举报功能：用户可举报违规建筑，管理员在后台可查看举报并删除建筑
* 接入防火墙内容检测、防刷机制和图形验证码

### 大喇叭音频

* 上传音频自动转码为 HLS（m3u8），并生成唱片 MP3：播放链接 `http://<主机>/music/<编号>.m3u8`，唱片下载 `http://<主机>/music/<编号>.mp3`（游戏内烧录唱片用）
* **「广播m3u8」按钮**：公开列表 / 我的音频 / 我的收藏 / 管理员审核队列 / 上传成功卡片统一为「广播m3u8」+ `radio` 图标，点击复制播放链接
* 支持 mp3 / wav / ogg / m4a / flac，单文件不超过 100MB（依赖 ffmpeg：Windows 优先 `uploads/ffmpeg/ffmpeg.exe`，缺失时回退系统 PATH）
* **公开需审核**：申请公开的音频进入「待审核」，管理员通过后才在游戏内大喇叭展示；驳回后自动转为私有，可重新申请或删除
* **私有仅表示不出现在公开列表**：所有音频均可凭链接访问（播放 m3u8 / 下载 MP3 / 拉取分片均无需登录）
* **邮件通知**：用户申请公开时提醒所有管理员；管理员通过/驳回后通知上传者（邮件未启用或无邮箱时自动跳过）
* **列表整体走 API**：公开列表首屏 / 搜索 / 加载更多均调用 `GET /api/music/list`，关键词同时匹配标题与标签
* **收藏**：可收藏他人上传的公开音频，在「我的收藏」（`/music/my/favorites`）统一查看与播放；删除音频时级联清理
* **标签**：上传时可填（逗号分隔、自动去重、最多 10 个、每个 ≤12 字），「我的音频」与管理员后台可编辑，参与搜索匹配
* **状态管理**：私有 / 待审核 / 已公开，用户在「我的音频」（`/music/my`）中申请公开、转为私有或删除，操作均为无刷新 API
* **独立上传页**：`/music/upload` 异步上传，分「文件上传」与「ffmpeg 转码」两阶段展示进度条，成功后展示播放链接与唱片 MP3 链接，失败可重试
* **转码后清理源文件**：目录内只保留 `index.m3u8`、`seg_*.ts` 与唱片 `index.mp3`
* **复制时长（秒）**：各音频卡片的「时长 Ns」按钮可一键复制音频总秒数
* 管理员可审核公开申请、查看全部音频并一键下架（删除记录与文件）
* 音频存放在 `uploads/music/<音频ID>/`，删除记录时自动清理对应目录

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

* 上传图片自动转为 WebP（LANCZOS 缩放，保持自然宽高比），磁盘上每张背景只保留一个主图文件
* **按屏幕宽高比挑选**：前端携带屏幕宽高比请求图片，服务端只查询并返回宽高比最接近的已通过背景原图，裁剪与铺满由浏览器按 `background-size: cover` 完成；挑选使用对数距离，保证「屏幕越宽 → 选越宽的图」
* **无启用/停用开关**：审核通过即进入全站背景图片池，不想要直接删除即可
* **统一取图入口**：全站背景从 `/backgrounds/serve?ratio=` 获取（不带 ID），响应带 ETag 并强制重新校验；按 ID 的 `/backgrounds/serve/<id>` 仅用于后台缩略图、审核预览与用户查看自己的图片
* **批量上传**：拖放/选择多个文件，逐文件校验格式与大小，聚合展示整体进度
* 支持审核 / 驳回流程与审核结果邮件通知，管理员与上传者可预览未通过审核的图片
* **列表整体走 API**：`/backgrounds` 首屏由 `GET /api/backgrounds/list` 获取（全部已通过背景 + 我的上传），删除为无刷新 AJAX
* **被驳回内容 24 小时自动删除**：被驳回的指南、背景图片等自动清理记录与关联文件

### 网页地图

* 导航栏「服务器 → 网页地图」进入 `/map`，自动内嵌「系统设置 → 外部链接 → 卫星地图地址」（`MAP_URL`）配置的网页地图，改设置即时生效
* 中间件按 `MAP_URL` 的源动态放行 CSP `frame-src` / `child-src`，保证外部地图可内嵌
* 地图区自适应铺满可视高度，工具栏提供「刷新 / 全屏 / 新标签打开」；iframe 载入完成自动淡出加载遮罩，超时或 `MAP_URL` 为空时给出提示与出口

### 文档系统

* Markdown 文档渲染（marked.js）

* 代码块一键复制按钮

* 侧边栏导航

## 配置说明

### 管理后台在线编辑（推荐）

所有运行时配置均可在 **管理后台 → 系统设置** 中在线编辑，修改后立即生效（热重载），无需重启服务器。

支持编辑的配置分类：

* **日志**：日志输出等级、是否打印日志到终端；各模块单独日志是否落盘 / 是否并入全局日志，在「日志页面 → 日志设置」中逐模块配置（支持任意已注册模块）

* **自动维护**：自动维护时间（数据备份 + 日志清理）、备份目录、保留份数、超时

* **Sitemap**：刷新时间、站点域名、多域名列表、搜索引擎爬虫策略（robots.txt：允许所有 / 仅主页 / 禁止所有）。站点地图（`/sitemap.xml`）**只收录无需登录即可访问、且含可索引内容的页面**——首页、服务器状态、服务器指南（及已通过详情）、公共建筑（及已通过详情）、大喇叭、背景图片、文档，以及后台「公开文件」配置的页面（自动跳过 `js`/`css`/图片等资源映射）；已排除登录后 / 操作 / 上传页（`/settings`、`/music/my`、`/music/upload`、`/game-accounts/apply`、`/guides/create` 等）、仅内嵌外部地图的 `/map`、以及 `/admin`、`/api` 等内部路径，并按 path 去重

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
| `FFMPEG_BIN`                  | 大喇叭音频转码用的 ffmpeg                          | Windows 优先 `uploads/ffmpeg/ffmpeg.exe`，否则系统 PATH；Linux/macOS 用系统 `ffmpeg`  |
| `FFPROBE_BIN`                 | 探测音频时长（转码进度百分比）用的 ffprobe                 | Windows 优先 `uploads/ffmpeg/ffprobe.exe`，否则系统 PATH；Linux/macOS 用系统 `ffprobe` |
| `FFMPEG_THREADS`              | ffmpeg 音频转码线程数                            | `0`（自动按 CPU 核数）                             |
| `MAX_CONTENT_LENGTH`          | 最大上传大小                                    | 100 MB                                      |
| `BACKUP_DIR`                  | 备份根目录（支持绝对/相对路径，运行时可在后台热改）            | `../bhxz_backups`（项目上一级）                   |
| `SECRET_KEY`                  | Session 密钥                                | `mc_server_site_random_secret_key_2024`     |
| `REGISTER_VERIFY_CODE`        | 注册验证码                                     | `binhai_xz`                                 |
| `BACKUP_SCHEDULED_TIME`       | 每日自动维护时间（备份 + 日志清理）                        | `03:00`                                     |
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
| `MAP_URL`                     | 卫星地图地址（首页按钮跳转 + 网页地图页内嵌）              | `https://map.bhxz.tw.kg`                    |
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

### 背景图片 API

| 方法  | 路径                        | 说明                                                       |
| --- | ------------------------- | -------------------------------------------------------- |
| GET | `/api/backgrounds/list`   | 背景图片列表（返回 `approved` 全部已通过、`my` 登录用户上传、`logged_in`），供 `/backgrounds` 页面首屏渲染 |
| GET | `/backgrounds/serve`      | 全站背景图片访问（**不带 ID**；`ratio`=屏幕宽/高，服务端只按比例挑选并原样返回，不缩放不裁剪）  |
| GET | `/backgrounds/serve/<id>` | 按 ID 取图（后台缩略图 / 审核预览 / 查看自己上传；原样返回主图）              |
| POST | `/backgrounds/<id>/delete` | 删除背景图片（上传者本人或管理员，AJAX）                                   |

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
| POST | `/api/guides/<id>/publish` | 发布草稿指南（草稿 → 待审核，正文不能为空，需登录且仅作者 / 管理员） |
| GET | `/api/guides/<id>/videos` | 当前指南视频列表（含 `url` / `delete_url` 与配额用量，需登录） |
| POST | `/api/guides/<id>/videos` | 上传指南视频（表单字段 `video`，写入 `assets/` 并按 50MB 配额校验，需登录） |
| POST | `/api/guides/<id>/videos/<文件名>/delete` | 删除指南视频（需登录） |

### 大喇叭音频 AJAX 端点

| 方法   | 路径                                 | 说明                              |
| ---- | ---------------------------------- | ------------------------------- |
| GET  | `/api/music/list`                  | 公开音频列表（`q` 关键词匹配名称与标签、`page` 页码；每页条数由 `MUSIC_PER_PAGE` 控制，接口不接受前端传入的数量参数）；公开列表页首屏 / 搜索 / 加载更多均调用此接口 |
| POST | `/music/upload`                    | 开始异步上传（返回 `{task_id}`，转码在后台执行）  |
| GET  | `/music/upload/progress/<task_id>` | 查询上传/转码进度（JSON）                 |
| GET  | `/music/<id>.mp3`                  | 下载唱片 MP3（游戏内烧录唱片；权限同 m3u8 播放链接） |
| POST | `/api/music/<id>/toggle`           | 申请公开 / 转为私有（无刷新，返回最新 `status`）    |
| POST | `/api/music/<id>/delete`           | 删除音频（本人或管理员，无刷新）               |
| POST | `/music/<id>/toggle`               | 旧表单入口（兼容保留，整页跳转）                |
| POST | `/music/<id>/delete`               | 旧表单入口（兼容保留，整页跳转）                |
| POST | `/music/<id>/favorite`             | 收藏 / 取消收藏（仅已公开音频，需登录）           |
| POST | `/music/<id>/tags`                 | 编辑音频标签（本人或管理员，需登录）              |
| GET  | `/music/my/favorites`              | 我的收藏页（需登录）                      |

### 账户设置 API（需登录，无刷新）

| 方法   | 路径                              | 说明                          |
| ---- | ------------------------------- | --------------------------- |
| POST | `/api/settings/username`        | 修改用户名（返回新用户名）               |
| POST | `/api/settings/password`        | 修改密码                        |
| POST | `/api/settings/email`           | 修改邮箱（需邮箱验证码 + 当前密码）         |
| POST | `/api/settings/delete`          | 注销账号（成功后前端跳转首页）             |
| POST | `/api/settings/avatar`          | 上传头像（multipart，返回 `avatar_url`） |
| POST | `/api/settings/avatar/delete`   | 恢复默认头像                      |

## 前端特性

### 白色磨砂玻璃效果（White Frosted Glass）

* **白色页面 + 黑色控件**：`#f3f6fa` 浅色底色搭配 `#1a2230` 深色正文、`#0284c7`（蓝）/`#7c3aed`（紫）强调色，按钮、输入框、导航栏均为深色控件，白色磨砂玻璃卡片承载内容

* **真实酸蚀刻玻璃质感**：`background: linear-gradient()` 渐变背景替代纯色，模拟光线透过玻璃的漫射效果

* `backdrop-filter: blur(28px) saturate(140%)` — 玻璃卡片高通透，自然融入浅色背景

* 高透明度 `rgba(255,255,255,0.74)` 背景 + 光线散射伪元素（`radial-gradient` 模拟漫射光）

* 边缘光晕伪元素（`mask-composite` 渐变边框，模拟玻璃切割面折射）

* 全局细微噪点纹理（SVG `feTurbulence`），模拟蚀刻玻璃表面微观散射

* **桌面端悬停下拉导航栏**：大屏端（≥1024px）主导航为「主页 / 服务器 / 社区 / 我的」，其中「服务器 / 社区 / 我的」为悬停下拉菜单；小屏端保持右侧滑出菜单。分组内容：服务器（服务器状态 / 服务器指南 / 网页地图）、社区（大喇叭音频 / 公共建筑 / 官网背景图片）、我的（账户设置 / 申请封禁玩家 / 申请服务器账号 / 管理中心 / 退出登录）

* **邮件模板同款磨砂玻璃**：`static/templates/emails/base.html` 统一白色磨砂玻璃卡片，验证码 / 指南审核 / 音频审核 / 背景图片审核 / 公共建筑审核 / 通用待审核提醒 / 广播邮件共用同一外层与样式；`services/mail/notify_admins()` 为统一的「通知所有管理员」入口

* **自定义音频播放器（磨砂玻璃风格）**：大喇叭音频列表、我的音频、管理员审核页均使用自研播放器替代默认控件，含进度条拖动、倍速（0.5x~2x）、音量（滑块弹层，记忆在 localStorage）与播放/暂停；同一时间只允许一个播放器出声。样式见 `static/css/base.css` 的 `.music-player`，逻辑见 `static/js/pages/music_player.js`

* **全站响应式适配**：窄屏下音频卡片操作按钮组自动占满整行并换行，管理员数据表格统一横向滚动，导航在小屏切换为右侧滑出菜单

* **模板宏复用**：音频状态徽章、复制链接按钮、复制时长按钮、播放器等提取到 `macros/music_macros.html` 公共宏，列表页与管理员页统一调用

* **统一弹窗模板系统**：`macros/modal.html` 提供弹窗骨架与页面级容器，配合 `base.js` 的 `CustomModal`（alert/confirm/prompt）统一全站弹窗，取代原生 `alert`/`confirm`/`prompt`

* **统一标签列表输入框**：`macros/forms.html` 的 `tags_field()` 宏 + `base.js` 的 `TagInput` 模块，输入后回车或点「添加」新增标签，可点叉号删除、支持粘贴自动拆分；底层为逗号分隔字符串，与后端解析兼容

* **统一进度条模板**：全站进度条由 `macros/progress.html` 的 `progress_track()` 宏渲染，样式集中在 `static/css/base.css` 的 `.progress-track` / `.progress-fill`；上传页、音频上传、自动维护、JS 动态创建一律复用同一套类名

### 交互效果

| 效果       | 实现方式                                                                                     |
| -------- | ---------------------------------------------------------------------------------------- |
| 鼠标光晕跟随   | `requestAnimationFrame` 平滑插值                                                            |
| 按钮水波纹    | CSS `ripple` 动画                                                                          |
| 滚动淡入     | `IntersectionObserver`                                                                   |
| 页面过渡     | `requestAnimationFrame` 控制 `.page-ready` 类切换                                           |
| 统一弹窗系统  | 磨砂玻璃风格，CSS 过渡动画 + 全局 `openModal`/`closeModal` 控制；CustomModal 提供 alert/confirm/prompt |
| Toast 提示 | 全站统一模板（图标 + 文案），CSS 关键帧驱动入场 / 退场动画，所有轻提示共用同一套                          |

### 性能优化

* **零外部依赖**：所有 CDN 资源（Lucide、Marked.js）下载到本地，无外部网络请求

* **前端资源按需加载**：页面级资源通过 `base.html` 的独立块按需引入，图形验证码弹窗仅需要验证码的页面加载，`uploader.js` / `search.js` 仅在实际上传页 / 搜索页加载

* **本地自定义字体**：正文与标题使用本地子集化 woff2（按 `unicode-range` 分片 + `font-display: swap`），无外部 CDN 请求

* **分段列表滚动自动加载**：带 `data-autoload-more` 属性的「加载更多」按钮由 `IntersectionObserver` 监听，进入视口即自动加载下一页

* `overflow-x: clip` 替代 `hidden`（消除滚动回弹）

* 尊重 `prefers-reduced-motion`（无障碍用户自动禁用动画）

* 触控设备降级光晕效果

* `IntersectionObserver` 触发后立即 `unobserve`

### 静态资源与引用规则

#### 静态资源更新

当升级第三方库版本时：

1. 修改 `scripts/build/build_static.py` 中的版本号
2. 运行 `python scripts/build/build_static.py` 重新下载
3. 提交 `static/lib/` 目录到 Git（`static/lib/monaco/` 除外）

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
│   ├── db/                   #   数据库连接（原生 sqlite3，每次调用新建连接）与 schema、雪花 ID 迁移
│   ├── system/               #   系统层：日志、启动检查、应用初始化
│   │   ├── init.py, logger.py, startup_checks.py
│   ├── shared/               #   共享工具（原 utils 收敛于此）
│   │   ├── snowflake.py      #   全站统一雪花 ID 生成器（非用户表主键唯一入口）
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
│   ├── backup/               #   自动维护（/uploads/ 全量 zip 极限压缩 + 日志清理）
│   ├── buildings/            #   公共建筑（列表/搜索/收藏/评论分页）
│   ├── mail/                 #   异步邮件发送
│   ├── game_accounts/        #   游戏账号注册申请
│   ├── game_server_ban/      #   游戏服务器封禁申请（审批 → 自动解封）
│   ├── system_metrics/       #   系统监控（CPU/内存/系统/性能追踪）
│   ├── music/                #   大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/                 #   RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── security/             #   安全扫描与内容过滤
│   ├── user/                 #   用户（认证/资料/管理）
│   ├── background_service/   #   背景图片业务（WebP 转换 + 按屏幕比例挑选）
│   ├── cleanup_service/      #   被驳回内容自动清理（统一定时调度）
│   ├── firewall/             #   高性能防火墙（DuckDB 引擎 + WSGI 门禁 + DDoS 防护）
│   │   ├── __init__.py       #     公共 API re-export（ban_ip / firewall 单例等）
│   │   ├── api_guard.py      #     接口频率限制（每 IP 每分钟）
│   │   ├── service/          #     业务层：core（封禁/白名单/警告）/ database（DuckDB）/ monitor（后台监控）
│   │   ├── protection/       #     防护策略：content_filter（内容注入）/ ddos / file_guard
│   │   └── transport/        #     连接层：wrappers（WSGI 门禁，直接断开连接）
│   ├── settings_manager/     #   系统设置管理
│   ├── sitemap_cache/        #   Sitemap 缓存服务
│   ├── content_limits/       #   待审核内容上限业务规则（从 core/helpers.py 下沉）
├── routes/                   # HTTP 路由层
│   ├── main/                 #   首页、登录、注册、设置、音乐
│   ├── admin/                #   管理后台（用户/自动维护/设置/日志/更新/游戏账号/指南/音乐/广播/背景/公共建筑等）
│   ├── api/                  #   JSON API（性能/统计/验证码/邮箱）
│   ├── backgrounds/          #   背景图片页面
│   ├── community/            #   社区辅助（AJAX / 表单统一响应）
│   ├── docs/                 #   文档页面
│   ├── game_accounts/        #   申请账号（页面+API，纯申请注册）
│   ├── guides/               #   服务器指南（页面+API）
│   ├── public/               #   公开文件服务
│   └── sitemap/              #   站点地图 & robots.txt
├── static/                   # 唯一前端文件夹：静态资源 + Jinja2 模板（命名规范见 docs/DEVELOPMENT.md）
│   ├── css/                  #   样式（base.css 手写样式 + tailwind.css 构建产物）
│   ├── js/                   #   前端脚本（core/ 通用组件、pages/ 页面脚本）
│   ├── favicons/             #   站点图标（可配置）
│   ├── lib/                  #   本地化第三方库与字体（构建生成）
│   ├── favicon.svg           #   站点默认图标
│   └── templates/            #   Jinja2 模板
│       ├── admin/                #     管理后台页面（无 admin_ 前缀）
│       ├── auth/                 #     登录 / 注册 / 找回密码
│       ├── settings/             #     用户个人设置
│       ├── site/                 #     站点级信息页（站点文档、服务器状态、网页地图）
│       ├── backgrounds/          #     背景图片页面（index / upload）
│       ├── emails/               #     邮件模板（独立 loader）
│       ├── game_accounts/        #     游戏账号页面（apply / ban_apply）
│       ├── guides/               #     服务器指南页面（index / detail / form）
│       ├── buildings/            #     公共建筑（index / create / detail）
│       ├── music/                #     大喇叭音频页面（index / my / favorites / upload）
│       ├── macros/               #     通用模板宏（模态框/编辑器/进度条/音乐/页面内搜索）
│       └── ...                   #     根级：base.html / index.html / error_simple.html
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

使用 **SQLite**（嵌入式单文件数据库），启用 **WAL 模式**（`PRAGMA journal_mode=WAL`）+ `synchronous=NORMAL` + `busy_timeout=30000`，读写并发性能优秀且崩溃可恢复。连接不做复用——每次 `get_db()` 新建一条独立连接、用完即关，事务边界天然隔离，不存在「跨线程共享连接导致事务边界错乱」的问题。首次启动自动建表，共 19 张表：

> ⚠️ **切勿删除 `uploads/db/site.db-wal` 与 `site.db-shm`。**
> WAL 模式下，「已经 `commit` 成功、但尚未 checkpoint 合并进主库」的数据全部保存在 `-wal` 文件里。删除它 = 丢掉最近写入的数据（曾导致「公共建筑审核通过后重启服务器又变回待审核」）。
> SQLite 打开数据库时会自动重放 WAL 完成恢复，最后一个连接关闭时也会自动 checkpoint 并清理，无需任何人工干预。

#### 读写与并发模型

**SQLite（主站）—— 由数据库自身的「单写者」机制保证写入串行：**

* SQLite 任意时刻只允许一个写事务，由文件锁统一排队；本层进一步把写事务改为 **`BEGIN IMMEDIATE`**（而非默认的 `BEGIN`）：事务一开始就独占写锁，而不是「先拿读锁、写时再升级」。
* 这样多线程并发写时 **不会出现两个事务同时持读锁、再抢写锁的升级冲突**（那正是「多线程写入时序问题」的根源）；配合 `busy_timeout=30000` 自动排队等待，做到写入天然串行、互不打断、不会锁升级死锁。
* 读取走独立连接并发进行；大批量改写（如 ID 迁移）或优雅退出前调用 `checkpoint()` 把 WAL 合并落盘。

**DuckDB（防火墙）—— 单写入线程 + FIFO 队列：**

* 所有写操作统一提交给唯一的写入线程顺序执行，相邻写操作合并为事务批量提交，彻底避免多线程并发写 DuckDB 的锁表问题；读走内存缓存与共享连接。
* **WAL 重放自愈**：历史版本用过 `CREATE SEQUENCE seq_firewall_bans` 作自增主键，迁移为雪花 ID 后序列被删；若进程在 CHECKPOINT 前异常退出，WAL 里会残留建/删序列记录，下次打开时 DuckDB 重放 WAL 报 `Sequence with name "seq_firewall_bans" already exists!` 导致整个库打不开（表现为备份里该库快照写入失败）。现在：
  1. **无条件清理遗留序列**（每次打开都幂等 `DROP SEQUENCE IF EXISTS`），从源头避免相关 DDL 再进入 WAL；
  2. 打开库后**强制 `CHECKPOINT`**、关闭前再 `CHECKPOINT`，把「已提交但仍在 WAL」的数据合并进主库并清空 WAL，避免 DDL 长期滞留；
  3. 打开失败时**自动自愈**：先把损坏的 `*.wal` 重命名隔离（`*.corrupt-wal-<时间戳>`）后重试，仍失败再隔离整个库文件并重建空库，保证防火墙功能不会因单文件损坏而整站不可用。

#### 雪花 ID

全站非用户表主键统一由 [`core/shared/snowflake.py`](core/shared/snowflake.py) 的 `next_id()` 生成（**唯一入口，禁止在别处自行拼接 ID**），结构为 **41 位毫秒时间戳 + 12 位序列号 = 53 位**（恒 ≤ 2^53-1，永不超过 JS 的 `Number.MAX_SAFE_INTEGER`，前端不会精度丢失）。

* **唯一生成者**：由一个独立「待命线程」独占计数器预生成 ID，计数器只被这一个线程读写，天然无竞态。
* **有界 FIFO 池**：生成的 ID 按顺序进入固定容量队列（默认 1024 个，约 32KB，**池满即阻塞，绝不无限预生成**）；单个 FIFO 保证每个 ID 只被发放一次。
* **取号零竞争**：`next_id()` 只是从池中取一个，O(1)、无锁竞争、无忙等——超高并发同时取号也不会「抢号」或重复；序列号用尽时的「等下一毫秒」由待命线程承担，调用方无感知。
* **时钟回拨保护**：系统对时导致时间戳回退时复用上一次时间戳、靠序列号继续推进，ID 仍单调递增。

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
| `backgrounds`             | 背景图片     | `status` 审核状态，WebP 格式，磁盘单主图（取图按屏幕比例挑选、原样返回，不缩放不裁剪），多张可同时启用，`rejected_at` 记录驳回时间（超 24h 自动删除）                                            |
| `game_account_registrations` | 游戏账号注册申请 | 申请注册 MC 账号，管理员审批                                                                                               |
| `game_account_bans`       | 游戏账号封禁   | 封禁 MC 账号申请资格                                                                                                    |
| `game_server_ban_applications` | 游戏服务器封禁申请 | 用户申请 → 管理员审批 → RCON ban，到期自动 pardon                                                                             |
| `public_buildings`        | 公共建筑     | 标题/领地名/介绍/使用方式/注意事项，审核工作流（pending→approved/rejected）                                                        |
| `building_comments`       | 建筑评论     | 外键 `building_id`，支持作者/管理员删除                                                                                       |
| `building_reports`        | 建筑举报     | 外键 `building_id`，待处理→驳回流程                                                                                         |
| `building_favorites`      | 建筑收藏     | 联合主键 `(user_id, building_id)`                                                                                   |
| `guide_favorites`         | 指南收藏     | 联合主键 `(user_id, guide_id)`                                                                                      |

#### 自动维护

每日凌晨 3:00（可配置）自动执行「自动维护」：

1. 扫描 `/uploads/` 目录下所有文件 → 极限压缩打包为 zip（ZIP_DEFLATED, level 9）→ 校验 zip 完整性 → 清理旧备份
2. **数据库以「一致快照」写入 zip**（`uploads/db/`）：主站 SQLite（`site.db`）用在线备份 API 导出，WAL 中「已提交但未 checkpoint」的数据会一并合并进快照；防火墙 DuckDB（`firewall.duckdb`）用引擎级导出（`ATTACH` + `COPY FROM DATABASE`）。运行期的 `-wal` / `-shm` / 原始 `.duckdb` 文件不直接复制（正被独占锁定且状态不一致），其数据已全部包含在快照里，恢复时单文件即可独立使用
3. **自动清理日志文件**：截断 `logs/app.log`，删除 `logs/fatal.log` 与 `logs/modules/*.log`（后台日志页面仍可查看本次运行期间的日志）

管理后台「自动维护」页可手动触发，显示实时进度条；备份目录（`BACKUP_DIR`）可在「系统设置」或「自动维护」页设置**绝对路径或相对路径**（相对路径基于网站根目录解析，默认 `../bhxz_backups`），保存后即时生效。已取消一键解压恢复功能，历史备份仅作留存与下载。

### 一键更新脚本

项目根目录下提供了一键更新脚本 [`update.py`](update.py)，纯 Python 全平台兼容，**只走下载覆盖**（不依赖 git），启动即更新、无需确认：

1. 运行 `python update.py`（可选 `--branch dev` 指定分支，默认 `main`，失败自动回退 `master`）
2. 脚本**多线程同时测速**全部镜像源（24 个：官方直连 / codeload / 前缀型代理 / 主机替换型镜像），单个镜像 2 秒超时，**整个测速环节最多 2 秒**；优先选取能返回合法 ZIP 且速度最快的镜像
3. 自动下载最新源码 ZIP（含 PK 魔数与 CRC 完整性校验，可识别镜像返回的 HTML 错误页），逐个镜像 × 逐个分支回退重试
4. 解压后**合并覆盖**项目代码（`_merge_copy`：同名覆盖、目标多余文件保留），随后进入第 5 步统一清理
5. **清理「GitHub 上已被删除」的文件与目录**：合并覆盖只会新增/覆盖，反映不了「新版删除」，故覆盖完成后按最新 ZIP 的文件清单递归清理——被移除的文件会删除、被移除的目录会整棵删除（例如更换字体后，旧字体的 woff2 子集一并清掉，不再残留）。`PROTECTED_PATHS` 中的路径**强制跳过、绝不删除**，包括：
   - 用户数据：`uploads/`（音频、背景图、sitemap，数据库也在 `uploads/db/`）
   - 运行期数据 / 本地配置：`db`、`backups`、`logs`、`ssl`、`release`、`.env`、`.env.local`、`.git`、`.venv`、`node_modules`
   - 本地生成物：`static/lib/monaco`、`uploads/ffmpeg`（Windows 下放置 ffmpeg.exe / ffprobe.exe，`uploads/` 已被 `.gitignore` 整目录排除）
   - 本地启动脚本：`start.bat`（未提交到仓库，本地自建）
   - 任意层级：`__pycache__`、`.pytest_cache`、`node_modules`、`.DS_Store`、`Thumbs.db`
6. 自动安装/更新 Python 依赖
7. **更新完成后提示手动重启服务器，不会自动启动**

> 字体等静态资源已随代码提交进仓库（`static/lib/fonts/`），因此一键更新即可同步字体，服务器无需联网构建、也无需额外步骤。
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
8. **全站安全响应标头**（`core/middleware.py` 集中下发，覆盖 HTML/API/SSE/静态资源）：

   * `Content-Security-Policy`：仅允许本站脚本/样式/资源，禁用 `object`，限制 `form-action`/`frame-ancestors` 等（已放行内联脚本/样式与 HLS blob worker，避免误伤自身功能）；`frame-src`/`child-src` 会按配置的「卫星地图地址」动态追加其源，供「网页地图」页内嵌外部地图

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
