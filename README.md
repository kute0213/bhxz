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

* **JetBrains Mono** — 编程字体

> 所有中文字体使用系统字体栈（各平台预装），**零下载、零延迟**。
> 一键更新时会自动运行构建脚本，无需手动操作。

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
├── core/         # 基础设施层（auth/server/web/system/db/shared）
│   ├── auth/                 #   认证装饰器、密码哈希
│   │   └── __init__.py
│   ├── server/               #   WSGI 服务器与优雅关闭
│   │   └── __init__.py
│   ├── web/                  #   Web 层：中间件、CSRF、错误页
│   │   ├── __init__.py, middleware.py, csrf.py, errors.py
│   ├── system/               #   系统层：日志、启动检查、应用初始化
│   │   ├── __init__.py, logger.py, startup_checks.py, init.py
│   ├── shared/               #   共享工具
│   │   └── scheduler/        #   统一任务注册表（task / executors / registry）
│   ├── db/                   #   数据库连接与 schema
│   ├── firewall/             #   高性能防火墙（DuckDB 引擎 + 连接级阻断 + DDoS 防护）
│   │   ├── __init__.py       #   全局单例 + 统一 API
│   │   ├── database.py       #   DuckDB 引擎
│   │   ├── service.py        #   封禁/白名单/警告/自动封禁
│   │   ├── connection_filter.py  # 连接级黑名单拦截 + 强制断开
│   │   ├── ddos.py           #   DDoS 检测（防误判）
│   │   ├── monitor.py        #   后台监控
│   │   └── wrappers.py       #   WSGI 门禁
├── services/     # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/               #   数据备份（/uploads/ 全量 zip 极限压缩）
│   ├── discussion/     # 讨论区（帖子/回复/分类）
│   ├── email/          # 异步邮件发送
│   ├── game_accounts/  # 游戏账号注册申请（审批/驳回/封禁）
│   ├── game_server_ban/ # 游戏服务器封禁申请（审批 → RCON ban → 到期自动 pardon）
│   ├── logging/        # 日志自动清理
│   ├── monitoring/     # CPU/内存/系统/性能追踪（后台线程采集）
│   ├── music/          # 大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/           # RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── updater/        # 自动更新（配置/核心逻辑）
│   ├── user/           # 用户（认证/资料/管理）
│   ├── attachment_service/  #   附件上传/清理
│   ├── background_service/  #   背景图片业务（WebP 转换 + 响应式变体）
│   ├── cleanup_service/     #   被驳回内容自动清理
│   ├── easy_auth_db/        #   EasyAuth 数据库直连验证
│   ├── settings_manager/    #   系统设置管理
│   └── sitemap_cache/       #   Sitemap 缓存服务
├── routes/       # HTTP 路由层（Flask Blueprint）
│   ├── admin/          # 管理后台（用户/备份/设置/日志/更新/游戏账号/指南/音乐/讨论等）
│   ├── api/            # 公开 API（性能/统计/验证码/邮箱）
│   ├── backgrounds/    # 背景图片页面
│   ├── buildings/      # 公共建筑（页面+API，发布即公开，无需审核）
│   ├── community/      # 社区留言板
│   ├── discussion/     # 讨论区（页面+API）
│   ├── docs/           # 文档页面
│   ├── firewall/       # 高性能防火墙（DuckDB 引擎 + 连接级阻断 + DDoS 防护 + 可疑访问拦截）
│   ├── game_accounts/  # 申请账号（页面+API，纯申请注册）
│   ├── guides/         # 服务器指南（页面+API）
│   ├── main/           # 主站（登录/注册/设置/音乐）
│   ├── public/         # 公开文件服务
│   └── sitemap/        # Sitemap & robots.txt（自动添加 Crawl-delay 防防火墙误判）
├── templates/    # Jinja2 模板
│   ├── admin/          # 管理后台页面
│   ├── backgrounds/    # 背景图片页面
│   ├── discussion/     # 讨论区页面
│   ├── emails/         # 邮件模板
│   ├── game_accounts/  # 游戏账号页面
│   ├── guides/         # 服务器指南页面
│   ├── buildings/      # 公共建筑（列表/详情/发布）
│   ├── macros/         # 通用模板宏（模态框/编辑/进度条/音乐）
│   ├── music/          # 大喇叭音频页面
│   ├── static/         # 静态资源（CSS/JS/本地化第三方库，随模板目录存放）
│   └── ...             # 基础页面（首页/登录/注册/设置/404/403）
├── utils/        # 共享工具函数（IP/限流/验证/验证码/安全扫描/模板辅助/子进程）
├── docs/         # 项目文档
├── scripts/      # 数据库迁移（migrate_db/、restore_db/）与测试（tests/）
├── uploads/      # 运行期上传数据
│   ├── attachments/    # 留言板/讨论区附件
│   ├── backgrounds/    # 全站背景图片
│   ├── community/      # 社区资源
│   ├── music/          # 大喇叭音频（每个音频一个 ID 目录，含 m3u8、ts 分片与唱片 MP3）
│   └── db/             # 数据库文件（site.db + firewall.duckdb）
├── backups/      # 数据备份
│   └── uploads/        # /uploads/ 全量 zip 极限压缩备份
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

* 讨论区管理（帖子置顶/锁定/删除 + 分类管理）

* 大喇叭音频管理（公开申请审核、查看全部音频、一键下架）

* 管理中心数据统计（含大喇叭音频总数与待审核数量）

* 系统设置（在线编辑，热重载，含网站图标选择、日志等级、背景图片开关、RCON 配置、MC 游戏文件夹）

* 系统日志（实时查看，SSE 推送，支持等级过滤、自动滚动；按时间顺序从上到下展示，与控制台一致）

* 数据备份（手动/自动，极限压缩 zip，进度条，一键解压恢复）

* 公开文件管理

* 广播邮件（富文本所见即所得编辑器 + 白名单 HTML 清洗，安全防 XSS）

* 手动更新脚本（`scripts/update.py` — 跨平台，从 GitHub 拉取最新代码，支持本地修改暂存与恢复）

* 游戏账号管理（注册申请审批、封禁列表管理）

* **游戏账号封禁**（用户申请 → 管理员审批 → RCON 自动执行）：用户在「申请封禁玩家」页提交封禁玩家名、QQ名、理由；管理员在管理中心「游戏账号封禁」页同意（可设封禁时长，留空为永久）或驳回；同意后经 RCON 执行 `ban 玩家游戏名`（无引号），到期由后台定时任务（每 60 秒检查一次，走 `(status, expires_at)` 索引，单周期最多处理 50 条）执行 `pardon 玩家游戏名`（无引号）自动解封；支持手动提前解封。玩家名经安全清洗杜绝 RCON 命令注入，RCON 执行失败自动保留状态下个周期重试

* 防火墙管理（IP 封禁/IP 白名单/违规警告：独立高性能 DuckDB 数据库，支持临时/永久封禁，全站 403 拦截，后台一键解封；自动识别可疑操作限流并自动封禁，各操作可独立开关、时长可配；**页面内直接编辑**自动封禁/可疑拦截/DDoS 防护开关与时长、白名单，无需跳转系统设置）

* 可疑访问拦截（识别 SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感文件与漏洞端点探测 / 恶意扫描 UA 等攻击特征，命中即拦截并自动封禁来源 IP，总开关与各攻击类型子开关独立配置、封禁时长可配，白名单 IP 不受影响）

* DDoS 攻击防护（高性能防火墙模块 `routes/firewall/`）：独立 DuckDB 数据库存储封禁/白名单/警告/攻击日志，连接级阻断在请求解析前直接强制断开黑名单 TCP 连接（自定义 Cheroot BanFilterConnection），不返回任何 HTTP 响应，客户端收到连接重置/EOF。按检测强度统计单位时间窗口内每个 IP 的请求数（低/中/高三档，检测窗口 10 秒），**防误判机制**：静态资源（`.css/.js/.ico`）、媒体文件（`.mp3/.ts/.m3u8/.webp`）、公共路径（`/static/`、`/music/<id>.mp3`、`/robots.txt`、`/sitemap.xml`）不计入请求计数，音频下载不会误判为 DDoS。超阈值自动封禁来源 IP（首次限时封禁；屡教不改升级永久封禁）。后台监控线程同步黑名单镜像、强制关闭已建立的空闲连接（先注销连接管理器再关闭，线程安全），定时清理过期数据与 VACUUM。检测强度、封禁时长、永久封禁触发次数等可在线热更新，白名单 IP 不受影响。robots.txt 自动添加 Crawl‑delay 与敏感路径 Disallow 规则，防止合法爬虫被误封

### 服务器指南

* 卡片式列表页，支持置顶与按标题自动排序

* Markdown 详情页（标题锚点、代码一键复制）

* 成员提交需审核，管理员直接发布

* 封禁机制（用户名/IP，限时或永久）

### 公共建筑

* 公共建筑列表页面，用户可发布自己的建筑（标题、领地名、介绍、使用方式、注意事项），**发布即公开，无需管理员审核**
* 一键复制传送指令 `/res tp 领地名`
* 评论功能：登录用户可发表评论，作者/管理员可删除评论
* 举报功能：用户可举报违规建筑，管理员在后台可查看举报并删除建筑
* 接入防火墙内容检测、防刷机制和图形验证码

### 讨论区

* 分类筛选、置顶优先、分页加载

* 回复实时刷新（默认 5 秒）

* Markdown 编辑 + 附件上传

### 大喇叭音频

* 「大喇叭音频」板块：上传音频自动转码为 HLS（m3u8），生成 `http://<主机>/music/<编号>.m3u8` 播放链接；同时生成**唱片 MP3**（`http://<主机>/music/<编号>.mp3`），供游戏内「电脑」下载后烧录成唱片

* 支持 mp3 / wav / ogg / m4a / flac，单文件不超过 100MB（依赖 ffmpeg）

* 自动调用内置 ffmpeg：Windows 用 `scripts/ffmpeg/ffmpeg.exe`，Linux/macOS 用 `scripts/ffmpeg/ffmpeg`，未内置时回退系统 PATH 中的 `ffmpeg`

* **公开需审核**：申请公开的音频进入「待审核」，管理员通过后才在游戏内大喇叭展示；**驳回后音频自动转为私有**，用户可重新申请公开或删除；已公开转私有再申请公开需重新审核

* **私有仅「不公开列出」而非「限制访问」**：所有音频（含私有/待审核）均可**凭链接访问**（播放 m3u8 / 下载唱片 MP3 / 拉取 HLS 分片均无需登录，不再限制上传者或管理员），私有只表示该音频不会出现在公开音频列表中——上传者分享链接给任何人即可播放

* **审核结果邮件通知**：管理员通过/驳回公开申请后，自动向上传者邮箱发送磨砂玻璃风格的审核结果邮件（通过 / 未通过状态卡），邮件未启用或上传者无邮箱时自动跳过

* **公开音频名称 / 标签搜索**：公开音频列表支持按名称或标签模糊搜索（`/music?q=关键词`，同时匹配 `title` 与 `tags` 列），无结果时给出空态提示

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
* 已接入：验证码清理、邮箱验证码清理、RCON 连接池清理、玩家列表追踪（含失败退避）、被驳回内容自动清理、每日 /uploads/ 全量 zip 备份、站点地图刷新、游戏服务器封禁到期自动解封

### 服务器性能监控

* CPU 使用率、内存占用、运行时间

* 公开页面，无需登录即可查看

* 后台线程每 5 秒自动采集数据并缓存，前端轮询读取

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

* **日志**：日志输出等级

* **数据备份**：自动备份时间、保留份数、超时

* **Sitemap**：刷新时间、站点域名、多域名列表、搜索引擎爬虫策略（robots.txt：允许所有 / 仅主页 / 禁止所有）

* **安全配置**：会话有效期、登录失败锁定次数及时间

* **防火墙**：自动封禁总开关、封禁时长（分钟，0 为永久）、白名单、登录/注册/找回密码/邮箱验证码异常各自独立开关

* **可疑访问拦截**：总开关、封禁时长（分钟，0 为永久）、SQL 注入 / XSS / 路径穿越 / 命令注入 / 敏感文件与漏洞端点探测 / 恶意扫描 UA 各攻击类型独立开关

* **DDoS 防护**：总开关、检测强度（low=宽松 300 次/10 秒 / medium=中等 150 次/10 秒 / high=严格 80 次/10 秒）、首次封禁时长（分钟，0 为直接永久封禁）、永久封禁触发次数（违规记录时间窗口内多次触发自动升级永久封禁）、违规记录时间窗口（小时）

* **讨论区配置**：回复实时刷新间隔、每页加载数量

* **外部链接**：卫星地图地址、QQ 群链接

* **邮件配置**：SMTP 服务器、端口、SSL、发件邮箱与授权码

* **背景图片**：显示开关、显示方式（cover/contain/auto）

* **网站图标**：favicon 图标选择（compass/mountain/star/heart），管理后台可在线切换

* **服务器配置**：监听地址、端口、调试模式、工作线程数

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
| `SECRET_KEY`                  | Session 密钥                                | `mc_server_site_random_secret_key_2024`     |
| `REGISTER_VERIFY_CODE`        | 注册验证码                                     | `binhai_xz`                                 |
| `BACKUP_SCHEDULED_TIME`       | 每日自动备份时间                                  | `03:00`                                     |
| `MAX_BACKUPS`                 | 最大保留备份份数                                  | `30`                                        |
| `DISCUSSION_REFRESH_INTERVAL` | 讨论区回复刷新间隔                                 | `5s`                                        |
| `REPLIES_PER_PAGE`            | 讨论区回复每页数量                                 | `10`                                        |
| `LOG_LEVEL`                   | 日志输出等级（DEBUG/INFO/WARNING/ERROR/CRITICAL） | `INFO`                                      |
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
| `ENABLE_SSL` | 启用 HTTPS | `0`（禁用） |
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

### SSL 证书

```bash
mkdir ssl && cp /path/to/private.key ssl/ && cp /path/to/fullchain.pem ssl/
export ENABLE_SSL=1 && python app.py
```

未找到证书或未设置 `ENABLE_SSL` 时，自动回退 HTTP 模式。

## API 接口

所有 API 以 `/api` 为前缀，返回 JSON。

### 公开接口

| 端点                             | 说明                        |
| ------------------------------ | ------------------------- |
| `GET /api/performance`         | 服务器性能数据（CPU/内存/运行时间/在线玩家） |
| `GET /api/stats`               | 网站统计数据                    |
| `GET /api/captcha/generate`    | 生成图形验证码                   |
| `POST /api/captcha/verify`     | 验证图形验证码                   |
| `POST /api/email/send-code`    | 发送邮箱验证码                   |
| `GET /api/email/check-enabled` | 检查邮件功能是否启用                |

### 申请账号 API（需登录）

| 方法   | 路径                                   | 说明                 |
| ---- | ------------------------------------ | ------------------ |
| GET  | `/game-accounts/apply`               | 申请注册页面             |
| POST | `/game-accounts/api/apply-register`  | 提交注册申请（需图形验证码）    |

### 申请账号管理 API（管理员）

| 方法     | 路径                                                   | 说明               |
| ------ | ---------------------------------------------------- | ---------------- |
| GET    | `/admin/game-accounts`                               | 游戏账号管理页面         |
| GET    | `/admin/api/game-accounts/applications`              | 获取注册申请列表         |
| POST   | `/admin/api/game-accounts/applications/<id>/approve` | 批准申请（自动 RCON 注册） |
| POST   | `/admin/api/game-accounts/applications/<id>/reject`  | 驳回申请             |
| GET    | `/admin/api/game-accounts/bans`                      | 获取封禁列表           |
| POST   | `/admin/api/game-accounts/bans`                      | 封禁账号申请资格         |
| DELETE | `/admin/api/game-accounts/bans/<username>`           | 解除封禁             |

### 社区 AJAX 端点

| 方法   | 路径                                 | 说明           |
| ---- | ---------------------------------- | ------------ |
| POST | `/discussion/<id>/reply`           | 回复帖子         |
| POST | `/discussion/reply/<id>/delete`    | 删除回复         |
| GET  | `/discussion/<id>/api/replies`     | 分页获取回复       |
| GET  | `/discussion/<id>/api/new-replies` | 获取最新回复（实时刷新） |
| POST | `/discussion/<id>/pin`             | 置顶/取消置顶（管理员） |
| POST | `/discussion/<id>/lock`            | 锁定/解锁（管理员）   |
| POST | `/discussion/<id>/delete`          | 删除帖子         |

### 大喇叭音频 AJAX 端点

| 方法   | 路径                                 | 说明                              |
| ---- | ---------------------------------- | ------------------------------- |
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

* **统一弹窗模板系统**：`templates/macros/modal.html` 提供 `modal_overlay`（CustomModal 骨架）、`modal_shell`（页面级弹窗容器，支持尺寸/图标/颜色自定义）、`modal_captcha`（图形验证码弹窗）、`modal_close_script`（全局 `openModal`/`closeModal` 控制器）四组宏，配合 `base.js` 的 `CustomModal`（alert/confirm/prompt）统一全站所有弹窗样式，取代全部原生 `alert`/`confirm`/`prompt` 及手写弹窗

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

* **系统字体栈**：中文字体使用各平台预装字体（PingFang SC / Noto Sans CJK），零下载、零延迟

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

* 内置 Cheroot WSGI 服务器，`python app.py` 即可独立运行

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
         public/      discussion/（topics / replies / categories）
         admin/       music/（constants / queries / crud / upload / favorites）
         api/         rcon/（client / pool / easy_auth）
         discussion/  email/（service / code / templates / sanitize）
         guides/      updater/（config / core）
         backgrounds/ backup/（manager / scheduler）
         sitemap/     attachment_service/（附件上传/清理）
         game_accounts/ background_service/（背景图片业务）
                      cleanup_service/（被驳回内容自动清理）
                      settings_manager/（系统设置管理）
                      sitemap_cache/（Sitemap 缓存）
                      easy_auth_db/（EasyAuth 数据库直连）
                      monitoring/（系统性能监控）
                      logging/（日志自动清理）
```

| 层级     | 目录          | 职责                                              | 禁止                                |
| ------ | ----------- | ----------------------------------------------- | --------------------------------- |
| **入口** | `app.py`    | Flask 实例、蓝图注册、WSGI 服务器                          | 不得包含业务逻辑                          |
| **路由** | `routes/`   | HTTP 请求解析、参数校验、Session 管理、响应构造                  | 不得包含 SQL、事务、业务逻辑                  |
| **服务** | `services/` | 纯业务逻辑，Flask 无关，返回 `(success, data_or_error)` 元组 | 不得导入 Flask、不得直接操作 request/session |
| **核心** | `core/`     | 数据库连接、认证装饰器、中间件、Web 工具、系统工具、防火墙                | 不得包含业务逻辑，不得导入 services            |

### 目录结构

```
workspace/
├── app.py                    # Flask 入口 + WSGI 服务器
├── config.py                 # 全局配置
├── requirements.txt          # Python 依赖
├── core/                     # 基础设施层
│   ├── auth/                 #   认证装饰器、密码哈希
│   │   └── __init__.py
│   ├── server/               #   WSGI 服务器与优雅关闭
│   │   └── __init__.py
│   ├── web/                  #   Web 层：中间件、CSRF、错误页
│   │   ├── __init__.py, middleware.py, csrf.py, errors.py
│   ├── system/               #   系统层：日志、启动检查、应用初始化
│   │   ├── __init__.py, logger.py, startup_checks.py, init.py
│   ├── shared/               #   共享工具
│   │   └── scheduler/        #   统一任务注册表（task / executors / registry）
│   ├── db/                   #   数据库连接与 schema
│   ├── firewall/             #   高性能防火墙（DuckDB 引擎 + 连接级阻断 + DDoS 防护）
│   │   ├── __init__.py       #   全局单例 + 统一 API
│   │   ├── database.py       #   DuckDB 引擎
│   │   ├── service.py        #   封禁/白名单/警告/自动封禁
│   │   ├── connection_filter.py  # 连接级黑名单拦截 + 强制断开
│   │   ├── ddos.py           #   DDoS 检测（防误判）
│   │   ├── monitor.py        #   后台监控
│   │   └── wrappers.py       #   WSGI 门禁
├── services/                 # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/               #   数据备份（/uploads/ 全量 zip 极限压缩）
│   ├── discussion/           #   讨论区（帖子/回复/分类）
│   ├── email/                #   异步邮件发送
│   ├── game_accounts/        #   游戏账号注册申请
│   ├── monitoring/           #   系统监控（CPU/内存/系统/性能追踪）
│   ├── music/                #   大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/                 #   RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── updater/              #   自动更新（配置/核心逻辑）
│   ├── user/                 #   用户（认证/资料/管理）
│   ├── attachment_service/   #   附件上传/清理
│   ├── background_service/   #   背景图片业务（WebP 转换 + 响应式变体）
│   ├── cleanup_service/      #   被驳回内容自动清理（统一定时调度）
│   ├── easy_auth_db/         #   EasyAuth 数据库直连验证
│   ├── settings_manager/     #   系统设置管理
│   ├── sitemap_cache/        #   Sitemap 缓存服务
├── routes/                   # HTTP 路由层
│   ├── main/                 #   首页、登录、注册、设置、音乐
│   ├── admin/                #   管理后台（用户/备份/设置/日志/更新/游戏账号/指南/音乐/讨论/广播/背景/公共建筑等）
│   ├── api/                  #   JSON API（性能/统计/验证码/邮箱）
│   ├── backgrounds/          #   背景图片页面
│   ├── community/            #   社区留言板
│   ├── discussion/           #   讨论区（页面+API）
│   ├── docs/                 #   文档页面
│   ├── game_accounts/        #   申请账号（页面+API，纯申请注册）
│   ├── guides/               #   服务器指南（页面+API）
│   ├── public/               #   公开文件服务
│   └── sitemap/              #   站点地图 & robots.txt
├── templates/                # Jinja2 模板
│   ├── admin/                #   管理后台页面
│   ├── backgrounds/          #   背景图片页面
│   ├── discussion/           #   讨论区页面
│   ├── emails/               #   邮件模板
│   ├── game_accounts/        #   游戏账号页面
│   ├── guides/               #   服务器指南页面
│   ├── macros/               #   通用模板宏（模态框/编辑器/进度条/音乐）
│   ├── music/                #   大喇叭音频页面
│   ├── static/               #   静态资源（CSS/JS/本地化第三方库，构建生成 lib/）
│   └── ...                   #   基础页面
├── docs/                     # 项目文档
└── scripts/
    ├── build/                #   构建脚本
    └── ...                   #   工具脚本
```

### 技术栈

| 类别       | 选型                            |
| -------- | ----------------------------- |
| 后端框架     | Flask 3.x                     |
| WSGI 服务器 | Cheroot（内置）                   |
| 数据库      | SQLite（WAL 模式，嵌入式单文件）         |
| 模板引擎     | Jinja2                        |
| CSS      | Tailwind CSS + 自定义样式（白色磨砂玻璃） |
| 图标       | Lucide（本地化）                   |
| Markdown | marked.js / Python Markdown   |

### 异步架构

| 组件      | 异步方式                               |
| ------- | ---------------------------------- |
| 日志写入器   | 队列 + 后台线程批量写入                      |
| 统一任务注册表 | 单 tick 线程每秒检测 + 共享线程池派发（`core/shared/scheduler/`，全站定时任务共用，防火墙除外） |
| IP 地理信息 | 后台线程异步更新缓存                         |
| CPU 监控  | 后台线程定期采样（2 秒）                      |

### 数据库

使用 **SQLite**（嵌入式单文件数据库），启用 **WAL 模式**（`PRAGMA journal_mode=WAL`）+ `synchronous=NORMAL` + `busy_timeout=30000`，读写并发性能优秀且崩溃可恢复；单例共享连接 + 可重入锁保证多线程安全。首次启动自动建表，共 17 张表：

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
| `discussion_categories`   | 讨论分类     | slug 唯一                                                                                                         |
| `discussion_topics`       | 讨论帖子     | 支持分类/标签/附件/置顶/锁定                                                                                                |
| `discussion_replies`      | 讨论回复     | 外键 `topic_id`，支持附件                                                                                              |
| `music`                   | 大喇叭音频    | `status` 状态机（0=私有/1=待审核/2=已公开，驳回后自动转为私有；旧库 `gain` 列仅保留不再使用），`tags` 逗号分隔标签列，删除记录时同步删除 `uploads/music/<ID>/` 文件目录 |
| `music_favorites`         | 大喇叭音频收藏  | 联合主键 `(user_id, music_id)`（同一用户对同一音频仅一条收藏）                                                                      |
| `backgrounds`             | 背景图片     | `status` 审核状态，WebP 格式，响应式变体，`rejected_at` 记录驳回时间（超 24h 自动删除）                                            |
| `game_account_registrations` | 游戏账号注册申请 | 申请注册 MC 账号，管理员审批                                                                                               |
| `game_account_bans`       | 游戏账号封禁   | 封禁 MC 账号申请资格                                                                                                    |
| `public_buildings`        | 公共建筑     | 标题/领地名/介绍/使用方式/注意事项，审核工作流（pending→approved/rejected）                                                        |
| `building_comments`       | 建筑评论     | 外键 `building_id`，支持作者/管理员删除                                                                                       |
| `building_reports`        | 建筑举报     | 外键 `building_id`，待处理→驳回流程                                                                                         |

> 旧版 DuckDB 数据库（`site.duckdb`）可通过 `scripts/migrate_db.py` 一键迁移到 SQLite（迁移前会自动备份旧库）。

#### 数据备份

每日凌晨 3:00（可配置）自动执行：

1. 扫描 `/uploads/` 目录下所有文件 → 极限压缩打包为 zip（ZIP_DEFLATED, level 9）→ 校验 zip 完整性 → 清理旧备份

管理后台支持手动触发，显示实时进度条；支持一键解压恢复。

### 手动更新脚本

项目提供了手动更新脚本 [`scripts/update.py`](scripts/update.py)，通过 Git 从 GitHub 拉取最新代码：

1. 运行 `python scripts/update.py`
2. 脚本自动检测 git 环境和远程更新
3. 显示更新内容预览（最近提交记录），确认后执行
4. 支持本地修改暂存（`git stash`），更新后自动恢复
5. 更新完成后提示手动重启服务器

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

9. **极高性能多线程防火墙**（`core/firewall/`，运行于 WSGI 入口、先于一切 Flask 逻辑）：黑名单 IP 的请求不参与任何业务处理，直接返回最小 403 响应并标记 `Connection: close`；后台监控线程周期性从数据库同步黑名单镜像、利用 Cheroot 连接特性（`linger=False` + `close()`）强制关闭黑名单 IP 的现存连接（含 keep-alive 空闲与处理中的请求），客户端表现为连接被重置；配套 DDoS 攻击检测按强度自动封禁（详见上文功能特性）。

## 开发注意事项

编写新代码前必查的**分层规范、易错点清单与测试要求**，详见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 更新日志

详见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 最近更新

* **修复管理员删除用户失败 + 清理废弃代码**：修复管理后台删除用户时因引用已删除的 `poll_votes`、`board_topics`、`board_replies` 表导致数据库操作失败的问题，改为级联清理 `discussion_topics`/`discussion_replies`（当前使用的讨论区表）；同步修复用户注销功能的相同问题，修复 `_clean_user_attachments` 函数引用废弃表的问题；优化 `routes/admin/mod_intros/__init__.py` 中三处嵌套 try-except 屎山代码为单层。

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

* **修复背景图片与评论等删除失败问题**：背景图片删除时 `remove_background_files` 对 `sqlite3.Row` 使用 `.get()` 导致 `AttributeError`，已改为按键访问；讨论区删除的 AJAX 统一响应 `_respond` 重定向端点从不存在的 `community.community_page` 改为 `main.home`，避免 `url_for` 构建失败返回 500；前端回复删除错误提示统一为「删除失败，请重试。」。删除权限校验正常返回 JSON 失败结果而非 500。

* **背景图片按屏幕比例最适配取图**：保存时自动记录图片自然宽高比（`backgrounds.ratio`，不再强制裁剪 16:9）；客户端在页面解析到背景元素后立即预加载（不等动画与其他脚本），自动携带屏幕宽高比与物理像素长边请求图片；服务端将所选档位中心裁剪到该比例后返回（结果缓存）。横屏/竖屏均获得与屏幕比例完全匹配且像素充足的图片，移动端清晰度大幅提升。

* **统一定时调度算法**：新增 `core/shared/scheduler/` 统一定时调度（固定间隔含失败退避 / 每日时间点、优雅停止），已接入被驳回内容自动清理、每日备份、玩家列表追踪、验证码清理、连接池清理、站点地图刷新，行为与原逻辑一致。

* **导航栏动画流畅度优化**：下拉 caret 与滚动收缩动画补上 `will-change: transform` 合成层提示，动画更流畅，视觉效果与时长完全不变。

* **新增 IP 封禁功能**：管理后台新增「IP 封禁」页面（`/admin/ip-bans`），支持添加/解除封禁 IP（IPv4/IPv6/CIDR 段），可设置临时封禁时长或永久封禁并填写原因；被封禁 IP 的所有请求由中间件统一拦截返回 403；内置 30 秒缓存降低查询压力，临时封禁到期自动清理。

* **背景图片优化**：审核通过后自动设为「当前显示」背景（无需手动再开启）；上传文件统一按 `bg_<id>_<hash>.webp` 命名，不再保留原始文件名。

* **全站 UI 优化为白色浅蓝磨砂玻璃风格**：主页由深色海洋风格全面转换为白色浅蓝主题（滚动时背景图片保持可见，标题深色 + 浅蓝渐变强调）；全站图标统一为浅蓝色；进度条与滚动条改为浅蓝渐变磨砂玻璃风格；修复 `/backgrounds` 页面「当前显示」按钮与状态徽章浅色文字浅色底融合不可见的问题，黄色/绿色等状态文字改为深色可读版本。

* **控件全面改为白色略微透明磨砂玻璃**：主按钮（`.btn-primary`）由黑色渐变改为白色半透明磨砂玻璃（深色文字 + 蓝色强调边），次按钮/危险按钮/输入框/导航/弹窗/Toast 等控件统一为白色磨砂玻璃质感，更好适配全站背景图片；深色工具类（`.bg-forest-900` 系列）全局映射为白色半透明背景；Markdown 编辑器面板、讨论区与指南正文的代码块保持深色卡片保证可读性，行内代码改为浅蓝底深蓝字；浅色状态文字（红/黄/绿/蓝 300/400 系列）全局映射为深色可读版本（代码块内除外）；指南卡片、广播富文本编辑器、更新日志面板等同步改为白色磨砂玻璃。

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

* **UI 改回白色页面 + 黑色控件**：全站由深色主题改为白色磨砂玻璃风格（白色卡片 + 深色控件），磨砂玻璃质感保留；导航栏大屏端（≥1024px）改为「首页 / 导航 / 互动 / 账号」悬停下拉菜单（导航=指南/讨论/服务器状态，互动=大喇叭音频/背景图片/游戏账号，账号=设置/管理/退出），小屏端保持右侧滑出菜单；下拉使用 CSS 过渡动画流畅展开

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

* **项目结构优化**：将大文件按功能模块拆分为子包，`services/music_service.py` → `services/music/`（常量/查询/CRUD/上传/收藏），`services/user_service.py` → `services/user/`（认证/资料/管理），`services/updater.py` → `services/updater/`（配置/核心逻辑），`services/discussion_service.py` → `services/discussion/`（帖子/回复/分类）；保留原文件作为兼容性重导出层，旧代码无需修改导入路径。

* **一键更新重写**：重写 `services/updater/core.py` 更新逻辑，实现跨平台独立重启脚本（Windows 批处理 / Linux Shell），通过 `tasklist` 检测旧进程退出后启动新进程，解决 Windows 环境下更新后服务器无法正常重启的问题。修复前端日志重复显示问题，调整重启检测时机避免误判。

- **启动健康检查取代更新脚本**：移除更新脚本功能，新增 `core/system/startup_checks.py`，每次启动固定运行服务器健康检查——数据库完整性、文件结构、配置完整性、uploads 目录结构检查，自动尝试修复且不删除任何文件。`core/system/init.py` 集成该检查，在数据库初始化前执行。

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

