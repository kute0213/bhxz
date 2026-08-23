# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票与征集、模组介绍、管理后台、服务器性能监控、终端控制台等功能。

## 文档索引

| 文档 | 说明 |
|------|------|
| 本文档 | 项目总览、快速开始、功能特性、配置、API、架构、终端控制台使用说明 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发准则：分层规范、易错点、测试、路由检测、构建打包与发布、文档写入准则 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 更新日志 |

## 快速开始

### 环境要求

- Python 3.8+
- pip

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
- **Lucide Icons** — 图标库
- **Marked.js** — Markdown 渲染
- **JetBrains Mono** — 编程字体

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

| 用户名 | 密码 |
|--------|------|
| `admin` | `admin1324` |

> 登录后请立即修改默认密码。

## 项目结构

```
/workspace
├── app.py / config.py / requirements.txt   # 入口、配置、依赖
├── core/         # 基础设施层（DB/认证/中间件）
├── services/     # 业务逻辑层（纯 Python，不依赖 Flask）
├── routes/       # HTTP 路由层（Flask Blueprint）
├── templates/    # Jinja2 模板
├── static/       # 静态资源（CSS/JS/本地化第三方库）
├── docs/         # 项目文档
├── scripts/      # 构建（build/）与测试（tests/）
├── uploads/      # 运行期上传数据
│   ├── attachments/    # 留言板/讨论区附件
│   ├── backgrounds/    # 全站背景图片（bg_16_9.jpg 等）
│   ├── community/      # 社区资源
│   └── music/          # 大喇叭音频（每个音频一个 ID 目录，含 m3u8 与 ts 分片）
├── backups/      # 数据库备份
└── ssl/          # HTTPS 证书（可选）
```

> 完整目录树与各层职责见下文 [架构](#架构)。

## 功能特性

### 用户系统
- 注册/登录（群内验证码 + 邮箱验证码 + 图形验证码三重验证）
- 找回密码（邮箱验证码 + 图形验证码双重验证）
- 账户设置（修改用户名/密码/邮箱/注销）
- 邮箱唯一性约束（一个邮箱仅可注册一个账号）

### 社区互动
- 投票（单选/多选，管理员创建/启停）
- 征集（主题+回复，支持多附件上传）

### 管理后台
- 用户管理、访问日志、模组介绍管理
- 服务器指南 CRUD + 审核工作流 + 编辑封禁
- 讨论区管理（帖子置顶/锁定/删除 + 分类管理）
- 大喇叭音频管理（公开申请审核、查看全部音频、一键下架）
- 脚本控制台（实时终端 + 快捷命令 + 定时任务）
- 系统设置（在线编辑，热重载，含背景图片开关）
- 数据库备份（手动/自动，进度条）
- 公开文件管理
- 广播邮件（Markdown 编辑器 + 实时预览，统一组件）
- 一键更新（从 GitHub 自动拉取 + 实时进度条 + 自动重启）

### 服务器指南
- 卡片式列表页，支持置顶与按标题自动排序
- Markdown 详情页（标题锚点、代码一键复制）
- 成员提交需审核，管理员直接发布
- 封禁机制（用户名/IP，限时或永久）

### 讨论区
- 分类筛选、置顶优先、分页加载
- 回复实时刷新（默认 5 秒）
- Markdown 编辑 + 附件上传

### 大喇叭音频
- 「大喇叭音频」板块：上传音频自动转码为 HLS（m3u8），生成 `http://<主机>/music/<编号>.m3u8` 播放链接
- 支持 mp3 / wav / ogg / m4a / flac，单文件不超过 100MB（依赖 ffmpeg）
- 自动调用内置 ffmpeg：Windows 用 `scripts/ffmpeg/ffmpeg.exe`，Linux/macOS 用 `scripts/ffmpeg/ffmpeg`，未内置时回退系统 PATH 中的 `ffmpeg`
- **公开需审核**：申请公开的音频进入「待审核」，管理员通过后才在游戏内大喇叭展示；驳回后用户可转为私有或删除；已公开转私有再申请公开需重新审核
- **审核结果邮件通知**：管理员通过/驳回公开申请后，自动向上传者邮箱发送磨砂玻璃风格的审核结果邮件（通过 / 未通过状态卡），邮件未启用或上传者无邮箱时自动跳过
- **公开音频名称搜索**：公开音频列表支持按名称模糊搜索（`/music?q=关键词`），无结果时给出空态提示
- 音频状态：私有 / 待审核 / 已公开 / 已驳回，用户可在独立的「我的音频」页（`/music/my`）中查看并管理（播放链接、申请公开/转为私有、删除）
- 管理员可在后台审核公开申请、查看全部音频并一键下架（删除数据库记录并同步删除音频文件）
- 音频文件存放在 `uploads/music/<音频ID>/`，删除记录时自动清理对应目录，无文件残留
- **ffmpeg 多线程转码**：上传转码统一加 `-threads` 参数（`FFMPEG_THREADS`），每个上传任务是独立 ffmpeg 子进程与独立输出目录，多用户同时上传天然并行，不会出现「文件正在使用」冲突

### 终端控制台与快捷命令
- 实时终端（持久 shell 会话，SSE 流式输出）
- 快捷命令管理（数据库存储，按名称排序）
- 定时任务（支持间隔/每日/一次性模式）

### 服务器性能监控
- CPU 使用率/温度、内存占用、运行时间
- 公开页面，无需登录即可查看

### 文档系统
- Markdown 文档渲染（marked.js）
- 代码块一键复制按钮
- 侧边栏导航

## 配置说明

### 管理后台在线编辑（推荐）

所有运行时配置均可在 **管理后台 → 系统设置** 中在线编辑，修改后立即生效（热重载），无需重启服务器。

支持编辑的配置分类：
- **日志清理**：访问日志、命令日志、任务日志上限及清理间隔
- **定时任务**：调度间隔、执行超时、线程池大小
- **数据库备份**：自动备份时间、保留份数、超时
- **Sitemap**：刷新时间、站点域名、多域名列表
- **脚本执行**：并发数
- **安全配置**：会话有效期、登录失败锁定次数及时间
- **讨论区配置**：回复实时刷新间隔、每页加载数量
- **外部链接**：卫星地图地址、QQ 群链接
- **服务器配置**：监听地址、端口、调试模式、工作线程数

### config.py

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DB_PATH` | 数据库文件路径 | `./site.duckdb` |
| `UPLOAD_DIR` | 上传文件目录 | `./uploads` |
| `UPLOAD_MUSIC_DIR` | 大喇叭音频存放目录 | `./uploads/music` |
| `MUSIC_ALLOWED_EXTENSIONS` | 大喇叭音频允许上传的格式 | `mp3/wav/ogg/m4a/flac` |
| `FFMPEG_BIN` | 大喇叭音频转码用的 ffmpeg | 优先 `scripts/ffmpeg/ffmpeg(.exe)`，否则系统 PATH |
| `FFMPEG_THREADS` | ffmpeg 音频转码线程数 | `0`（自动按 CPU 核数） |
| `MAX_CONTENT_LENGTH` | 最大上传大小 | 100 MB |
| `SECRET_KEY` | Session 密钥 | `mc_server_site_random_secret_key_2024` |
| `REGISTER_VERIFY_CODE` | 注册验证码 | `binhai_xz` |
| `MAX_ACCESS_LOGS` | 访问日志最大保留条数 | `500` |
| `MAX_CMD_LOGS` | 脚本命令日志最大保留条数 | `1000` |
| `MAX_TASK_LOGS` | 任务日志最大保留条数 | `2000` |
| `BACKUP_SCHEDULED_TIME` | 每日自动备份时间 | `03:00` |
| `MAX_BACKUPS` | 最大保留备份份数 | `30` |
| `TASK_EXECUTION_TIMEOUT` | 定时任务默认执行超时（秒） | `300` |
| `TASK_SCHEDULER_INTERVAL` | 定时任务调度间隔（秒） | `1` |
| `SCRIPT_EXECUTOR_POOL_SIZE` | 脚本子进程并发数上限 | `2` |
| `DISCUSSION_REFRESH_INTERVAL` | 讨论区回复刷新间隔 | `5s` |
| `REPLIES_PER_PAGE` | 讨论区回复每页数量 | `10` |
| `MAP_URL` | 卫星地图地址 | `https://map.bhxz.tw.kg` |
| `QQ_GROUP_URL` | QQ 群链接 | 空 |

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
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

| 端点 | 说明 |
|------|------|
| `GET /api/performance` | 服务器性能数据（CPU/内存/运行时间） |
| `GET /api/stats` | 网站统计数据 |
| `GET /api/polls` | 投票数据（含选项/百分比/用户投票状态） |
| `GET /api/captcha/generate` | 生成图形验证码 |
| `POST /api/captcha/verify` | 验证图形验证码 |
| `POST /api/email/send-code` | 发送邮箱验证码 |
| `GET /api/email/check-enabled` | 检查邮件功能是否启用 |

### 社区 AJAX 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/poll/create` | 创建投票（管理员） |
| POST | `/poll/<id>/vote` | 投票 |
| POST | `/poll/<id>/delete` | 删除投票（管理员） |
| POST | `/poll/<id>/toggle` | 启用/禁用投票（管理员） |
| POST | `/board/create` | 创建征集（管理员） |
| POST | `/board/<id>/reply` | 回复征集（支持多附件） |
| POST | `/board/<id>/delete` | 删除征集（管理员） |
| POST | `/board/reply/<id>/delete` | 删除回复 |
| POST | `/discussion/<id>/reply` | 回复帖子 |
| POST | `/discussion/reply/<id>/delete` | 删除回复 |
| GET | `/discussion/<id>/api/replies` | 分页获取回复 |
| GET | `/discussion/<id>/api/new-replies` | 获取最新回复（实时刷新） |
| POST | `/discussion/<id>/pin` | 置顶/取消置顶（管理员） |
| POST | `/discussion/<id>/lock` | 锁定/解锁（管理员） |
| POST | `/discussion/<id>/delete` | 删除帖子 |

### 终端控制台 API（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/script/commands` | 获取快捷命令列表 |
| POST | `/admin/script/commands` | 新增快捷命令 |
| POST | `/admin/script/run` | 同步执行命令 |
| GET/POST | `/admin/script/run-stream` | SSE 流式执行 |
| POST | `/admin/script/run-preset/<id>` | 执行快捷命令 |
| POST | `/admin/script/commands/<id>/delete` | 删除快捷命令 |
| GET | `/admin/script/terminal/stream` | 交互式终端 SSE 流 |
| POST | `/admin/script/terminal/input` | 向终端发送输入 |
| POST | `/admin/script/terminal/reset` | 重置终端会话 |
| POST | `/admin/script/terminal/resize` | 调整终端窗口尺寸 |

## 前端特性

### 磨砂玻璃效果（Glassmorphism）

- **真实酸蚀刻玻璃质感**：`background: linear-gradient()` 渐变背景替代纯色，模拟光线透过玻璃的漫射效果
- `backdrop-filter: blur(48px) saturate(100%)` — 降低饱和度，更自然通透
- 超低透明度 `rgba(0.10)` 背景 + 光线散射伪元素（`radial-gradient` 模拟漫射光）
- 边缘光晕伪元素（`mask-composite` 渐变边框，模拟玻璃切割面折射）
- 动态背景光球（CSS `@keyframes` 动画），降低透明度使光晕更柔和
- 全局细微噪点纹理（SVG `feTurbulence`），模拟蚀刻玻璃表面微观散射
- **滚动收缩导航栏**：向下滚动后导航栏收缩为居中漂浮的椭圆胶囊，磨砂质感更凝实，弹性缓出动画（`prefers-reduced-motion` 可降级）
- **邮件模板同款磨砂玻璃**：`templates/emails/base.html` 统一暗绿金黄玻璃卡片（背景光晕 + 噪点纹理 + 光线散射层 + 顶部高光描边 + 状态卡），验证码 / 指南审核 / 音频审核 / 广播邮件共用同一外层与样式
- **模板宏复用**：`templates/macros/music_macros.html` 提取音频状态徽章、复制链接按钮、HLS 播放器为公共宏，`music/list.html` 与 `admin/admin_music.html` 统一调用，消除重复代码

### 交互效果

| 效果 | 实现方式 |
|------|----------|
| 鼠标光晕跟随 | `requestAnimationFrame` 平滑插值 |
| 按钮水波纹 | CSS `ripple` 动画 |
| 滚动淡入 | `IntersectionObserver` |
| 页面过渡 | `requestAnimationFrame` 控制 `.page-ready` 类切换 |
| 自定义弹窗 | 放大居中动画，触发元素位置感知 |
| Toast 提示 | 四种类型（success/error/warning/info） |

### 性能优化

- **零外部依赖**：所有 CDN 资源（Lucide、Marked.js）下载到本地，无外部网络请求
- **系统字体栈**：中文字体使用各平台预装字体（PingFang SC / Noto Sans CJK），零下载、零延迟
- `overflow-x: clip` 替代 `hidden`（消除滚动回弹）
- 尊重 `prefers-reduced-motion`（无障碍用户自动禁用动画）
- 触控设备降级光晕效果
- `IntersectionObserver` 触发后立即 `unobserve`

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

- 内置 Cheroot WSGI 服务器，`python app.py` 即可独立运行
- 生产环境推荐前置 Nginx 反向代理，且必须关闭缓冲以支持 SSE 长连接
- 构建、打包与发布流程见 [DEVELOPMENT.md 构建与发布](docs/DEVELOPMENT.md)
- 一键更新机制原理见下文 [一键更新机制](#一键更新机制)

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
         main/        process_utils.py
         docs/        process_manager.py
         public/      shell.py
         admin/       user_service.py
         api/         attachment_service.py
         cmd/         board_service.py
         community/   discussion_service.py
         discussion/  poll_service.py
         guides/      captcha.py （验证码）
         scheduled/   ratelimit.py （限流）
                      logger.py （日志）
```

| 层级 | 目录 | 职责 | 禁止 |
|------|------|------|------|
| **入口** | `app.py` | Flask 实例、蓝图注册、WSGI 服务器 | 不得包含业务逻辑 |
| **路由** | `routes/` | HTTP 请求解析、参数校验、Session 管理、响应构造 | 不得包含 SQL、事务、业务逻辑 |
| **服务** | `services/` | 纯业务逻辑，Flask 无关，返回 `(success, data_or_error)` 元组 | 不得导入 Flask、不得直接操作 request/session |
| **核心** | `core/` | 数据库连接、认证装饰器、中间件 | 不得包含业务逻辑，不得导入 services |

### 目录结构

```
workspace/
├── app.py                    # Flask 入口 + WSGI 服务器
├── config.py                 # 全局配置
├── requirements.txt          # Python 依赖
├── core/                     # 基础设施层
│   ├── db/                   #   数据库连接与 schema
│   ├── auth.py               #   认证装饰器、密码哈希
│   └── middleware.py         #   请求中间件
├── services/                 # 业务逻辑层
│   ├── user_service.py       #   用户注册/登录/改密
│   ├── attachment_service.py #   附件上传/清理
│   ├── board_service.py      #   征集主题 CRUD
│   ├── discussion_service.py #   讨论区帖子管理
│   ├── poll_service.py       #   投票业务
│   ├── music_service.py      #   大喇叭音频上传/转码/删除
│   ├── captcha.py            #   图形验证码
│   ├── ratelimit.py          #   IP 频率限制
│   ├── logger.py             #   操作日志
│   ├── process_manager.py    #   子进程生命周期管理
│   ├── process_utils.py      #   子进程工具（编码/缓冲/环境变量）
│   ├── shell.py              #   跨平台 shell 检测
│   ├── scheduler.py          #   定时任务调度器
│   ├── settings_manager.py   #   系统设置管理
│   ├── updater.py            #   自动更新
│   ├── cmd_runner.py         #   命令执行流
│   ├── email/                #   邮件服务
│   ├── backup/               #   数据库备份
│   ├── logging/              #   日志写入与清理
│   ├── monitoring/           #   系统监控
│   └── terminal/             #   持久终端会话
├── routes/                   # HTTP 路由层
│   ├── main/                 #   首页、登录、注册、设置
│   ├── docs/                 #   文档页面
│   ├── public/               #   公开文件服务
│   ├── admin/                #   管理后台
│   ├── api/                  #   JSON API
│   ├── script/               #   脚本控制台
│   ├── discussion/           #   讨论区
│   ├── guides/               #   服务器指南
│   └── scheduled/            #   定时任务管理
├── static/                   # 静态资源（CSS/JS）
│   ├── css/                  #   样式（tailwind/base）
│   ├── js/                   #   脚本（base/main/script）
│   └── lib/                  #   本地化第三方库（构建生成）
├── templates/                # Jinja2 模板
│   ├── macros/               #   通用模板宏（进度条等）
│   └── ...                   #   页面模板
├── docs/                     # 项目文档
└── scripts/
    ├── build/                #   构建脚本
    └── tests/                #   自动化测试
```

### 技术栈

| 类别 | 选型 |
|------|------|
| 后端框架 | Flask 3.x |
| WSGI 服务器 | Cheroot（内置） |
| 数据库 | DuckDB（嵌入式单文件） |
| 模板引擎 | Jinja2 |
| CSS | Tailwind CSS + 自定义样式（玻璃拟态） |
| 图标 | Lucide（本地化） |
| Markdown | marked.js / Python Markdown |
| 终端模拟 | xterm.js（本地化） |

### 异步架构

| 组件 | 异步方式 |
|------|----------|
| 定时任务调度器 | 后台线程 + ThreadPoolExecutor |
| 日志写入器 | 队列 + 后台线程批量写入 |
| 日志清理器 | 后台线程定期检查 |
| IP 地理信息 | 后台线程异步更新缓存 |
| CPU 监控 | 后台线程定期采样（2 秒） |
| 交互式终端 | session-based shell + 后台读取线程 + SSE |

### 数据库

使用 **DuckDB**（嵌入式 OLAP 数据库，单文件），首次启动自动建表。共 20 张表：

| 表名 | 说明 | 关键约束 |
|------|------|----------|
| `users` | 用户 | `username` 唯一, `email` 唯一 |
| `polls` | 投票 | — |
| `poll_options` | 投票选项 | 外键 `poll_id` 级联删除 |
| `poll_votes` | 投票记录 | 唯一约束 `(poll_id, user_id, option_id)` |
| `board_topics` | 征集主题 | 外键 `user_id` |
| `board_replies` | 征集回复 | 外键 `topic_id`，`attachment` 存 JSON |
| `mod_intros` | 模组介绍 | — |
| `cmd_commands` | 快捷命令 | 名称/命令/描述/排序 |
| `access_logs` | 访问日志 | 含 IP 地理信息，自动清理 |
| `scheduled_tasks` | 定时任务 | 支持间隔/每日/一次性 |
| `scheduled_task_logs` | 任务执行日志 | 外键 `task_id` |
| `cmd_run_logs` | 脚本命令执行日志 | — |
| `db_backups` | 备份记录 | 状态/大小/耗时 |
| `settings` | 系统设置 | key 唯一，支持热重载 |
| `server_guides` | 服务器指南 | 支持 Markdown，审核工作流 |
| `guide_edit_bans` | 编辑封禁 | 用户名/IP，限时/永久 |
| `discussion_categories` | 讨论分类 | slug 唯一 |
| `discussion_topics` | 讨论帖子 | 支持分类/标签/附件/置顶/锁定 |
| `discussion_replies` | 讨论回复 | 外键 `topic_id`，支持附件 |
| `music` | 大喇叭音频 | `status` 状态机（0=私有/1=待审核/2=已公开/3=已驳回），删除记录时同步删除 `uploads/music/<ID>/` 文件目录 |

#### 访问日志自动清理

超出 `MAX_ACCESS_LOGS`（默认 500 条）阈值时，后台线程自动删除最旧记录。

#### 数据库备份

每日凌晨 3:00（可配置）自动执行：
1. 清理过期日志 → CHECKPOINT → DuckDB 在线备份 → 验证 → 清理旧备份

管理后台支持手动触发，显示实时进度条。

### 一键更新机制

用户通过管理后台的「一键更新」功能，从 GitHub 获取最新代码：

1. 系统自动检测最快代理，下载 GitHub 仓库的 ZIP 压缩包
2. 解压后同步到本地（跳过受保护文件：数据库、配置、上传文件等）
3. 同步前自动**暂存本地独有文件**（仓库中不存在、如 `scripts/ffmpeg/` 下未入库的二进制），复制完成后自动恢复，避免更新误删本地资产
4. 不替换列表支持**子目录路径**（如 `scripts/ffmpeg`）：命中后该子目录在更新时不会被删除、覆盖或新增文件，完全保持本地现状；其余内容正常跟随仓库
5. 自动运行 `scripts/build/build_static.py` 构建静态资源
6. 自动重启服务器

> 实现详见 `services/updater.py`（通过 SSE 推送实时下载进度到前端）。

### 安全要点

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 图形验证码服务端内存存储，一次性删除防重放
5. Session Cookie 启用 `HttpOnly` + `SameSite=Lax`
6. 邮箱唯一性检查（一个邮箱仅可注册一个账号）
7. IP 频率限制（注册/登录）

## 终端控制台使用说明

本文档介绍终端控制台的快捷命令、实时终端、定时任务功能。

### 页面布局

终端控制台页面分为两个区域：

- **快捷命令**：以卡片网格展示，点击"运行"直接执行——Shell 命令会打开**弹窗终端**（基于 xterm.js）并在其中自动执行，输出实时回流
- **实时终端**：独立全屏终端页面（`/admin/script/terminal-page`），基于 xterm.js 渲染，输入/输出/清屏/光标控制与本地终端完全一致

### 快捷命令

快捷命令以卡片网格展示，支持添加、编辑、删除、排序。点击「运行」按钮打开弹窗终端，命令发送到持久 Shell 会话（PTY）执行，输出通过 SSE 实时回流。

### 实时终端

终端基于 **xterm.js**（业界标准终端模拟器）渲染，使用真实伪终端（PTY）驱动 Shell 会话：

- 直接在终端中键入命令，`Enter` 执行
- 输入回显、行编辑、`Tab` 补全、历史命令由终端驱动原生响应
- 输出通过 **SSE** 实时逐行回流
- 支持 `Ctrl+L` 清屏、`Ctrl+C` 中断
- 自动自适应尺寸，浏览器窗口变化时自动调整

### 定时任务

支持三种调度模式：间隔执行、每日定时、一次性执行。任务类型为 Shell 命令，在后台线程中异步执行，不会阻塞 Web 请求。支持查看执行日志和实时状态反馈。

## 开发注意事项

编写新代码前必查的**分层规范、易错点清单与测试要求**，详见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 更新日志

详见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。