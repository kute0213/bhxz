# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票与征集、模组介绍、管理后台、服务器性能监控、CMD 控制台与 MiniScript 脚本引擎等功能。

## 文档索引

| 文档 | 说明 |
|------|------|
| 本文档 | 项目总览、快速开始、功能特性、配置、API、架构、CMD 控制台使用说明 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 开发准则：分层规范、易错点、测试、路由检测、构建打包与发布、文档写入准则 |
| [CHANGELOG.md](CHANGELOG.md) | 更新日志 |

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
- **Monaco Editor** — 代码编辑器（约 12MB，HTTP 下载，无需 npm）

> 所有中文字体使用系统字体栈（各平台预装），**零下载、零延迟**。
> 一键更新时会自动运行构建脚本，无需手动操作。

### 打包发布 zip

需要离线分发时，可打包为发布 zip（排除敏感文件、数据库、上传、备份、SSL、日志与 Monaco 大文件）：

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
└── uploads/ backups/db/ ssl/               # 运行期数据
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
- CMD 控制台（实时终端 + 快捷命令 + 脚本编辑器 + 定时任务）
- 系统设置（在线编辑，热重载）
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

### CMD 控制台与 MiniScript
- 实时终端（持久 shell 会话，SSE 流式输出）
- 快捷命令管理（数据库存储，按名称排序）
- 专业脚本编辑器（Monaco，语法高亮/补全/诊断）
- MiniScript 脚本引擎（Python 子集，独立子进程执行）
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
- **脚本执行**：默认超时、最大超时、最大循环次数、并发数
- **安全配置**：会话有效期、登录失败锁定次数及时间
- **讨论区配置**：回复实时刷新间隔、每页加载数量
- **外部链接**：卫星地图地址、QQ 群链接
- **服务器配置**：监听地址、端口、调试模式、工作线程数

### config.py

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DB_PATH` | 数据库文件路径 | `./site.duckdb` |
| `UPLOAD_DIR` | 上传文件目录 | `./uploads` |
| `MAX_CONTENT_LENGTH` | 最大上传大小 | 100 MB |
| `SECRET_KEY` | Session 密钥 | `mc_server_site_random_secret_key_2024` |
| `REGISTER_VERIFY_CODE` | 注册验证码 | `binhai_xz` |
| `MAX_ACCESS_LOGS` | 访问日志最大保留条数 | `500` |
| `MAX_CMD_LOGS` | CMD 日志最大保留条数 | `1000` |
| `MAX_TASK_LOGS` | 任务日志最大保留条数 | `2000` |
| `BACKUP_SCHEDULED_TIME` | 每日自动备份时间 | `03:00` |
| `MAX_BACKUPS` | 最大保留备份份数 | `30` |
| `SCRIPT_DEFAULT_TIMEOUT` | 脚本默认执行超时 | `30s` |
| `SCRIPT_MAX_TIMEOUT` | 脚本最大允许超时 | `300s` |
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

### CMD 控制台 API（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/cmd/commands` | 获取快捷命令列表 |
| POST | `/admin/cmd/commands` | 新增快捷命令 |
| POST | `/admin/cmd/run` | 同步执行命令 |
| GET/POST | `/admin/cmd/run-stream` | SSE 流式执行 |
| POST | `/admin/cmd/run-preset/<id>` | 执行快捷命令 |
| POST | `/admin/cmd/run-script` | MiniScript 执行（SSE 流式+交互） |
| POST | `/admin/cmd/abort-script` | 终止脚本执行 |
| POST | `/admin/cmd/script-response` | 回传交互响应 |
| GET/POST | `/admin/cmd/scripts` | 脚本 CRUD |
| GET | `/admin/cmd/terminal/stream` | 交互式终端 SSE 流 |
| POST | `/admin/cmd/terminal/input` | 向终端发送输入 |
| POST | `/admin/cmd/terminal/close` | 关闭终端会话 |

## 前端特性

### 磨砂玻璃效果（Glassmorphism）

- **真实酸蚀刻玻璃质感**：`background: linear-gradient()` 渐变背景替代纯色，模拟光线透过玻璃的漫射效果
- `backdrop-filter: blur(48px) saturate(100%)` — 降低饱和度，更自然通透
- 超低透明度 `rgba(0.10)` 背景 + 光线散射伪元素（`radial-gradient` 模拟漫射光）
- 边缘光晕伪元素（`mask-composite` 渐变边框，模拟玻璃切割面折射）
- 动态背景光球（CSS `@keyframes` 动画），降低透明度使光晕更柔和
- 全局细微噪点纹理（SVG `feTurbulence`），模拟蚀刻玻璃表面微观散射
- **滚动收缩导航栏**：向下滚动后导航栏收缩为居中漂浮的椭圆胶囊，磨砂质感更凝实，弹性缓出动画（`prefers-reduced-motion` 可降级）

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

- **零外部依赖**：所有 CDN 资源（Lucide、Marked.js、Monaco Editor）下载到本地，无外部网络请求
- **系统字体栈**：中文字体使用各平台预装字体（PingFang SC / Microsoft YaHei / Noto Sans CJK），零下载、零延迟
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

部署方式、构建静态资源、打包发布详见 [DEVELOPMENT.md](DEVELOPMENT.md)。

- 内置 Cheroot WSGI 服务器，`python app.py` 即可独立运行
- 生产环境推荐前置 Nginx 反向代理，且必须关闭缓冲以支持 SSE 长连接
- 构建、打包与发布流程见 [DEVELOPMENT.md 构建与发布](DEVELOPMENT.md)
- 一键更新机制原理见下文 [一键更新机制](#一键更新机制)

## 架构

> 本文档描述项目的**架构分层、目录结构与技术栈**。代码编写与部署发布规范见 [DEVELOPMENT.md](DEVELOPMENT.md)。

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
│   ├── script_store.py       #   MiniScript 脚本存储
│   ├── email/                #   邮件服务
│   ├── backup/               #   数据库备份
│   ├── logging/              #   日志写入与清理
│   ├── miniscript/           #   MiniScript 脚本引擎
│   ├── monitoring/           #   系统监控
│   └── terminal/             #   持久终端会话
├── routes/                   # HTTP 路由层
│   ├── main/                 #   首页、登录、注册、设置
│   ├── docs/                 #   文档页面
│   ├── public/               #   公开文件服务
│   ├── admin/                #   管理后台
│   ├── api/                  #   JSON API
│   ├── cmd/                  #   命令控制台
│   ├── community/            #   社区（投票、留言板）
│   ├── discussion/           #   讨论区
│   ├── guides/               #   服务器指南
│   └── scheduled/            #   定时任务管理
├── static/                   # 静态资源（CSS/JS）
│   ├── css/                  #   样式（tailwind/style/base）
│   ├── js/                   #   脚本（base/main/cmd）
│   └── lib/                  #   本地化第三方库（构建生成）
├── templates/                # Jinja2 模板
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
| 代码编辑器 | Monaco Editor（本地化，按需构建） |
| 脚本引擎 | MiniScript（Python 子集，独立子进程执行） |

### 异步架构

| 组件 | 异步方式 |
|------|----------|
| 定时任务调度器 | 后台线程 + ThreadPoolExecutor |
| 日志写入器 | 队列 + 后台线程批量写入 |
| 日志清理器 | 后台线程定期检查 |
| IP 地理信息 | 后台线程异步更新缓存 |
| CPU 监控 | 后台线程定期采样（2 秒） |
| 交互式终端 | session-based shell + 后台读取线程 + SSE |
| MiniScript | 独立子进程 + SSE 流式回流 |

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
| `cmd_commands` | 快捷命令 | 名称/命令/描述/排序/类型 |
| `scripts` | 统一脚本 | name/description/content/script_type |
| `access_logs` | 访问日志 | 含 IP 地理信息，自动清理 |
| `scheduled_tasks` | 定时任务 | 支持间隔/每日/一次性 |
| `scheduled_task_logs` | 任务执行日志 | 外键 `task_id` |
| `cmd_run_logs` | CMD 执行日志 | — |
| `db_backups` | 备份记录 | 状态/大小/耗时 |
| `settings` | 系统设置 | key 唯一，支持热重载 |
| `server_guides` | 服务器指南 | 支持 Markdown，审核工作流 |
| `guide_edit_bans` | 编辑封禁 | 用户名/IP，限时/永久 |
| `discussion_categories` | 讨论分类 | slug 唯一 |
| `discussion_topics` | 讨论帖子 | 支持分类/标签/附件/置顶/锁定 |
| `discussion_replies` | 讨论回复 | 外键 `topic_id`，支持附件 |

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
3. 自动运行 `scripts/build/build_static.py` 构建静态资源
4. 自动重启服务器

> 实现详见 `services/updater.py`（通过 SSE 推送实时下载进度到前端）。

### 安全要点

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 图形验证码服务端内存存储，一次性删除防重放
5. Session Cookie 启用 `HttpOnly` + `SameSite=Lax`
6. 邮箱唯一性检查（一个邮箱仅可注册一个账号）
7. IP 频率限制（注册/登录）

## CMD 控制台使用说明

本文档详细介绍 CMD 控制台的快捷命令、实时终端、MiniScript 脚本语言、专业脚本编辑器的使用方法。

MiniScript 是一种 **Python 子集脚本语言**，脚本在独立 Python 子进程中执行，通过 SSE 流式回流输出，不影响 Flask 主服务。语法为完整 Python 子集，内置函数兼容旧函数名并新增文件/数据库函数。

### 目录

1. [页面布局](#1-页面布局)
2. [快捷命令](#2-快捷命令)
3. [实时终端](#3-实时终端)
4. [MiniScript 脚本语言](#4-miniscript-脚本语言)
5. [内置函数参考](#5-内置函数参考)
6. [安全限制](#6-安全限制)
7. [执行模式](#7-执行模式)
8. [强制终止](#8-强制终止)
9. [实用脚本示例](#9-实用脚本示例)
10. [常见问题](#10-常见问题)
11. [脚本编辑器](#11-脚本编辑器)
12. [错误信息与行号](#12-错误信息与行号)
13. [定时任务](#13-定时任务)
14. [日志自动清除](#14-日志自动清除)

---

### 1. 页面布局

CMD 控制台页面分为两个区域：

```
┌─────────────────────────────────────────────────────┐
│  顶部操作栏：[实时终端] [添加快捷命令] [脚本编辑器]      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  快捷命令区域（卡片网格）                               │
│  ┌──────┐ ┌──────┐ ┌──────┐                        │
│  │命令1  │ │命令2  │ │命令3  │                        │
│  └──────┘ └──────┘ └──────┘                        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- **实时终端**：点击按钮以弹窗形式打开，支持实时流式输出
- **快捷命令**：以卡片网格展示，点击"运行"直接执行
- **脚本编辑器**：进入专业脚本编辑器页面，提供语法高亮、代码补全、错误诊断等功能

> **提示**：MiniScript 脚本通过"快捷命令"功能管理，也可在「脚本编辑器」中编写并保存。脚本统一在后端独立子进程中执行，通过 SSE 流式回流输出。

---

### 2. 快捷命令

#### 2.1 添加快捷命令

1. 点击页面顶部的「添加快捷命令」按钮
2. 在弹窗中填写以下信息：
   - **名称**：命令的显示名称（必填）
   - **类型**：选择 `CMD 命令` 或 `MiniScript 脚本`
   - **内容**：CMD 命令或脚本代码（必填）
   - **描述**：简短说明（可选）
   - **排序**：数字越小越靠前（可选）
3. 点击「保存」

#### 2.2 编辑快捷命令

点击命令卡片右上角的编辑图标（铅笔），修改后保存。

#### 2.3 删除快捷命令

点击命令卡片右上角的删除图标（垃圾桶），确认后删除。

#### 2.4 运行快捷命令

点击命令卡片底部的「运行」按钮：

- **CMD 命令类型**：自动打开终端弹窗，流式显示输出
- **脚本类型**：通过后端 SSE API 在独立子进程中执行，输出回流到终端弹窗

#### 2.5 命令类型说明

| 类型 | 标签颜色 | 执行位置 | 说明 |
|------|----------|----------|------|
| CMD 命令 | 绿色 | 服务端 | 原始 Shell 命令，通过 SSE 流式返回输出 |
| MiniScript 脚本 | 紫色 | 服务端子进程 | Python 子集，在独立子进程中执行，通过 SSE 回流事件 |

---

### 3. 实时终端

#### 3.1 打开终端

点击页面顶部的「实时终端」按钮，以弹窗形式打开终端。

#### 3.2 执行命令

在底部输入框中输入命令，按 `Enter` 或点击发送按钮执行。命令通过 **SSE（Server-Sent Events）** 流式返回输出，实时逐行显示。

#### 3.3 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 执行命令 |
| `↑` | 上一条历史命令 |
| `↓` | 下一条历史命令 |
| `Ctrl + L` | 清屏 |

#### 3.4 清屏

点击输入框右侧的垃圾桶图标清除终端内容。

#### 3.5 关闭终端

点击终端弹窗右上角的关闭按钮，或点击弹窗外部区域。

---

### 4. MiniScript 脚本语言

MiniScript 是一种 **Python 子集脚本语言**，由后端执行引擎在独立 Python 子进程中执行，通过 SSE 流式回流输出，不影响 Flask 主服务。前端编辑器（Monaco）仅负责代码编辑与高亮，不再解释执行。

**语法与 Python 一致**：支持完整 Python 语法（控制流、函数、类、异常处理、`import` 标准库、列表/字典、推导式、f-string、装饰器等），可直接使用 Python 原生类型（`True`/`False`/`None`）与原生列表方法（`append`/`pop`/切片/推导式）。具体语法请直接参考 Python 文档，本文不再赘述。

执行前通过 AST 沙箱校验，禁止危险调用（详见 [第 6 节：安全限制](#6-安全限制)）。

---

### 5. 内置函数参考

MiniScript 在脚本全局命名空间注入以下内置函数。除此之外，Python 原生的 `len` / `range` / `str` / `int` / `float` / `list` / `dict` / `sorted` / `re` 等均可直接使用。

#### 5.1 基础 I/O

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `echo(*args)` | 任意多个参数 | 无 | 输出消息（拼接所有参数），通过 SSE 回流到前端 |
| `print(*args, sep=' ', end='\n')` | 任意参数 + 分隔符 + 结束符 | 无 | 标准 Python `print`，行为与 `echo` 一致回流到前端 |
| `sleep(seconds)` | 秒数（float） | 无 | 延时指定秒数，阻塞子进程 |
| `now()` | 无 | `float` | 返回当前时间戳（秒） |
| `set_timeout(seconds)` | 秒数（int） | 无 | 设定本次执行超时，上限 300 秒 |

**示例**：

```python
echo("当前时间：", now())
print("a", "b", "c", sep="-")    # a-b-c
sleep(1.5)
set_timeout(60)                  # 把本次执行超时调整为 60 秒
```

#### 5.2 Shell 命令执行

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `cmd(command)` | 命令字符串 | 完整输出字符串 | 在子进程中执行 shell 命令，等待完成后返回合并的 stdout+stderr |

> 旧的 `cmd_sync()` 函数已被移除，统一使用 `cmd()`。`cmd()` 在后端独立子进程中执行，不再有流式与同步之分。

**示例**：

```python
output = cmd("df -h")
echo(output)
```

#### 5.3 文件操作

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `file_read(path)` | 文件路径 | 字符串 | 读取文件内容 |
| `file_write(path, content)` | 路径, 内容 | `True`/`False` | 覆盖写入文件，成功返回 `True` |
| `file_append(path, content)` | 路径, 内容 | `True`/`False` | 追加写入文件 |
| `file_list(dir)` | 目录路径 | 字符串列表 | 列出目录下的文件/子目录名 |
| `file_exists(path)` | 路径 | `True`/`False` | 判断文件或目录是否存在 |

**示例**：

```python
# 读取配置文件
if file_exists("/etc/hostname"):
    content = file_read("/etc/hostname")
    echo(f"主机名: {content.strip()}")

# 写入日志
file_append("/tmp/script.log", f"[{now()}] 任务执行完成\n")

# 列出目录
for name in file_list("/var/log"):
    echo(name)
```

#### 5.4 数据库访问

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `db_query(sql, params=None)` | SQL 字符串, 参数元组/列表（可选） | 字典列表 | 执行 SELECT 查询，每行作为一个 dict |
| `db_execute(sql, params=None)` | SQL 字符串, 参数（可选） | 整数（影响行数） | 执行 INSERT/UPDATE/DELETE，返回受影响行数 |

> 数据库连接复用 Flask 主服务的 DuckDB 数据库（`site.duckdb`），可直接读写网站数据。请谨慎执行写操作。

**示例**：

```python
# 查询所有用户
rows = db_query("SELECT id, username FROM users ORDER BY id")
for row in rows:
    echo(f"#{row['id']} {row['username']}")

# 带参数查询（防注入）
user = db_query(
    "SELECT username FROM users WHERE id = ?",
    [1]
)
if user:
    echo(f"用户名: {user[0]['username']}")

# 插入数据
affected = db_execute(
    "INSERT INTO cmd_commands (name, command, type) VALUES (?, ?, ?)",
    ["测试命令", "echo hello", "shell"]
)
echo(f"插入 {affected} 行")
```

#### 5.5 交互函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `alert(title, message='')` | 标题, 内容（可选） | 无 | 弹窗提示 |
| `prompt(title, message='', default='')` | 标题, 提示语（可选）, 默认值（可选） | 字符串 | 弹窗获取用户输入 |
| `confirm(title, message='')` | 标题, 内容（可选） | `True`/`False` | 确认弹窗 |

**手动执行模式**：通过 SSE 与前端交互，弹出页面弹窗并等待用户响应。

**定时执行模式**：交互函数自动降级（详见 [第 7 节：执行模式](#7-执行模式)）：

| 函数 | 手动执行 | 定时执行（降级） |
|------|----------|------------------|
| `alert` | SSE 通知前端弹窗 | 静默跳过 |
| `prompt` | SSE 请求前端输入并等待响应 | 直接返回 `default` 值 |
| `confirm` | SSE 请求前端确认并等待响应 | 直接返回 `True` |

**示例**：

```python
name = prompt("用户信息", "请输入你的名字：", "匿名")
sure = confirm("危险操作", "确定要继续吗？")
if sure:
    alert("结果", f"你好, {name}!")
```

---

### 6. 安全限制

MiniScript 在执行前通过 **AST 沙箱校验**确保脚本不会危害系统安全。

#### 6.1 AST 白名单

仅允许安全的语法节点类型，**禁止**以下声明：

- `global` 声明
- `nonlocal` 声明

#### 6.2 函数黑名单

禁止直接调用以下 Python 内置函数：

| 函数 | 拒绝原因 |
|------|----------|
| `exec` / `eval` / `compile` | 可执行任意代码字符串 |
| `__import__` | 可动态导入危险模块 |
| `globals` / `locals` / `vars` | 可访问内部命名空间 |
| `dir` | 可枚举对象内部成员 |
| `getattr` / `setattr` / `delattr` / `hasattr` | 反射绕过沙箱 |
| `breakpoint` | 触发调试器 |
| `exit` / `quit` | 退出解释器 |

#### 6.3 属性保护

禁止访问**双下划线开头**的属性（如 `__class__`、`__subclasses__`、`__globals__` 等），防止通过反射链进行沙箱逃逸。

#### 6.4 运行时防护

- 从 `__builtins__` 中移除上述危险函数
- `print` 被重定向到管道，输出通过 SSE 回流到前端
- 子进程独立于 Flask 主服务，即使脚本异常崩溃也不影响 Web 请求

#### 6.5 校验示例

```python
# ❌ 会被拒绝（直接调用危险函数或访问危险属性）
exec("print('hi')")
eval("1 + 1")
__import__('subprocess')
obj.__class__.__bases__[0].__subclasses__()
global x
nonlocal y

# ✅ 允许（import 语句、推导式、函数定义等）
import math
import re
import os  # import 语句本身不被拦截（仅管理员可执行，子进程隔离）
def safe(x): return x * 2
result = [i for i in range(10) if i % 2 == 0]
```

> **安全边界说明**：AST 沙箱只拦截**显式危险模式**（直接调用 `exec`/`eval`/`__import__`、双下划线属性访问、`global`/`nonlocal`）。`import` 语句本身不被拦截，因此理论上可导入 `os`/`subprocess` 等模块。安全依赖以下三层保障：
> 1. **访问控制**：仅管理员可执行 MiniScript 脚本（`/admin/cmd/*` 路由需 admin 权限）
> 2. **进程隔离**：脚本运行在独立子进程中，崩溃或异常不影响 Flask 主服务
> 3. **超时与终止**：默认 30 秒超时，支持手动强制终止

---

### 7. 执行模式

MiniScript 支持两种执行模式，区别在于交互函数的行为。

#### 7.1 手动执行（交互模式）

由用户在 CMD 控制台或脚本编辑器点击「运行」触发，采用交互模式执行。

- **SSE 实时回流**：脚本输出（`echo`/`print`）和事件（`alert`/`prompt`/`confirm`/`error`/`done`）通过 Server-Sent Events 流式推送到前端
- **交互弹窗**：调用 `alert`/`prompt`/`confirm` 时，后端通过 SSE 推送对应事件到前端，前端弹出 `CmdModal` 弹窗
- **响应回传**：用户在弹窗中输入或确认后，前端将响应回传给后端，脚本继续执行
- **响应超时**：等待前端响应超过 60 秒时，`prompt` 返回 `None`、`confirm` 返回 `False`
- **互斥控制**：同时只允许一个脚本执行，并发请求返回 `409`

#### 7.2 定时执行（降级模式）

由定时任务调度器在后台触发，采用非交互模式执行。

- **无前端交互**：定时执行时没有前端连接，交互函数自动降级（见 [5.5 交互函数](#55-交互函数)）
- **输出记录**：`echo`/`print` 输出捕获到执行日志，写入 `scheduled_task_logs` 表的 `output` 字段
- **超时保护**：默认 30 秒，可配置上限 300 秒
- **执行流程**：调度器扫描到期任务 → 异步执行 → 启动子进程 → 输出与状态写入日志表

#### 7.3 SSE 事件类型

手动执行时，后端通过 SSE 推送以下事件，前端按类型处理：

| `type` | `data` 字段 | 是否需要前端响应 | 说明 |
|--------|-------------|------------------|------|
| `output` | `{text: "..."}` | 否 | 脚本标准输出 |
| `alert` | `{title, message}` | 否 | 请求前端弹窗 |
| `prompt` | `{title, message, default}` | **是** | 请求前端输入并等待 |
| `confirm` | `{title, message}` | **是** | 请求前端确认并等待 |
| `error` | `{message: "..."}` | 否 | 错误信息 |
| `done` | `{}` | 否 | 执行结束 |

---

### 8. 强制终止

MiniScript 支持随时强制终止正在执行的脚本，避免长时间运行或失控的脚本占用资源。

#### 8.1 终止按钮

脚本运行时：

- **脚本编辑器**：工具栏的「运行」按钮变为红色「强制终止」按钮
- **CMD 控制台终端**：终端标题栏显示红色「中止」按钮

点击按钮即可终止子进程（接口详情见项目 README）。

#### 8.2 自动终止场景

除手动终止外，以下场景会自动终止脚本：

| 场景 | 触发条件 | 行为 |
|------|----------|------|
| 超时 | 执行时间超过设定超时（默认 30 秒，上限 300 秒） | 看门狗线程终止子进程，推送 `error` 事件 |
| 交互超时 | `prompt`/`confirm` 等待响应超过 60 秒 | 返回默认值，脚本继续执行 |
| 循环上限 | `while`/`for` 迭代次数超过 100,000 | 抛出运行时错误 |
| 语法校验失败 | AST 沙箱检测到危险代码 | 不启动子进程，直接返回错误 |
| Flask 主进程退出 | 主进程结束 | 子进程作为守护进程被回收 |

#### 8.3 终止后行为

- 后端清理子进程资源（管道、看门狗线程）
- 推送 `done` 事件结束 SSE 流
- 前端按钮恢复为「运行」状态

---

### 9. 实用脚本示例

#### 9.1 获取用户名并弹窗显示

```python
name = prompt("用户信息", "请输入你的名字：", "匿名")
result = cmd("whoami").strip()
alert("结果", f"你好, {name}!\n当前系统用户: {result}")
```

#### 9.2 检查磁盘空间

```python
output = cmd("df -h")
echo(output)
```

#### 9.3 条件执行命令

```python
choice = prompt("操作", "查看什么？\n1. CPU\n2. 内存\n3. 磁盘", "1")
if choice == "1":
    echo(cmd("top -bn1 | head -5"))
elif choice == "2":
    echo(cmd("free -h"))
else:
    echo(cmd("df -h"))
```

#### 9.4 正则提取信息

```python
import re

output = cmd("ip addr show eth0")
m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
if m:
    echo(f"IP 地址: {m.group(1)}")
else:
    echo("未找到 IP 地址")
```

#### 9.5 批量执行命令

```python
echo("=== 系统信息 ===")
echo(cmd("uname -a"))
echo("")
echo("=== 磁盘 ===")
echo(cmd("df -h"))
echo("")
echo("=== 内存 ===")
echo(cmd("free -h"))
```

#### 9.6 用户确认后执行

```python
sure = confirm("危险操作", "确定要重启服务吗？")
if sure:
    output = cmd("systemctl restart myapp")
    alert("结果", output or "已重启")
else:
    echo("已取消")
```

#### 9.7 批量执行命令（for 循环）

```python
commands = ["whoami", "hostname", "date"]
for c in commands:
    echo(f"=== {c} ===")
    echo(cmd(c))
    echo("")
```

#### 9.8 倒计时

```python
for i in range(10, 0, -1):
    echo(f"{i} 秒后开始...")
    sleep(1)
echo("开始！")
```

#### 9.9 列表与循环

```python
nums = [10, 20, 30, 40, 50]
total = sum(nums)
echo(f"总和: {total}")                 # 150
echo(f"平均: {total / len(nums)}")     # 30.0
```

#### 9.10 推导式过滤与映射

```python
nums = list(range(1, 11))
evens = [n for n in nums if n % 2 == 0]
doubled = [n * 2 for n in nums]
print(evens)      # [2, 4, 6, 8, 10]
print(doubled)    # [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
```

#### 9.11 系统状态批量检查

```python
checks = [
    ("CPU", "top -bn1 | head -5"),
    ("内存", "free -h"),
    ("磁盘", "df -h"),
]
for label, command in checks:
    echo(f"=== {label} ===")
    echo(cmd(command))
    echo("")
```

#### 9.12 读写文件

```python
# 写入文件
file_write("/tmp/note.txt", "第一行\n")
file_append("/tmp/note.txt", "第二行\n")

# 读取并显示
if file_exists("/tmp/note.txt"):
    content = file_read("/tmp/note.txt")
    echo(content)
```

#### 9.13 数据库查询

```python
# 查询用户数
rows = db_query("SELECT COUNT(*) AS cnt FROM users")
echo(f"用户总数: {rows[0]['cnt']}")

# 查询最近 5 条访问日志
logs = db_query(
    "SELECT path, ip, created_at FROM access_logs ORDER BY id DESC LIMIT 5"
)
for log in logs:
    echo(f"[{log['created_at']}] {log['ip']} -> {log['path']}")
```

#### 9.14 异常处理

```python
try:
    data = file_read("/tmp/config.json")
    import json
    config = json.loads(data)
    echo(f"配置加载成功: {config}")
except FileNotFoundError:
    echo("配置文件不存在，使用默认配置")
except json.JSONDecodeError as e:
    echo(f"配置文件格式错误: {e}")
```

#### 9.15 自定义函数与类

```python
def format_size(bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} TB"

class SystemInfo:
    def __init__(self):
        self.hostname = cmd("hostname").strip()

    def show(self):
        echo(f"主机名: {self.hostname}")

info = SystemInfo()
info.show()
```

---

### 10. 常见问题

#### Q: 命令执行超时怎么办？

脚本默认超时 30 秒，最大可调整至 300 秒（通过 `set_timeout(seconds)` 或运行前设置）。超时后子进程自动终止。如果脚本需要更长时间，建议：

- 拆分为多个独立脚本
- 使用 `set_timeout(300)` 调到上限
- 改为定时任务模式执行

#### Q: 脚本报错"缩进错误"？

MiniScript 使用 Python 风格的缩进。请确保：

- 同一代码块内缩进一致
- 不要混用空格和 Tab
- 推荐使用 4 个空格缩进

#### Q: 旧的 `cmd_sync()` 和 `cmd()` 有什么区别？

> **新版本中 `cmd_sync()` 已被移除**，统一使用 `cmd()`。`cmd()` 在后端独立子进程中执行，等待命令完成后返回完整输出字符串。前端通过 SSE 流式接收脚本本身的输出（如 `echo`），而 shell 命令的输出由 `cmd()` 一次性返回。

#### Q: 旧的 `append`/`push`/`pop`/`slice` 等列表函数还能用吗？

不能。新版 MiniScript 直接使用 Python 原生列表方法：

| 旧函数（已移除） | 新写法（Python 原生） |
|------------------|----------------------|
| `append(a, x)` | `a.append(x)` |
| `push(a, x)` | `a.append(x)` |
| `pop(a)` | `a.pop()` |
| `pop(a, 0)` | `a.pop(0)` |
| `slice(a, 1, 3)` | `a[1:3]` |
| `join(arr, "-")` | `"-".join(arr)` |
| `reverse(a)` | `a[::-1]` 或 `a.reverse()` |
| `sort(a)` | `sorted(a)` 或 `a.sort()` |
| `contains(a, x)` | `x in a` |

#### Q: 旧的 `set_timeout("code", 3000)` 和 `set_interval` 还能用吗？

**`set_interval` 已被移除**。`set_timeout` 的语义已变更：

| 旧版本 | 新版本 |
|--------|--------|
| `set_timeout("echo('hi')", 3000)` — 3 秒后执行代码字符串 | `set_timeout(3)` — 设置本次执行的超时为 3 秒 |
| `set_interval("echo('hi')", 1000)` — 每秒重复执行 | （已移除）改用 `while True` + `sleep(1)` 循环 |
| `clear_timer(id)` — 取消定时器 | （已移除） |

定时执行请改用循环 + sleep：

```python
for i in range(10):
    echo(f"第 {i + 1} 秒")
    sleep(1)
```

#### Q: 脚本可以保存为快捷命令吗？

可以。添加快捷命令时，类型选择「MiniScript 脚本」，将脚本代码粘贴到内容区域即可。保存后可一键运行。

#### Q: 非管理员可以使用 CMD 控制台吗？

不可以。所有 `/admin/cmd/*` 路由均需要管理员权限，非管理员访问返回 403。

#### Q: 循环会无限运行吗？

不会。MiniScript 有多层保护机制：

1. **循环迭代上限**：`while` 和 `for` 循环最大 **100,000 次迭代**，超过会抛出错误
2. **脚本超时保护**：默认 30 秒，最大可调整至 300 秒，超时自动终止
3. **手动终止**：脚本运行时显示「强制终止」按钮，点击可立即停止（详见 [第 8 节](#8-强制终止)）
4. **进程隔离**：脚本运行在独立子进程中，即使异常崩溃也不影响 Flask 主服务

```
while 循环超过最大迭代次数 100000，可能存在无限循环
```

```
脚本执行超时（30秒），已被自动中止
```

#### Q: 如何停止正在运行的脚本？

脚本运行时，编辑器工具栏或终端标题栏会出现红色「强制终止」按钮。点击即可终止子进程（详见 [第 8 节](#8-强制终止)）。

其他停止方式：

- **关闭终端弹窗**：自动中止脚本
- **运行新脚本**：会因互斥控制返回 `409`，需先终止当前脚本
- **超时自动终止**：达到超时上限后自动终止

#### Q: 脚本可以访问数据库吗？

可以。通过 `db_query(sql, params=None)` 和 `db_execute(sql, params=None)` 可读写网站使用的 DuckDB 数据库。建议：

- 写操作前用 `confirm` 让用户确认
- 使用参数化查询防止 SQL 注入
- 谨慎执行 DROP / DELETE 等危险操作

#### Q: 脚本可以访问文件系统吗？

可以。`file_read` / `file_write` / `file_append` / `file_list` / `file_exists` 提供基本文件操作的便捷封装。由于脚本运行在独立子进程中且仅管理员可执行，`import os` 等模块导入不被拦截，管理员也可直接使用 Python 原生文件 API，但建议优先使用内置函数以获得统一的错误处理与日志记录。

#### Q: 列表和 Python 列表有什么区别？

**没有区别**。MiniScript 列表就是 Python 原生 list：

- ✅ 支持 `[1, 2, 3]` 字面量、`list[0]` 索引、`list[-1]` 负索引
- ✅ 支持切片 `list[1:3]`、`list[::-1]`
- ✅ 支持 `for...in` 遍历、`+` 拼接、`*` 重复
- ✅ 支持列表推导式 `[x for x in range(10)]`
- ✅ 支持原生方法 `list.append(x)` / `list.pop()` / `list.sort()` 等

---

### 11. 脚本编辑器

脚本编辑器是一个独立的、专业级的代码编写页面，基于 Monaco Editor（VS Code 的核心编辑器）实现。

#### 11.1 进入编辑器

- 在 CMD 控制台页面顶部点击紫色「脚本编辑器」按钮
- 或在快捷命令卡片上点击代码图标（紫色），可直接打开并编辑该命令

访问地址：`/admin/cmd/editor`（仅管理员）

#### 11.2 编辑器功能

| 功能 | 说明 |
|------|------|
| **语法高亮** | 使用 Monaco 内置 `python` 语言 + 自定义 `pythonDark` 深色主题（深绿金色风格） |
| **代码补全** | 输入时自动弹出 Python 关键字与后端内置函数列表，含函数签名和文档说明 |
| **悬浮提示** | 鼠标悬停在内置函数名上时显示函数签名和用法文档 |
| **行号标注** | 左侧行号栏，当前行高亮显示 |
| **代码折叠** | 支持折叠 `if` / `while` / `for` / `def` / `class` 代码块 |
| **括号匹配与着色** | 括号对自动配对着色 |
| **查找与批量替换** | `Ctrl+F` 查找、`Ctrl+H` 替换、`Ctrl+Shift+L` 选中所有匹配项（多光标批量编辑） |
| **多光标编辑** | `Alt+点击` 添加光标、`Ctrl+Alt+↑/↓` 上下添加光标 |
| **代码格式化** | 点击「格式化」按钮或 `Shift+Alt+F` |
| **Minimap** | 右侧缩略图导航 |
| **自动缩进** | 在 `:` 后回车自动增加缩进 |

> 语法诊断由后端执行时通过 SSE `error` 事件回传，前端不再做实时语法检查（Monaco 仅做基础的 Python 词法高亮）。

#### 11.3 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Enter` | 运行脚本（无需保存） |
| `Ctrl+S` | 保存为快捷命令 |
| `Ctrl+F` | 查找 |
| `Ctrl+H` | 替换 |
| `Ctrl+Shift+L` | 选中所有匹配项（批量替换） |
| `Shift+Alt+F` | 格式化代码 |
| `Ctrl+/` | 切换行注释 |
| `Alt+↑/↓` | 上下移动当前行 |
| `Shift+Alt+↑/↓` | 向上/向下复制当前行 |
| `Ctrl+D` | 选中下一个匹配项 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |

#### 11.4 测试运行

点击工具栏「运行」按钮或按 `Ctrl+Enter` 即可在右侧输出面板查看运行结果，**无需保存**。

- 运行时按钮变为红色「强制终止」，点击可随时终止脚本（详见 [第 8 节](#8-强制终止)）
- 错误会通过 SSE `error` 事件回传并显示在输出面板
- 脚本默认执行 30 秒，最大可调整至 300 秒，超时自动终止

#### 11.5 保存为快捷命令

点击「保存为命令」按钮或按 `Ctrl+S`：

1. 输入命令名称（必填）
2. 输入简短描述（可选）
3. 脚本会自动以 `[脚本]` 前缀标记描述，作为脚本类型保存到数据库
4. 保存后即可在 CMD 控制台的快捷命令卡片中找到并重复运行

如果是编辑现有命令（从卡片入口打开），保存会自动更新该命令而非新建。

#### 11.6 示例代码

点击工具栏「示例」按钮可选择加载内置示例：

- Hello World
- 循环与列表
- 条件判断
- 交互输入
- 执行 CMD
- 读取文件
- 数据库查询

加载示例会替换当前内容（会先确认）。

---

### 12. 错误信息与行号

MiniScript 的所有错误（语法错误和运行时错误）都包含**具体的出错行号**，便于快速定位问题。

#### 12.1 错误格式

错误信息统一通过 SSE `error` 事件回传，包含 Python 异常类型与 traceback 行号。

#### 12.2 语法错误（AST 校验阶段）

在脚本开始执行前由 `validate_script()` 抛出：

```
禁止使用 exec()
禁止使用 __import__()
禁止访问双下划线属性 __class__
禁止使用 global 声明
```

#### 12.3 Python 语法错误

由 Python 解析器在编译阶段抛出：

```
SyntaxError: invalid syntax (line 5)
IndentationError: expected an indented block (line 8)
```

#### 12.4 运行时错误

脚本执行过程中由 Python 解释器抛出：

```
NameError: name 'foo' is not defined (line 5)
IndexError: list index out of range (line 6)
ZeroDivisionError: division by zero (line 7)
KeyError: 'nonexistent' (line 8)
TypeError: unsupported operand type(s) (line 9)
FileNotFoundError: [Errno 2] No such file or directory (line 10)
```

#### 12.5 循环与中止错误

```
while 循环超过最大迭代次数 100000，可能存在无限循环
脚本已被手动中止                  # 手动点击强制终止
脚本执行超时（30秒），已被自动中止  # 超时自动中止
```

#### 12.6 在编辑器中查看错误

- **运行时定位**：运行出错后，错误信息显示在右侧输出面板，包含完整的 Python traceback
- **状态栏**：顶部显示当前执行状态（运行中 / 已完成 / 出错）

---

### 13. 定时任务

定时任务功能允许管理员设置自动定时执行的 CMD 命令或 MiniScript 脚本，所有任务在后台线程中异步执行，不会阻塞 Web 请求。

#### 13.1 访问方式

- 在 CMD 控制台页面点击「定时任务」按钮
- 直接访问 `/admin/cmd/scheduled`

#### 13.2 调度模式

| 模式 | 说明 | 配置项 |
|------|------|--------|
| **间隔执行** | 每隔指定秒数重复执行 | 间隔秒数（支持快捷按钮：1分/1时/1天） |
| **每日定时** | 每天在固定时间执行一次 | 执行时间（HH:MM 格式） |
| **一次性执行** | 在指定日期时间执行一次后自动禁用 | 执行日期时间 |

#### 13.3 任务类型

| 类型 | 字段值 | 说明 | 执行方式 |
|------|--------|------|----------|
| Shell 命令 | `shell`（默认） | 系统命令 | 通过 `subprocess.run` 在 shell 中执行 |
| MiniScript 脚本 | `script` | Python 脚本 | 通过 `ScriptExecutor` 在独立子进程中以**定时模式**执行（非交互），`alert`/`prompt`/`confirm` 自动降级（详见 [第 7 节](#7-执行模式)） |

#### 13.4 创建任务

1. 点击「创建定时任务」按钮
2. 填写任务名称（如：每日备份）
3. 选择任务类型（Shell 命令 / MiniScript 脚本）
4. 输入要执行的内容（如：`tar -czf /backup/data.tar.gz /data` 或 Python 脚本代码）
5. 选择调度类型
6. 根据调度类型设置间隔或执行时间
7. 点击「保存」

#### 13.5 任务管理

- **启用/禁用**：切换任务状态，禁用后不再自动执行
- **编辑**：修改任务配置，保存后重新计算下次执行时间
- **删除**：删除任务（相关日志保留）
- **立即执行**：手动触发任务立即执行，不影响原有调度
- **查看日志**：查看该任务的执行历史和输出

#### 13.6 执行状态实时反馈

任务卡片底部显示「最近执行状态徽章」，无需手动刷新即可看到执行结果：

- **未执行**：灰色「未执行」提示
- **执行中**：蓝色「执行中…」徽章（手动触发或调度器刚启动任务时）
- **成功**：绿色徽章 + 开始时间 + 耗时
- **失败**：红色徽章 + 开始时间 + 耗时
- **活动中**：当任务在最近 10 分钟内有执行记录时，徽章右侧追加蓝色「活动中」标签

**刷新机制**：

- 页面每 15 秒自动通过 `/admin/cmd/scheduled/status` 接口拉取最新状态（轻量接口，仅返回状态信息）
- 仅更新状态徽章，不重渲染整个列表，避免打断用户操作
- 切回浏览器标签页时立即刷新一次
- 手动「立即执行」时立即显示「执行中」状态，并在 0.5s / 2s / 5s 后自动拉取最新结果
- 所有模态框打开时暂停自动刷新，关闭后恢复

#### 13.7 执行日志

每次任务执行后自动记录以下信息（Shell 与 Script 两种任务类型的日志格式一致）：

| 字段 | 说明 |
|------|------|
| 任务名称 | 执行时的任务名称 |
| 命令 | 执行的命令或脚本代码 |
| 输出 | stdout + stderr（脚本任务为 `echo`/`print` 输出，超过 10000 字符自动截断） |
| 退出码 | 命令退出码 |
| 状态 | 成功 / 失败 |
| 开始时间 | 执行开始时间 |
| 完成时间 | 执行完成时间 |
| 耗时 | 执行耗时（秒） |

#### 13.8 配置

在 `config.py` 中可调整以下配置：

```python
TASK_SCHEDULER_INTERVAL = 10        # 调度器检查间隔（秒）
TASK_EXECUTION_TIMEOUT = 300        # 单个任务执行超时（秒）
TASK_EXECUTOR_POOL_SIZE = 4         # 执行线程池大小

# 脚本任务相关
SCRIPT_DEFAULT_TIMEOUT = 30         # 脚本默认执行超时（秒）
SCRIPT_MAX_TIMEOUT = 300            # 脚本最大允许超时（秒）
SCRIPT_MAX_LOOP_ITER = 100000       # 脚本最大循环迭代次数
SCRIPT_EXECUTOR_POOL_SIZE = 2       # 脚本执行器并发数量限制
```

---

### 14. 日志自动清除

系统自动管理日志表的大小，避免日志无限增长影响性能。

#### 14.1 日志类型与上限

| 日志表 | 配置项 | 默认上限 | 说明 |
|--------|--------|----------|------|
| `access_logs` | `MAX_ACCESS_LOGS` | 500 | 访问日志 |
| `cmd_run_logs` | `MAX_CMD_LOGS` | 1000 | CMD 命令执行日志 |
| `scheduled_task_logs` | `MAX_TASK_LOGS` | 2000 | 定时任务执行日志（含 Shell 与 Script 任务） |

#### 14.2 工作原理

- 后台线程每隔 `LOG_CLEANUP_INTERVAL`（默认 300 秒）检查一次各日志表
- 当某表记录数超过上限时，自动删除最旧的记录，使记录数回到上限
- 清理操作在后台线程中执行，不影响 Web 请求

#### 14.3 修改配置

在 `config.py` 中修改对应的配置值即可：

```python
MAX_ACCESS_LOGS = 500          # 访问日志上限
MAX_CMD_LOGS = 1000            # CMD 命令日志上限
MAX_TASK_LOGS = 2000           # 定时任务日志上限
LOG_CLEANUP_INTERVAL = 300     # 清理检查间隔（秒）
```

## 开发注意事项

编写新代码前必查的**分层规范、易错点清单与测试要求**，详见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。