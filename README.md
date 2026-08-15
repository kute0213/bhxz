# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票与征集、模组介绍、管理后台、服务器性能监控、CMD 控制台与 MiniScript 脚本引擎等功能。

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
├── app.py                        # 应用入口 + WSGI 服务器
├── config.py                     # 全局配置
├── requirements.txt              # Python 依赖
│
├── core/                         # 基础设施层
│   ├── db/                       #   DuckDB 数据库连接与 schema
│   ├── auth.py                   #   认证装饰器、密码哈希
│   └── middleware.py             #   请求中间件
│
├── services/                     # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── user_service.py           #   用户注册/登录/改密
│   ├── attachment_service.py     #   附件上传/清理
│   ├── board_service.py          #   征集主题 CRUD
│   ├── discussion_service.py     #   讨论区帖子管理
│   ├── poll_service.py           #   投票业务
│   ├── captcha.py                #   图形验证码
│   ├── ratelimit.py              #   IP 频率限制
│   ├── logger.py                 #   操作日志
│   ├── process_manager.py        #   子进程生命周期管理
│   ├── process_utils.py          #   子进程工具（编码/缓冲/环境变量）
│   ├── shell.py                  #   跨平台 shell 检测
│   ├── scheduler.py              #   定时任务调度
│   ├── settings_manager.py       #   系统设置管理
│   ├── updater.py                #   一键更新
│   ├── cmd_runner.py             #   命令执行
│   ├── script_store.py           #   MiniScript 脚本存储
│   ├── email/                    #   SMTP 邮件服务
│   ├── terminal/                 #   持久交互式终端服务
│   ├── miniscript/               #   MiniScript 脚本引擎
│   ├── logging/                  #   日志服务（异步写入+自动清理）
│   ├── backup/                   #   数据库备份
│   └── monitoring/               #   系统监控（CPU/内存/运行时间）
│
├── routes/                       # HTTP 路由层（Flask Blueprint）
│   ├── main/                     #   首页/登录/注册/设置/找回密码
│   ├── admin/                    #   管理后台（用户/日志/模组/指南/设置/备份/CMD/讨论/广播）
│   ├── community/                #   社区（投票/征集/留言板）
│   ├── discussion/               #   讨论区
│   ├── guides/                   #   服务器指南
│   ├── cmd/                      #   CMD 控制台
│   ├── scheduled/                #   定时任务管理
│   ├── api/                      #   公开 API（性能/统计/验证码/邮箱）
│   ├── docs/                     #   文档系统
│   └── public/                   #   公开文件管理
│
├── scripts/                      # 构建与维护脚本
│   ├── build/                    #   构建工具
│   │   ├── build_static.py       #     静态资源构建（下载 CDN 资源到本地）
│   │   ├── package.json          #     npm 依赖
│   │   ├── tailwind.config.js    #     Tailwind 配置
│   │   └── tailwind-source.css   #     Tailwind 入口 CSS
│   └── tests/                    #   自动化测试套件
│       ├── run_all.py            #     测试运行器（含静态检查）
│       ├── check_undefined_names.py #  静态检查：未定义名称（NameError 隐患）
│       ├── test_basic.py         #     基础测试（应用启动、路由可达性）
│       ├── test_admin.py         #     管理后台测试
│       ├── test_captcha.py       #     验证码测试
│       ├── test_routes.py        #     路由可达性测试
│       ├── test_services.py      #     服务层测试
│       ├── test_user.py          #     用户系统测试
│       └── test_updater.py       #     一键更新下载进度测试
│
├── templates/                    # Jinja2 模板
│   ├── base.html                 #   基础模板
│   ├── admin/                    #   管理后台模板（17个页面）
│   ├── guides/                   #   服务器指南模板
│   ├── discussion/               #   讨论区模板
│   └── emails/                   #   邮件 HTML 模板
│
├── static/                       # 静态资源
│   ├── css/
│   │   ├── tailwind.css          #   Tailwind CSS（构建生成）
│   │   ├── style.css             #   主样式
│   │   └── base.css              #   全局样式
│   ├── js/
│   │   ├── base.js               #   全局脚本（弹窗/Toast/导航/验证码）
│   │   ├── main.js               #   全局交互
│   │   └── cmd/                  #   CMD 控制台模块（10个文件）
│   └── lib/                      # 第三方库（由 build_static.py 生成）
│       ├── lucide/               #   Lucide 图标库
│       ├── marked/               #   Marked.js Markdown 渲染
│       ├── fonts/                #   字体定义（系统字体栈 + JetBrains Mono）
│       └── monaco/               #   Monaco Editor（.gitignore 排除）
│
├── docs/                         # Markdown 文档
│   ├── CHANGELOG.md              #   更新日志
│   ├── DEVELOPMENT.md            #   开发准则
│   └── cmd-guide.md              #   CMD 控制台使用说明
│
├── scripts/                      # 构建与测试脚本（详见上方）
├── uploads/                      # 用户上传文件
├── backups/db/                   # 数据库备份
└── ssl/                          # SSL 证书
```

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

## 数据库

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

### 访问日志自动清理

超出 `MAX_ACCESS_LOGS`（默认 500 条）阈值时，后台线程自动删除最旧记录。

### 数据库备份

每日凌晨 3:00（可配置）自动执行：
1. 清理过期日志 → CHECKPOINT → DuckDB 在线备份 → 验证 → 清理旧备份

管理后台支持手动触发，显示实时进度条。

## 前端特性

### 磨砂玻璃效果（Glassmorphism）

- **真实酸蚀刻玻璃质感**：`background: linear-gradient()` 渐变背景替代纯色，模拟光线透过玻璃的漫射效果
- `backdrop-filter: blur(48px) saturate(100%)` — 降低饱和度，更自然通透
- 超低透明度 `rgba(0.10)` 背景 + 光线散射伪元素（`radial-gradient` 模拟漫射光）
- 边缘光晕伪元素（`mask-composite` 渐变边框，模拟玻璃切割面折射）
- 动态背景光球（CSS `@keyframes` 动画），降低透明度使光晕更柔和
- 全局细微噪点纹理（SVG `feTurbulence`），模拟蚀刻玻璃表面微观散射

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

### 代码维护说明

#### 静态资源更新

当升级第三方库版本时：

1. 修改 `scripts/build/build_static.py` 中的版本号
2. 运行 `python scripts/build/build_static.py` 重新下载
3. 提交 `static/lib/` 目录到 Git（`static/lib/monaco/` 除外）

一键更新功能会自动执行此流程。

#### 添加新的外部资源

1. 在 `scripts/build/build_static.py` 中添加下载函数
2. 在模板中使用 `url_for('static', filename='lib/...')` 引用
3. 确保更新前已运行构建脚本

#### 引用规则

所有静态资源必须通过 `url_for('static', filename='...')` 引用，禁止硬编码路径或外部 CDN URL。

## 部署

### 方式一：CherryPy（内置）

```bash
python app.py                    # HTTP
export ENABLE_SSL=1 && python app.py  # HTTPS
```

### 方式二：Nginx 反向代理

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/private.key;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 架构

### 分层设计

| 层级 | 职责 |
|------|------|
| **入口** `app.py` | Flask 实例、蓝图注册、WSGI 服务器 |
| **核心** `core/` | 数据库、认证、中间件 — 不含业务逻辑，不导入 services |
| **服务** `services/` | 纯业务逻辑，Flask 无关 — 返回 `(success, data_or_error)` 元组 |
| **路由** `routes/` | 薄层 HTTP 处理 — 参数解析、调用 service、构造响应 |
| **视图** `templates/` `static/` | 纯展示层 |

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

### 安全

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 图形验证码服务端内存存储，一次性删除防重放
5. Session Cookie 启用 `HttpOnly` + `SameSite=Lax`
6. 邮箱唯一性检查（一个邮箱仅可注册一个账号）
7. IP 频率限制（注册/登录）

## 开发注意事项

- **弹窗定位**：全屏弹窗/模态框应放置在 `{% block page_modals %}` 中（在 `</main>` 之后渲染），而非 `{% block content %}` 内，避免 `page-content` 的 `transform` 影响 `position: fixed` 定位。
- **图形验证码模块化**：全局验证码弹窗 HTML 位于 `base.html`，JS 逻辑位于 `base.js` 的 `CaptchaModal` 对象。页面通过 `CaptchaModal.show(hint, callback)` 或 `window.__showCaptchaModal(hint, callback)` 调用。
- **白屏闪烁防护**：`base.html` 的 `<head>` 中内联深色背景样式和页面过渡动画初始状态，在外部 CSS 加载前即生效。

## 更新日志

详见 [docs/CHANGELOG.md](file:///workspace/docs/CHANGELOG.md)。