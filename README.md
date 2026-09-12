# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用白色磨砂玻璃（White Frosted Glass）设计风格。提供用户系统、游戏账号管理、模组介绍、管理后台、服务器状态监控、全站背景图片、网站图标可配置等功能。

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
├── core/         # 基础设施层（DB/认证/中间件/服务器）
│   ├── db/             # 数据库连接与 schema
│   ├── auth.py         # 认证装饰器、密码哈希
│   ├── middleware.py   # 请求中间件
│   ├── startup_checks.py # 启动服务器健康检查（数据库/文件/配置，自动修复）
│   └── ...             # 模板上下文、服务器、CSRF、日志
├── services/     # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/         # 数据库备份与恢复
│   ├── discussion/     # 讨论区（帖子/回复/分类）
│   ├── email/          # 异步邮件发送
│   ├── game_accounts/  # 游戏账号绑定与注册申请
│   ├── logging/        # 日志自动清理
│   ├── monitoring/     # CPU/内存/系统/性能追踪（后台线程采集）
│   ├── music/          # 大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/           # RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── updater/        # 自动更新（配置/核心逻辑）
│   ├── user/           # 用户（认证/资料/管理）
│   └── ...             # 其他单文件服务（附件/背景/验证码/限流/调度/设置/等）
├── routes/       # HTTP 路由层（Flask Blueprint）
│   ├── admin/          # 管理后台（用户/备份/设置/日志/更新/游戏账号/指南/音乐/讨论等）
│   ├── api/            # 公开 API（性能/统计/验证码/邮箱）
│   ├── backgrounds/    # 背景图片页面
│   ├── community/      # 社区留言板
│   ├── discussion/     # 讨论区（页面+API）
│   ├── docs/           # 文档页面
│   ├── game_accounts/  # 游戏账号绑定与注册
│   ├── guides/         # 服务器指南（页面+API）
│   ├── main/           # 主站（登录/注册/设置/音乐）
│   └── public/         # 公开文件服务
├── templates/    # Jinja2 模板
│   ├── admin/          # 管理后台页面
│   ├── backgrounds/    # 背景图片页面
│   ├── discussion/     # 讨论区页面
│   ├── emails/         # 邮件模板
│   ├── game_accounts/  # 游戏账号页面
│   ├── guides/         # 服务器指南页面
│   ├── macros/         # 通用模板宏（模态框/编辑/进度条/音乐）
│   ├── music/          # 大喇叭音频页面
│   └── ...             # 基础页面（首页/登录/注册/设置/404/403）
├── static/       # 静态资源（CSS/JS/本地化第三方库）
├── docs/         # 项目文档
├── scripts/      # 构建（build/）与测试（tests/）
├── uploads/      # 运行期上传数据
│   ├── attachments/    # 留言板/讨论区附件
│   ├── backgrounds/    # 全站背景图片
│   ├── community/      # 社区资源
│   └── music/          # 大喇叭音频（每个音频一个 ID 目录，含 m3u8、ts 分片与唱片 MP3）
├── backups/      # 数据库备份
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

* 用户管理、模组介绍管理

* 服务器指南 CRUD + 审核工作流 + 编辑封禁

* 讨论区管理（帖子置顶/锁定/删除 + 分类管理）

* 大喇叭音频管理（公开申请审核、查看全部音频、一键下架）

* 管理中心数据统计（含大喇叭音频总数与待审核数量）

* 系统设置（在线编辑，热重载，含网站图标选择、日志等级、背景图片开关、RCON 配置、MC 游戏文件夹）

* 系统日志（实时查看，SSE 推送，支持等级过滤、自动滚动）

* 数据库备份（手动/自动，进度条，一键恢复）

* 公开文件管理

* 广播邮件（富文本所见即所得编辑器 + 白名单 HTML 清洗，安全防 XSS）

* 一键更新（从 GitHub 自动拉取 + 实时进度条 + 自动重启）

* 游戏账号管理（注册申请审批、封禁列表管理）

### 服务器指南

* 卡片式列表页，支持置顶与按标题自动排序

* Markdown 详情页（标题锚点、代码一键复制）

* 成员提交需审核，管理员直接发布

* 封禁机制（用户名/IP，限时或永久）

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

### 服务器性能监控

* CPU 使用率/温度、内存占用、运行时间

* 公开页面，无需登录即可查看

* 后台线程每 5 秒自动采集数据并缓存，前端轮询读取

### Minecraft 在线玩家

* 通过 RCON 连接 Minecraft 服务器，实时获取在线玩家列表

* 后台线程每 5 秒执行 `/list` 命令，缓存结果

* 支持系统设置中配置 RCON 地址、端口、密码

### 游戏账号管理

* 一个网站账号只能绑定一个服务器账号（已绑定时需先解绑再绑定其他账号）

* 绑定通过 RCON 执行 `/auth getPlayerInfo 玩家名` 获取 BCrypt 密码哈希，服务端校验密码；绑定/修改密码前需完成图形验证码

* 绑定后可在线修改 MC 账号密码（通过 EasyAuth 数据库直连或 RCON，数据库从 MC\_GAME\_FOLDER 自动发现）

* 申请注册 MC 游戏账号（需图形验证码 + 管理员审批，审批通过后自动 RCON 添加白名单）

* 管理员可批准/驳回申请，封禁恶意账号

### 文档系统

* Markdown 文档渲染（marked.js）

* 代码块一键复制按钮

* 侧边栏导航

## 配置说明

### 管理后台在线编辑（推荐）

所有运行时配置均可在 **管理后台 → 系统设置** 中在线编辑，修改后立即生效（热重载），无需重启服务器。

支持编辑的配置分类：

* **日志**：日志输出等级

* **数据库备份**：自动备份时间、保留份数、超时、备份前 CHECKPOINT

* **Sitemap**：刷新时间、站点域名、多域名列表

* **安全配置**：会话有效期、登录失败锁定次数及时间

* **讨论区配置**：回复实时刷新间隔、每页加载数量

* **外部链接**：卫星地图地址、QQ 群链接

* **邮件配置**：SMTP 服务器、端口、SSL、发件邮箱与授权码

* **一键更新**：更新时是否构建静态资源、不替换的文件列表、自定义 GitHub 代理

* **背景图片**：显示开关、显示方式（cover/contain/auto）

* **网站图标**：favicon 图标选择（compass/mountain/star/heart），管理后台可在线切换

* **服务器配置**：监听地址、端口、调试模式、工作线程数

* **RCON 配置**：服务器 RCON 地址/端口/密码、MC 游戏文件夹

* **网站备案**：工信部备案号、公安备案号、版权年份与站点名称

### config.py

| 配置项                           | 说明                                        | 默认值                                         |
| ----------------------------- | ----------------------------------------- | ------------------------------------------- |
| `DB_PATH`                     | 数据库文件路径                                   | `./site.db`                                 |
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

### 环境变量

| 变量名          | 说明       | 默认值     |
| ------------ | -------- | ------- |
| `ENABLE_SSL` | 启用 HTTPS | `0`（禁用） |

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

### 游戏账号 API（需登录）

| 方法   | 路径                                   | 说明                 |
| ---- | ------------------------------------ | ------------------ |
| GET  | `/game-accounts/`                    | 游戏账号首页（已绑定列表）      |
| POST | `/game-accounts/api/bind`            | 绑定 MC 账号（需图形验证码）     |
| POST | `/game-accounts/api/unbind`          | 解绑 MC 账号           |
| GET  | `/game-accounts/api/bound`           | 获取已绑定账号列表          |
| POST | `/game-accounts/api/change-password` | 修改绑定的 MC 账号密码      |
| POST | `/game-accounts/api/apply-register`  | 申请注册 MC 游戏账号（需验证码） |

### 游戏账号管理 API（管理员）

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

* **桌面端悬停下拉导航栏**：大屏端（≥1024px）主导航为「首页 / 导航 / 互动 / 账号」，其中「导航 / 互动 / 账号」为悬停下拉菜单（CSS 过渡动画，`cubic-bezier` 弹性曲线流畅展开）；小屏端保持右侧滑出菜单不变

* **邮件模板同款磨砂玻璃**：`templates/emails/base.html` 统一白色磨砂玻璃卡片（背景光晕 + 噪点纹理 + 光线散射层 + 顶部高光描边 + 状态卡），验证码 / 指南审核 / 音频审核 / 广播邮件共用同一外层与样式

* **自定义音频播放器（磨砂玻璃风格）**：大喇叭音频列表（`/music`）、我的音频（`/music/my`）、管理员审核页（`admin/admin_music.html`）均使用自研播放器替代浏览器默认控件，含进度条（点击/拖动 seek、缓冲显示，**圆点（thumb）跟随进度实时移动**）、倍速（0.5x~2x）、音量（按钮+滑块弹层，音量记忆在 localStorage）与播放/暂停，窄屏（≤480px）自动占满整行，且倍速/音量弹层窄屏时改为右对齐，避免超出卡片/视口被裁切；每个 `.music-player` 独立实例化并拥有独立的 HLS 实例与 `Audio` 元素，同一时间只允许一个播放器出声，列表内多个音频均可独立播放；样式见 `static/css/base.css` 的 `.music-player`（倍速/音量弹层 `z-index:100` 向上展开；内含播放器的卡片使用 `.pixel-card.music-card` 显式解除 `contain:paint`/`content-visibility` 的溢出裁切，弹层不被遮挡/裁切），逻辑见 `static/js/pages/music_player.js`，HLS 播放依赖本地 `static/lib/hls/hls.min.js`（构建脚本 `scripts/build/build_static.py` 自动下载）

* **全站响应式适配所有屏幕**：竖屏/窄屏（≤640px）下音频卡片操作按钮组（复制广播 m3u / 唱片 MP3 / 时长 Ns / 审核操作）通过 `.music-card-actions` 自动占满整行并换行排列，不再横向溢出被裁切导致「穿模」、无法点击；全局 `body` 增加 `overflow-wrap: break-word` 兜底长文本换行，配合 `overflow-x: clip` 杜绝横向滚动；小屏端导航使用右侧滑出菜单，大屏端使用悬停下拉导航，管理员数据表格统一 `overflow-x-auto` 横向滚动、指南/文档 `pre/table` 自带横向滚动，全站各页面均可适配任意屏幕尺寸

* **模板宏复用**：`templates/macros/music_macros.html` 提取音频状态徽章、复制广播 m3u 链接按钮、复制唱片 MP3 按钮、复制时长（秒）按钮、自定义播放器（`music_audio_player`）与播放器脚本（`music_player_assets`）为公共宏，`music/list.html`、`music/my.html` 与 `admin/admin_music.html` 统一调用，消除重复代码

* **全局弹窗模板**：`templates/macros/modal.html` 提供 `modal_overlay` 宏，统一渲染自定义弹窗骨架（alert / confirm / prompt 共用），由 `base.html` 引入一次，配合 `core/base.js` 的 `CustomModal` 控制，取代全部原生 `alert` / `confirm` / `prompt`

### 交互效果

| 效果       | 实现方式                                                                                                                                                 |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 鼠标光晕跟随   | `requestAnimationFrame` 平滑插值                                                                                                                         |
| 按钮水波纹    | CSS `ripple` 动画                                                                                                                                      |
| 滚动淡入     | `IntersectionObserver`                                                                                                                               |
| 页面过渡     | `requestAnimationFrame` 控制 `.page-ready` 类切换                                                                                                         |
| 自定义弹窗    | 磨砂玻璃风格，放大居中动画、触发元素位置感知；`CustomModal` 统一提供 alert / confirm / prompt（Promise + 回调双风格），自动拦截 `onsubmit="return confirm(...)"` 表单与 `onclick` 确认链接，全站无原生弹窗 |
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
3. 提交 `static/lib/` 目录到 Git（`static/lib/monaco/` 除外）

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
  Flask    蓝图/路由   纯 Python 函数    DB/认证/工具
             │            │
         main/        user/（auth.py / profile.py）
         docs/        game_accounts/（binding_service.py / registration_service.py）
         public/      attachment_service.py
         admin/       discussion/（topics.py / replies.py / categories.py）
         api/         music/（constants.py / queries.py / crud.py / upload.py / favorites.py）
         discussion/  rcon/（client.py / pool.py / easy_auth.py）
         guides/      updater/（config.py / core.py）
         backgrounds/ backup/（manager.py / scheduler.py）
         game_accounts/ captcha.py （验证码）
                       easyauth_bind.py （游戏账号密码验证）
                       ratelimit.py （限流）
                       logger.py （日志）
```

| 层级     | 目录          | 职责                                              | 禁止                                |
| ------ | ----------- | ----------------------------------------------- | --------------------------------- |
| **入口** | `app.py`    | Flask 实例、蓝图注册、WSGI 服务器                          | 不得包含业务逻辑                          |
| **路由** | `routes/`   | HTTP 请求解析、参数校验、Session 管理、响应构造                  | 不得包含 SQL、事务、业务逻辑                  |
| **服务** | `services/` | 纯业务逻辑，Flask 无关，返回 `(success, data_or_error)` 元组 | 不得导入 Flask、不得直接操作 request/session |
| **核心** | `core/`     | 数据库连接、认证装饰器、中间件                                 | 不得包含业务逻辑，不得导入 services            |

### 目录结构

```
workspace/
├── app.py                    # Flask 入口 + WSGI 服务器
├── config.py                 # 全局配置
├── requirements.txt          # Python 依赖
├── core/                     # 基础设施层
│   ├── db/                   #   数据库连接与 schema
│   ├── auth.py               #   认证装饰器、密码哈希
│   ├── middleware.py         #   请求中间件（访问日志 + 公共文件 + 安全响应标头）
│   ├── csrf.py               #   CSRF 保护
│   ├── logger.py             #   日志基础
│   ├── server.py             #   WSGI 服务器与优雅关闭
│   ├── template_context.py   #   模板全局变量
│   ├── init.py               #   应用初始化
│   ├── startup_checks.py     #   启动服务器健康检查（数据库/文件/配置，自动修复）
├── services/                 # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/               #   数据库备份与恢复
│   ├── discussion/           #   讨论区（帖子/回复/分类）
│   ├── email/                #   异步邮件发送
│   ├── game_accounts/        #   游戏账号绑定与注册申请
│   ├── monitoring/           #   系统监控（CPU/内存/系统/性能追踪）
│   ├── music/                #   大喇叭音频（常量/查询/CRUD/上传/收藏）
│   ├── rcon/                 #   RCON 连接管理、玩家列表追踪、EasyAuth 指令
│   ├── updater/              #   自动更新（配置/核心逻辑）
│   ├── user/                 #   用户（认证/资料/管理）
│   ├── attachment_service.py #   附件上传/清理
│   ├── background_service.py #   背景图片业务（WebP 转换 + 响应式变体）
│   ├── captcha.py            #   图形验证码
│   ├── discussion_service.py #   兼容性重导出层（讨论区）
│   ├── easy_auth_db.py       #   EasyAuth 数据库直连验证
│   ├── easyauth_bind.py      #   游戏账号密码验证（/auth getPlayerInfo + bcrypt）
│   ├── ip.py                 #   IP 工具
│   ├── music_service.py      #   兼容性重导出层（大喇叭音频）
│   ├── process_utils.py      #   子进程工具（编码/缓冲/环境变量）
│   ├── ratelimit.py          #   IP 频率限制
│   ├── settings_manager.py   #   系统设置管理
│   ├── sitemap_cache.py      #   Sitemap 缓存
│   ├── updater.py            #   兼容性重导出层（自动更新）
│   ├── user_service.py       #   兼容性重导出层（用户）
│   └── validation.py         #   输入验证统一模块
├── routes/                   # HTTP 路由层
│   ├── main/                 #   首页、登录、注册、设置、音乐
│   ├── admin/                #   管理后台（用户/备份/设置/日志/更新/游戏账号/指南/音乐/讨论/广播/背景等）
│   ├── api/                  #   JSON API（性能/统计/验证码/邮箱）
│   ├── backgrounds/          #   背景图片页面
│   ├── community/            #   社区留言板
│   ├── discussion/           #   讨论区（页面+API）
│   ├── docs/                 #   文档页面
│   ├── game_accounts/        #   游戏账号绑定与注册
│   ├── guides/               #   服务器指南（页面+API）
│   ├── public/               #   公开文件服务
│   ├── registry.py           #   蓝图注册中心
│   └── sitemap.py            #   站点地图
├── static/                   # 静态资源（CSS/JS）
│   ├── css/                  #   样式（tailwind/base）
│   ├── js/                   #   脚本（core/通用, pages/页面）
│   └── lib/                  #   本地化第三方库（构建生成）
├── templates/                # Jinja2 模板
│   ├── admin/                #   管理后台页面
│   ├── backgrounds/          #   背景图片页面
│   ├── discussion/           #   讨论区页面
│   ├── emails/               #   邮件模板
│   ├── game_accounts/        #   游戏账号页面
│   ├── guides/               #   服务器指南页面
│   ├── macros/               #   通用模板宏（模态框/编辑器/进度条/音乐）
│   ├── music/                #   大喇叭音频页面
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
| 数据库备份调度器 | 后台线程每日定时执行                         |
| IP 地理信息 | 后台线程异步更新缓存                         |
| CPU 监控  | 后台线程定期采样（2 秒）                      |

### 数据库

使用 **SQLite**（嵌入式单文件数据库），启用 **WAL 模式**（`PRAGMA journal_mode=WAL`）+ `synchronous=NORMAL` + `busy_timeout=30000`，读写并发性能优秀且崩溃可恢复；单例共享连接 + 可重入锁保证多线程安全。首次启动自动建表，共 17 张表：

| 表名                        | 说明       | 关键约束                                                                                                            |
| ------------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `users`                   | 用户       | `username` 唯一, `email` 唯一                                                                                       |
| `mod_intros`              | 模组介绍     | —                                                                                                               |
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
| `backgrounds`             | 背景图片     | `status` 审核状态，WebP 格式，响应式变体                                                                                    |
| `game_account_bindings`   | 游戏账号绑定   | 一个网站用户只能绑定一个 MC 账号（`user_id`/`mc_username` 唯一）                                                                  |
| `game_account_registrations` | 游戏账号注册申请 | 申请注册 MC 账号，管理员审批                                                                                               |
| `game_account_bans`       | 游戏账号封禁   | 封禁 MC 账号申请资格                                                                                                    |

> 旧版 DuckDB 数据库（`site.duckdb`）可通过 `scripts/migrate_db.py` 一键迁移到 SQLite（迁移前会自动备份旧库）。

#### 数据库备份

每日凌晨 3:00（可配置）自动执行：

1. 清理 WAL（CHECKPOINT）→ SQLite 在线备份 API（`Connection.backup()`）→ 校验备份文件 → 清理旧备份

管理后台支持手动触发，显示实时进度条；恢复前自动备份当前数据库。

### 一键更新机制

用户通过管理后台的「一键更新」功能，从 GitHub 获取最新代码：

1. 系统自动检测最快代理，下载 GitHub 仓库的 ZIP 压缩包
2. 解压后同步到本地（跳过受保护文件：数据库、配置、上传文件等）
3. 同步前自动**暂存本地独有文件**（仓库中不存在、如 `scripts/ffmpeg/` 下未入库的二进制），复制完成后自动恢复，避免更新误删本地资产
4. 不替换列表支持**子目录路径**（如 `scripts/ffmpeg`）：命中后该子目录在更新时不会被删除、覆盖或新增文件，完全保持本地现状；其余内容正常跟随仓库
5. 自动运行 `scripts/build/build_static.py` 构建静态资源
6. 写入独立跨平台重启脚本，确保旧进程完全退出后启动新进程（解决 Windows 环境下进程管理问题）
7. **服务器重启后自动运行健康检查**：数据库完整性检查、文件结构检查、配置完整性检查、uploads 目录结构检查，自动修复不删除文件

> 实现详见 `services/updater/core.py`（通过 SSE 推送实时下载进度到前端）。每次启动的健康检查由 `core/startup_checks.py` 负责。

### 安全要点

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 图形验证码服务端内存存储，一次性删除防重放
5. Session Cookie 启用 `HttpOnly` + `SameSite=Lax`（HTTPS 下自动加 `Secure`）
6. 邮箱唯一性检查（一个邮箱仅可注册一个账号）
7. IP 频率限制（注册/登录）
8. **全站安全响应标头**（`core/middleware.py` 集中下发，覆盖 HTML/API/SSE/静态资源）：

   * `Content-Security-Policy`：仅允许本站脚本/样式/资源，禁用 `object`，限制 `form-action`/`frame-ancestors` 等（已放行内联脚本/样式与 HLS blob worker，避免误伤自身功能）

   * `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`（防点击劫持）

   * `Referrer-Policy: strict-origin-when-cross-origin`（防 Referer 泄露）

   * `Permissions-Policy`：默认禁用摄像头/麦克风/定位/传感器等，仅放行本域剪贴板写入

   * `Cross-Origin-Opener-Policy: same-origin`（跨源隔离，防 Spectre 类窗口攻击）

   * `Strict-Transport-Security`（HSTS）：**仅 HTTPS 请求下发**，避免 HTTP 部署被强制升级而无法访问

## 开发注意事项

编写新代码前必查的**分层规范、易错点清单与测试要求**，详见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 更新日志

详见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 最近更新

* **同步 GitHub 代码 + 上传**：本地改动已与 GitHub 仓库同步并提交。

* **清理无用代码**：删除顶层残留的 `static/js/base.js`、`static/js/main.js`（模板实际引用 `js/core/base.js` 与 `js/pages/main.js`），删除空的 `static/js/script/` 目录；`static/lib/lib-version.json` 移除已废弃的 `xterm_version` 字段；打包/忽略规则更新为 SQLite 的 `*.db-wal`/`*.db-shm`，移除 DuckDB 残留

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

- **启动健康检查取代更新脚本**：移除更新脚本功能，新增 `core/startup_checks.py`，每次启动固定运行服务器健康检查——数据库完整性、文件结构、配置完整性、uploads 目录结构检查，自动尝试修复且不删除任何文件。`core/init.py` 集成该检查，在数据库初始化前执行。

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

