# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票、征集（多附件上传）、模组介绍、管理后台、服务器性能监控、CMD 控制台与 MiniScript 脚本引擎等功能。

## 项目结构

```
/workspace
├── app.py                        # 应用入口：Flask 实例、蓝图注册、CherryPy 服务器（支持 SSL）
├── config.py                     # 全局配置（数据库路径、上传限制、密钥、日志上限、调度器、备份）
├── requirements.txt              # Python 依赖
│
├── core/                         # 核心基础设施
│   ├── db/                       #   DuckDB 数据库层（兼容 sqlite3 接口：Row/lastrowid/executescript）
│   │   ├── __init__.py           #     包入口，导出 get_db / init_db / DuckDBConnection 等
│   │   ├── connection.py         #     连接、游标、行对象封装 + get_db
│   │   └── schema.py             #     建表 SQL、迁移、默认数据 + init_db
│   ├── auth.py                   #   认证模块（login_required / admin_required 装饰器、hash_password / verify_password、当前用户，含请求内缓存，AJAX 返回 JSON）
│   ├── middleware.py             #   请求中间件（异步访问日志记录，不阻塞请求）
│   ├── process_utils.py          #   跨平台子进程工具（编码解码、环境变量、run_process 封装）
│   ├── process_manager.py        #   跨平台子进程生命周期管理（启动 / 终止 / 进程组 / 信号）
│   └── shell.py                  #   跨平台 shell 检测与环境构造（Windows cmd/ps / Unix bash-sh）
│
├── services/                     # 业务服务（含异步后台线程）
│   ├── monitoring/               #   系统监控（CPU 使用率/温度、内存、运行时间，跨平台）
│   │   ├── __init__.py           #     包入口，导出 get_cpu_usage / get_cpu_temperature / get_memory_info / get_system_info
│   │   ├── cpu.py                #     CPU 使用率与温度采集
│   │   ├── memory.py             #     内存信息采集
│   │   └── system.py             #     系统信息采集 + psutil 可用性检测
│   ├── ip.py                     #   IP 工具（真实 IP 解析、异步地理信息查询）
│   ├── cmd_runner.py             #   命令执行服务（SSE 流式 + 同步执行 + 异步日志记录）
│   ├── scheduler.py              #   定时任务调度引擎（后台线程 + ThreadPoolExecutor 异步执行）
│   ├── logging/                  #   日志服务包（后台线程异步写入与清理）
│   │   ├── __init__.py           #     包入口，导出 log_cleaner / log_writer
│   │   ├── cleaner.py            #     日志自动清除服务（后台线程定期清理超限记录）
│   │   └── writer.py             #     异步日志写入器（队列 + 后台线程批量写入）
│   ├── backup/                   #   数据库备份服务包
│   │   ├── __init__.py           #     包入口，导出 BackupScheduler
│   │   ├── manager.py            #     数据库备份管理器（DuckDB 在线备份 + 旧备份清理）
│   │   └── scheduler.py          #     每日定时备份调度器（默认凌晨 3:00，支持热重载）
│   ├── settings_manager.py       #   系统设置管理器（数据库存储 + 内存缓存，支持热重载）
│   ├── captcha.py                #   图形验证码服务（两位数运算 + 服务端内存存储 + 一次性删除防重放）
│   ├── email/                    #   SMTP 邮件服务包
│   │   ├── __init__.py           #     包入口，导出 email_service / email_code_service / 模板函数
│   │   ├── service.py            #     SMTP 邮件发送服务（基于标准库 smtplib，后台线程异步发送）
│   │   ├── code.py               #     邮箱验证码服务（生成/存储/验证，内存存储，自动过期）
│   │   └── templates.py          #     邮件 HTML 模板模块（统一构建 + 公共组件复用 + 移动端响应式适配）
│   ├── script_store.py           #   统一脚本存储服务（数据库存储，按名称自动排序）
│   ├── terminal/                 #   持久交互式终端服务（session-based shell 子进程管理）
│   │   ├── __init__.py           #     包入口，导出 TerminalManager / TerminalSession
│   │   ├── manager.py            #     终端会话管理器（创建 / 获取 / 重置 / 过期清理）
│   │   └── session.py            #     单个持久 shell 会话（IO 读写 / 生命周期）
│   └── miniscript/               #   MiniScript 后端执行引擎（独立子进程执行）
│       ├── __init__.py           #     包入口，导出 ScriptExecutor
│       ├── builtins.py           #     内置函数工厂（echo/cmd/file_*/db_*/alert/prompt/confirm）
│       ├── runner.py             #     子进程入口（exec 执行脚本 + 管道通信 + 超时看门狗）
│       ├── executor.py           #     ScriptExecutor 类（multiprocessing + Pipe + abort）
│       └── session.py            #     按用户 session 隔离的脚本执行状态管理器
│
├── routes/                       # 路由控制器（Flask Blueprint）
│   ├── main.py                   #   页面路由：首页、登录/注册、用户设置、性能监控页
│   ├── discussion/               #   讨论蓝图包：帖子列表、发帖、回复、管理
│   │   ├── __init__.py           #     创建 discussion_bp，导入子模块注册路由
│   │   ├── pages.py              #     帖子列表/详情/创建/编辑页面路由
│   │   └── api.py                #     回复/删除/置顶/锁定 API
│   ├── community/                #   社区蓝图包：投票 CRUD、征集 CRUD、多附件上传
│   │   ├── __init__.py           #     创建 community_bp，导入子模块注册路由
│   │   ├── pages.py              #     社区首页渲染 + 附件下载
│   │   ├── polls.py              #     投票创建/投票/删除/启停
│   │   ├── board.py              #     征集主题/回复/删除（含附件管理）
│   │   └── helpers.py            #     _is_ajax / _respond 辅助函数
│   ├── admin/                    #   管理蓝图包：用户管理、日志、模组介绍、数据库备份、系统设置、服务器指南管理
│   │   ├── __init__.py           #     创建 admin_bp，导入子模块注册路由
│   │   ├── pages.py              #     管理后台首页
│   │   ├── users.py              #     用户列表/切换管理员/删除用户
│   │   ├── mod_intros.py         #     模组介绍 增/改/删
│   │   ├── logs.py               #     访问日志分页查看/清空
│   │   ├── settings.py           #     系统设置页面 + API（在线编辑配置，热重载）
│   │   ├── backup.py             #     数据库备份页面/启动/进度/历史
│   │   ├── guides.py             #     服务器指南 CRUD + 审核工作流
│   │   ├── guide_bans.py         #     指南编辑权限封禁管理（用户/IP）
│   │   ├── discussion.py         #     讨论管理（帖子列表/删除/置顶/锁定 + 分类管理）
│   │   └── broadcast.py          #     广播邮件：向全体用户发送 Markdown 格式邮件
│   ├── guides/                   #   服务器指南蓝图包：公开列表/详情 + 成员提交 API
│   │   ├── __init__.py           #     创建 guides_bp，导入子模块注册路由
│   │   ├── pages.py              #     指南列表页 + 详情页（Markdown 渲染）
│   │   └── api.py                #     成员提交/编辑指南 API（需审核）
│   ├── cmd/                      #   CMD 控制台蓝图包：实时命令执行 + 一键命令管理 + 脚本
│   │   ├── __init__.py           #     创建 cmd_bp，导入子模块注册路由
│   │   ├── pages.py              #     命令控制台首页 + 脚本编辑器页面
│   │   ├── commands.py           #     快捷命令 CRUD + 执行预设命令
│   │   ├── execution.py          #     Shell 命令同步执行 + SSE 流式执行
│   │   ├── script.py             #     MiniScript SSE 执行 + _admin_check 辅助函数
│   │   ├── scripts.py            #     统一脚本管理 CRUD（数据库存储）
│   │   └── terminal.py           #     交互式终端路由（持久 shell 会话 + SSE 流式 + 命令输入）
│   ├── scheduled/                #   定时任务蓝图包：任务 CRUD、启停、触发、执行日志
│   │   ├── __init__.py           #     创建 scheduled_bp + _admin_check，导入子模块注册路由
│   │   ├── tasks.py              #     任务 CRUD/启停/触发/状态查询
│   │   └── logs.py               #     任务执行日志（单任务/全部/详情）
│   ├── docs.py                   #   文档路由：Markdown 文档列表 + 内容 API
│   ├── public_files.py           #   公开文件管理（本地文件/目录对外公开访问）
│   └── api/                      #   API 接口：
│       ├── __init__.py           #     包入口，导出各蓝图
│       ├── public.py             #     /api/performance, /api/stats, /api/polls
│       ├── captcha.py            #     /api/captcha     验证码生成
│       ├── email_code.py         #     /api/email       邮箱验证码发送
│       └── admin.py              #     /api/admin/logs  访问日志（管理员）
│
├── templates/                    # Jinja2 模板（25 个页面）
│   ├── base.html                 #   基础模板（全局样式、磨砂玻璃、导航栏、动画，含 page_modals 弹窗挂载点）
│   ├── index.html                #   首页（模组介绍卡片 + 服务器指南入口）
│   ├── community.html            #   社区页（投票 + 征集）
│   ├── login.html / register.html
│   ├── settings.html             #   用户设置（改用户名/密码/注销）
│   ├── performance.html          #   服务器性能监控
│   ├── docs.html                 #   文档中心（Markdown 渲染 + 侧边栏导航）
│   ├── guides/                   #   服务器指南模板
│   │   ├── index.html            #     指南列表页（卡片展示 + 状态筛选）
│   │   └── detail.html           #     指南详情页（Markdown 渲染 + 标题锚点）
│   ├── discussion/               #   讨论帖子模板
│   │   ├── list.html             #     帖子列表页（分类筛选、置顶优先、分页）
│   │   ├── detail.html           #     帖子详情页（Markdown 渲染 + 回复列表）
│   │   └── create.html           #     发帖/编辑页面（Markdown 编辑 + 附件上传）
│   ├── admin.html                #   管理后台首页
│   ├── admin_users.html          #   用户管理
│   ├── admin_logs.html           #   访问日志
│   ├── manage_mod_intros.html    #   模组介绍管理
│   ├── admin_guides.html         #   服务器指南管理（审核/编辑/删除）
│   ├── admin_guide_form.html     #   指南编辑页面（Markdown 编辑器 + 实时预览）
│   ├── admin_guide_bans.html     #   指南编辑权限封禁管理
│   ├── admin_cmd.html            #   CMD 控制台
│   ├── admin_cmd_editor.html     #   脚本编辑器（专业代码编辑器页面）
│   ├── admin_cmd_scheduled.html  #   定时任务管理页面
│   ├── admin_settings.html       #   系统设置（在线编辑配置，支持重置，热重载）
│   ├── admin_db_backup.html      #   数据库优化备份页面（进度条 + 备份历史）
│   ├── admin_public_files.html   #   公开文件管理
│   ├── admin_discussion.html     #   讨论管理（帖子列表/置顶/锁定/删除）
│   ├── admin_discussion_categories.html  #   讨论分类管理（创建/删除）
│   ├── admin_broadcast.html      #   广播邮件（Markdown 编辑器 + 实时预览 + 发送确认）
│   └── 403.html / 404.html       #   错误页
│
├── static/                       # 静态资源
│   ├── css/
│   │   ├── style.css             #   主样式（磨砂玻璃、动画、响应式）
│   │   └── base.css              #   base.html 提取的全局样式（导航栏、模态框、动画）
│   └── js/
│       ├── main.js               #     全局交互（滚动动画、鼠标光晕、按钮反馈）
│       ├── base.js               #     base.html 提取的全局脚本（导航、Toast、键盘快捷键）
│       └── cmd/                  #     CMD 控制台模块（10 个文件，职责清晰）
│           ├── terminal-core.js  #       终端核心复用库（ANSI 解析 / SSE 连接 / 命令历史 / 输入发送）
│           ├── modal.js          #       页内弹窗系统（替代原生 alert/prompt/confirm）
│           ├── terminal.js       #       终端弹窗（依赖 terminal-core.js，持久 shell 会话 + SSE 流式输出）
│           ├── presets.js        #       快捷命令管理（增删改查，按 [脚本] 前缀区分类型）
│           ├── editor.js         #       脚本编辑器核心（Monaco 初始化、工具栏、可折叠输出面板、自动保存）
│           ├── editor-highlight.js  #    编辑器语法高亮 / 补全 / 主题 / 实时语法诊断（拆分自 editor.js）
│           ├── editor-sse.js     #       编辑器 SSE 执行 / 事件分发 / 强制终止（拆分自 editor.js）
│           ├── editor-terminal.js #      编辑器内嵌终端（依赖 terminal-core.js，持久 shell 会话）
│           ├── scheduled.js      #       定时任务管理核心（任务列表/创建/编辑/启停/触发/从快捷命令选择）
│           ├── scheduled-logs.js #       定时任务执行日志查看（拆分自 scheduled.js）
│           └── main.js           #       主入口（整合各模块 + 后端 SSE 脚本执行）
│
├── docs/                         # Markdown 文档（通过 /docs 页面渲染）
│   ├── README.md                 #   项目说明（README 副本）
│   └── cmd-guide.md              #   CMD 控制台与 MiniScript 用户指南
│
├── uploads/                      # 用户上传文件（自动创建）
├── backups/
│   └── db/                       # 数据库备份目录（自动创建，DuckDB 单文件备份）
└── ssl/                          # SSL 证书目录（可选）
    ├── private.key               #   私钥
    └── fullchain.pem             #   证书链
```

### 开发注意事项

- **弹窗定位**：`base.html` 中的 `<main class="page-content">` 使用了 `transform: translateY(16px)` 实现页面过渡动画。这会创建新的 CSS 包含块，导致内部 `position: fixed` 元素相对于 `.page-content` 而非视口定位。所有全屏弹窗/模态框应放置在 `{% block page_modals %}` 中（该块在 `</main>` 之后渲染），而非 `{% block content %}` 内。

### 分层设计

| 层级 | 目录 | 职责 |
|------|------|------|
| **入口** | `app.py` | 创建 Flask 实例、注册蓝图、启动 WSGI 服务器 |
| **核心** | `core/` | 数据库连接、认证装饰器、请求中间件 — 不含业务逻辑 |
| **服务** | `services/` | 系统监控、IP 解析、调度器、MiniScript 引擎 — 可被任意路由调用 |
| **路由** | `routes/` | 接收请求、调用 core/services、返回响应 |
| **视图** | `templates/` `static/` | 纯展示层，不包含后端逻辑 |

## 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装与启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务（默认 HTTP 模式，端口 5000）
python app.py
```

### 默认管理员

首次启动自动创建：

| 用户名 | 密码 |
|--------|------|
| `服主` | `admin1324` |

> 登录后请立即修改默认密码。

## 配置说明

### 管理后台在线编辑（推荐）

所有运行时配置均可在 **管理后台 → 系统设置** 中在线编辑，修改后立即生效（热重载），无需重启服务器。

支持编辑的配置分类：
- **日志清理**：访问日志、命令日志、任务日志上限及清理间隔
- **定时任务**：调度间隔、执行超时、线程池大小
- **数据库备份**：自动备份时间、保留份数、超时、清理日志、CHECKPOINT
- **脚本执行**：默认超时、最大超时、最大循环次数、并发数
- **安全配置**：会话有效期、登录失败锁定次数及时间
- **讨论区配置**：回复实时刷新间隔、每页加载数量
- **服务器配置**：监听地址、端口、调试模式、工作线程数

修改后的值存储在 `settings` 表中，重启后依然保留。点击「重置」可恢复为默认值。

### config.py

`config.py` 中定义了所有配置的默认值。如需修改默认值，可编辑此文件；但推荐使用管理后台在线编辑。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DB_PATH` | DuckDB 数据库文件路径 | `./site.duckdb` |
| `UPLOAD_DIR` | 上传文件目录 | `./uploads` |
| `MAX_CONTENT_LENGTH` | 最大上传大小 | 100 MB |
| `SECRET_KEY` | Flask Session 密钥 | `mc_server_site_random_secret_key_2024` |
| `REGISTER_VERIFY_CODE` | 注册验证码 | `binhai_xz` |
| `MAX_ACCESS_LOGS` | 访问日志最大保留条数 | `500` |
| `MAX_CMD_LOGS` | CMD 命令日志最大保留条数 | `1000` |
| `MAX_TASK_LOGS` | 定时任务日志最大保留条数 | `2000` |
| `LOG_CLEANUP_INTERVAL` | 日志清理检查间隔（秒） | `300` |
| `TASK_SCHEDULER_INTERVAL` | 定时任务调度检查间隔（秒） | `10` |
| `TASK_EXECUTION_TIMEOUT` | 单任务执行超时（秒） | `300` |
| `TASK_EXECUTOR_POOL_SIZE` | 任务执行线程池大小 | `4` |
| `BACKUP_DIR` | 数据库备份目录 | `./backups/db` |
| `BACKUP_FILENAME_FORMAT` | 备份文件名格式（strftime） | `backup_%Y%m%d_%H%M%S.duckdb` |
| `BACKUP_SCHEDULED_TIME` | 每日自动备份时间（HH:MM） | `03:00` |
| `MAX_BACKUPS` | 最大保留备份份数 | `30` |
| `BACKUP_TIMEOUT` | 备份超时（秒） | `3600` |
| `BACKUP_CLEAN_LOGS` | 备份前是否清理过期日志 | `True` |
| `BACKUP_CHECKPOINT` | 备份前是否执行 CHECKPOINT | `True` |
| `SCRIPT_DEFAULT_TIMEOUT` | 脚本默认执行超时（秒） | `30` |
| `SCRIPT_MAX_TIMEOUT` | 脚本最大允许超时（秒） | `300` |
| `SCRIPT_MAX_LOOP_ITER` | 脚本最大循环迭代次数 | `100000` |
| `SCRIPT_EXECUTOR_POOL_SIZE` | 脚本执行器并发数量限制 | `2` |
| `DISCUSSION_REFRESH_INTERVAL` | 讨论区回复实时刷新间隔（秒） | `5` |
| `REPLIES_PER_PAGE` | 讨论区回复每页加载数量 | `10` |

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `ENABLE_SSL` | 启用 HTTPS（需配合证书文件） | `0`（禁用） |

### SSL 证书

```bash
# 1. 创建 ssl/ 目录并放入证书
mkdir ssl
cp /path/to/private.key ssl/
cp /path/to/fullchain.pem ssl/

# 2. 启用 SSL 并启动
export ENABLE_SSL=1
python app.py
```

未找到证书或未设置 `ENABLE_SSL` 时，自动回退 HTTP 模式并输出警告。

## API 接口

所有 API 以 `/api` 为前缀，返回 JSON 格式数据。按功能模块拆分至 [routes/api/](file:///workspace/routes/api/) 目录：

| 模块 | 文件 | 端点 | 说明 |
|------|------|------|------|
| 公开 API | [public.py](file:///workspace/routes/api/public.py) | `/api/performance`, `/api/stats`, `/api/polls` | 性能监控 / 网站统计 / 投票数据 |
| 访问日志 | [admin.py](file:///workspace/routes/api/admin.py) | `/api/admin/logs/refresh` | 管理员：分页日志 |

### 公开接口

#### `GET /api/performance`

获取服务器性能数据。

```json
{
  "cpu_usage": 23.5,
  "cpu_temp": 45.2,
  "memory": { "total": 8589934592, "used": 3221225472, "available": 5368709120, "usage": 37.5 },
  "system": { "os": "Linux 5.15.0", "uptime": "10天 5小时 30分钟", "uptime_seconds": 883800 },
  "timestamp": "2024-01-15 10:30:00"
}
```

#### `GET /api/stats`

获取网站统计数据。

```json
{
  "total_users": 42,
  "total_polls": 5,
  "total_votes": 128,
  "total_board_topics": 8,
  "total_board_replies": 67
}
```

#### `GET /api/polls`

获取所有投票数据（含选项、投票数、百分比、当前用户投票状态）。

```json
{
  "polls": [
    {
      "id": 1,
      "title": "下一个模组投票",
      "is_multiple": 1,
      "is_active": 1,
      "total_votes": 15,
      "user_voted": false,
      "options": [
        { "id": 1, "option_text": "Terralith", "vote_count": 8, "percent": 53 },
        { "id": 2, "option_text": "SnowySpirit", "vote_count": 7, "percent": 47 }
      ]
    }
  ]
}
```

### 管理员接口

#### `GET /api/admin/logs/refresh?page=1`

刷新访问日志（需登录管理员）。每页 50 条，返回日志列表及分页信息。

### 社区操作（支持 AJAX）

社区路由（投票、征集）同时支持传统表单提交和 AJAX 请求：

- **表单提交**：`flash` 消息 + 页面重定向（默认行为）
- **AJAX 请求**：返回 JSON 响应（检测 `X-Requested-With`、`Content-Type: application/json`、`Accept: application/json`）

```json
{
  "success": true,
  "message": "投票成功",
  "redirect": "/community"
}
```

支持的 AJAX 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/poll/create` | 创建投票（管理员） |
| POST | `/poll/<id>/vote` | 投票 |
| POST | `/poll/<id>/delete` | 删除投票（管理员） |
| POST | `/poll/<id>/toggle` | 启用/禁用投票（管理员） |
| POST | `/board/create` | 创建征集（管理员） |
| POST | `/board/<id>/reply` | 回复征集（支持多附件） |
| POST | `/board/<id>/delete` | 删除征集（管理员） |
| POST | `/board/reply/<id>/delete` | 删除回复（管理员或作者） |
| POST | `/discussion/<id>/reply` | 回复帖子（支持多附件） |
| POST | `/discussion/reply/<id>/delete` | 删除回复 |
| GET | `/discussion/<id>/api/replies` | **分页获取回复（分段加载）** |
| GET | `/discussion/<id>/api/new-replies` | **获取最新回复（实时刷新，仅返回比 last_id 大的记录）** |
| POST | `/discussion/<id>/pin` | 置顶/取消置顶（管理员） |
| POST | `/discussion/<id>/lock` | 锁定/解锁（管理员） |
| POST | `/discussion/<id>/delete` | 删除帖子（作者或管理员） |

### CMD 控制台与 MiniScript（管理员）

CMD 控制台提供实时终端、快捷命令管理、专业脚本编辑器（Monaco）与定时任务管理。MiniScript 是一种 **Python 子集脚本语言**，由后端执行引擎在独立 Python 子进程中运行，通过 SSE 流式回流输出，不影响 Flask 主服务。支持完整 Python 语法、文件/数据库访问、交互弹窗、强制终止等。

> **完整的脚本语法、内置函数参考、安全限制、执行模式、实用示例与常见问题，请参阅 [CMD 控制台使用说明](file:///workspace/docs/cmd-guide.md)。**

后端接口位于 [routes/cmd/](file:///workspace/routes/cmd/)，前端代码位于 [static/js/cmd/](file:///workspace/static/js/cmd/)：

| 模块 | 文件 | 职责 |
|------|------|------|
| 终端弹窗 | [terminal.js](file:///workspace/static/js/cmd/terminal.js) | **持久 shell 会话**（cd 状态保持）、SSE 流式输出、命令历史（↑↓）、Ctrl+L 清屏、Ctrl+C 中断、断线 3 秒自动重连、脚本运行中止按钮、**心跳看门狗（35 秒无数据主动重连）**、generation 计数防止多连接竞争 |
| 快捷命令 | [presets.js](file:///workspace/static/js/cmd/presets.js) | 增删改查一键命令（数据库存储，**按名称自动排序**，删除前检查定时任务引用） |
| 脚本编辑器核心 | [editor.js](file:///workspace/static/js/cmd/editor.js) | Monaco 初始化、工具栏绑定、**右侧可折叠终端面板**、**自动保存**（防抖 2 秒，状态指示器）、统一脚本存储 |
| 编辑器高亮 | [editor-highlight.js](file:///workspace/static/js/cmd/editor-highlight.js) | Monaco Python 语法高亮、代码补全、自定义主题、**前端实时语法诊断**（拆分自 editor.js） |
| 编辑器 SSE | [editor-sse.js](file:///workspace/static/js/cmd/editor-sse.js) | SSE 执行、事件分发、强制终止、运行时显示命令行（拆分自 editor.js） |
| **编辑器终端** | [editor-terminal.js](file:///workspace/static/js/cmd/editor-terminal.js) | **持久化交互式终端**：真实 shell 会话、cd 状态保持、SSE 流式输出、命令历史（↑↓）、Ctrl+L 清屏、Ctrl+C 终止 |
| 定时任务核心 | [scheduled.js](file:///workspace/static/js/cmd/scheduled.js) | 任务列表/创建/编辑/启停/触发/状态轮询、**仅从快捷命令列表选择**（command_id 引用 cmd_commands），暴露 `window.ScheduledCore` |
| 定时任务日志 | [scheduled-logs.js](file:///workspace/static/js/cmd/scheduled-logs.js) | 执行日志查看（分页/详情），暴露 `window.ScheduledLogs.openLogsModal`（拆分自 scheduled.js） |
| 主入口 | [main.js](file:///workspace/static/js/cmd/main.js) | 整合各模块、通过后端 SSE API 执行脚本、交互事件处理 |
| 页内弹窗 | [modal.js](file:///workspace/static/js/cmd/modal.js) | 替代原生 alert/prompt/confirm，返回 Promise 支持 async/await，**状态机+队列架构彻底解决连续弹窗闪退**，仅可通过按钮或 ESC 关闭（禁用背景点击关闭） |

> **前端模块化拆分**：`editor.js` 拆分为 `editor.js`（核心）+ `editor-highlight.js`（高亮）+ `editor-sse.js`（SSE）；`scheduled.js` 拆分为 `scheduled.js`（任务管理）+ `scheduled-logs.js`（日志查看）。模板按依赖顺序加载：核心文件 → 高亮 → SSE → 入口。`base.html` 的内联 CSS / JS 已分别提取至 `static/css/base.css` 和 `static/js/base.js`。

#### 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/cmd` | CMD 控制台页面 |
| GET | `/admin/cmd/editor` | **专业脚本编辑器页面**（支持 `?edit=<id>` 编辑现有脚本） |
| GET | `/admin/cmd/commands` | 获取一键命令列表（JSON） |
| POST | `/admin/cmd/commands` | 新增一键命令 |
| PUT / POST | `/admin/cmd/commands/<id>` | 更新一键命令 |
| POST / DELETE | `/admin/cmd/commands/<id>/delete` | 删除一键命令 |
| POST | `/admin/cmd/run` | 同步执行命令（一次性返回全部输出） |
| GET / POST | `/admin/cmd/run-stream` | **实时流式执行**（SSE，逐行返回输出） |
| POST | `/admin/cmd/run-preset/<id>` | 执行一键命令 |
| POST | `/admin/cmd/run-script` | **MiniScript 脚本执行**（SSE 流式 + 交互） |
| POST | `/admin/cmd/abort-script` | 终止正在执行的 MiniScript 脚本 |
| POST | `/admin/cmd/script-response` | 回传前端对 prompt/confirm 事件的响应 |
| GET | `/admin/cmd/scripts` | **获取脚本列表**（统一脚本存储，支持 type 过滤） |
| POST | `/admin/cmd/scripts` | **创建脚本**（自动命名，写入文件和数据库） |
| GET | `/admin/cmd/scripts/<id>` | 获取脚本详情 |
| PUT / POST | `/admin/cmd/scripts/<id>` | 更新脚本内容/名称/备注 |
| POST / DELETE | `/admin/cmd/scripts/<id>/delete` | 删除脚本（同时删除文件） |
| GET | `/admin/cmd/terminal/stream` | **交互式终端 SSE 流**（持久 shell 会话，实时输出） |
| POST | `/admin/cmd/terminal/input` | **向终端发送输入**（命令 / Ctrl+C / 等） |
| POST | `/admin/cmd/terminal/close` | 关闭当前终端会话（重启 shell 进程） |

**SSE 实时输出事件格式**：

```
data: {"type": "output", "line": "Hello world"}
data: {"type": "exit", "code": 0}
data: [DONE]
```

事件类型：
- `output` — 标准输出/错误输出的一行内容
- `exit` — 进程退出，含返回码
- `error` — 执行错误信息

#### MiniScript 脚本执行 API（SSE 流式 + 交互）

脚本在独立子进程中运行，事件通过 SSE 流式回流，交互事件（prompt/confirm）通过单独的 POST 接口回传响应。所有接口仅管理员可用。

**`POST /admin/cmd/run-script`**（SSE 端点）

请求体：
```json
{ "code": "echo('hello')\nname = prompt('输入', '你的名字：')", "timeout": 30 }
```

响应：`Content-Type: text/event-stream`，逐条推送事件，格式为 `data: {"type": "<事件类型>", "data": {...}}\n\n`。

事件类型：

| type | data 字段 | 是否需要前端响应 |
|------|-----------|------------------|
| `output` | `{text: "..."}` | 否 |
| `alert` | `{title, message}` | 否 |
| `error` | `{message: "..."}` | 否 |
| `done` | `{}` | 否（执行结束） |
| `prompt` | `{title, message, default}` | **是**，前端通过 `/admin/cmd/script-response` 回传用户输入字符串 |
| `confirm` | `{title, message}` | **是**，前端通过 `/admin/cmd/script-response` 回传 `true`/`false` |

> 交互响应超时为 60 秒，超时后 `prompt` 返回 `None`、`confirm` 返回 `False`。同时只允许一个脚本执行，并发请求返回 `409`。

**`POST /admin/cmd/abort-script`** — 终止正在执行的脚本，返回 `{"success": true/false}`。

**`POST /admin/cmd/script-response`** — 回传交互响应，请求体 `{"value": "用户输入值"}`，返回 `{"success": true}`。服务端通过 `threading.Event` 唤醒等待中的 SSE 线程。

#### MiniScript 后端执行引擎

基于独立子进程执行的脚本引擎，位于 [services/miniscript/](file:///workspace/services/miniscript/)。脚本在独立 Python 子进程中运行，通过管道回传输出，不影响 Flask 主服务。

**核心特性**：
- **完整 Python 语法**：支持控制流、函数、类、异常处理、`import` 标准库、推导式、f-string、装饰器等
- **独立进程隔离**：使用 `multiprocessing.Process` 启动子进程，超时/异常不影响 Flask 主服务
- **管道通信**：父子进程通过 `multiprocessing.Pipe` 通信，事件流式回流
- **超时与终止**：默认 30 秒超时（可配置上限 300 秒），支持 `abort()` 强制终止
- **两种执行模式**：交互模式（`interactive=True`）支持 alert/prompt/confirm 与前端交互；定时模式（`interactive=False`）交互函数降级（alert 跳过、prompt 返回默认值、confirm 返回 True）

**公共 API**：

```python
from services.miniscript import ScriptExecutor

# 执行脚本（生成器模式，流式 yield 事件）
executor = ScriptExecutor()
for event_type, data in executor.execute(code, interactive=True, timeout=30):
    # 事件类型：output / alert / prompt / confirm / error / done
    print(event_type, data)

# 交互事件响应：prompt/confirm 事件通过 generator.send() 回传用户输入
gen = executor.execute(code, interactive=True)
event = next(gen)
if event[0] == 'prompt':
    response = gen.send(user_input)  # 回传响应并获取下一个事件

# 强制终止
executor.abort()

# 查询状态
executor.is_running()  # -> bool
```

### 文档系统

Markdown 文档存放在 [docs/](file:///workspace/docs/) 目录，通过 `/docs` 页面渲染展示（使用 marked.js）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/docs` | 文档页面（侧边栏导航 + Markdown 渲染） |
| GET | `/docs/api/list` | 文档列表（JSON） |
| GET | `/docs/api/content/<filename>` | 文档内容（JSON） |

现有文档：
- `README.md` — 项目说明
- `cmd-guide.md` — CMD 控制台与 MiniScript 用户指南

主页底部「关于官网」链接跳转至文档页面。

### 服务器指南

服务器指南是面向玩家的 Markdown 文档中心，管理员可直接发布，成员亦可提交但需审核通过后才公开显示。

**功能特性**：
- 卡片式列表页，支持置顶与按标题自动排序
- Markdown 详情页（标题锚点、代码高亮）
- 成员可提交新指南或修改现有指南，进入待审核状态（需验证码验证）
- 管理员后台具备专业 Markdown 编辑器（实时预览）
- 审核工作流：管理员可在预览弹窗中直接通过/拒绝（附原因）
- 管理员新建指南自动通过，无需审核
- 封禁机制：管理员可按用户名或 IP 封禁编辑权限，支持限时或永久封禁

**前端页面**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/guides` | 指南列表页（默认展示已审核通过） |
| GET | `/guides?my=1` | 我的指南（登录用户查看自己提交的） |
| GET | `/guides/<slug>` | 指南详情页（Markdown 渲染） |
| GET | `/discussion` | 帖子列表（支持分类筛选、分页） |
| GET | `/discussion/create` | 发帖页面（需登录） |
| GET | `/discussion/<id>` | 帖子详情页（Markdown 渲染 + 回复列表） |
| GET | `/discussion/<id>/edit` | 编辑帖子（作者或管理员） |
| GET | `/discussion/<id>/api/replies` | **分页获取回复（支持分段加载）** |
| GET | `/discussion/<id>/api/new-replies` | **获取最新回复（实时刷新用）** |

**成员 API（需登录）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/guides/submit` | 提交新指南（进入 `pending` 待审核） |
| POST | `/api/guides/<id>/edit-request` | 提交编辑请求（进入 `pending` 待审核） |
| GET | `/api/guides/my` | 获取当前用户的指南列表 |

**管理后台（仅管理员）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/guides` | 指南管理首页（审核/编辑/删除） |
| GET/POST | `/admin/guides/create` | 创建指南（直接通过，无需审核） |
| GET/POST | `/admin/guides/<id>/edit` | 编辑指南 |
| POST | `/admin/guides/<id>/delete` | 删除指南 |
| POST | `/admin/guides/<id>/approve` | 通过审核 |
| POST | `/admin/guides/<id>/reject` | 拒绝审核（需填写原因） |
| GET | `/admin/guide-bans` | 封禁列表 |
| POST | `/admin/guide-bans/create` | 新增封禁（按用户名或 IP） |
| POST | `/admin/guide-bans/<id>/delete` | 解除封禁 |
| GET | `/admin/discussion` | 讨论管理列表 |
| POST | `/admin/discussion/<id>/delete` | 管理员删除帖子 |
| POST | `/admin/discussion/<id>/toggle-pin` | 管理员切换置顶 |
| POST | `/admin/discussion/<id>/toggle-lock` | 管理员切换锁定 |
| GET/POST | `/admin/discussion/categories` | 分类管理（创建/删除） |

## 数据库

使用 **DuckDB**（高性能嵌入式 OLAP 数据库，单文件、支持列存、窗口函数），首次启动自动建表。共 20 张表：

| 表名 | 说明 | 关键约束 |
|------|------|----------|
| `users` | 用户 | `username` 唯一 |
| `polls` | 投票 | — |
| `poll_options` | 投票选项 | 外键 `poll_id` 级联删除 |
| `poll_votes` | 投票记录 | 唯一约束 `(poll_id, user_id, option_id)` 防重复投票 |
| `board_topics` | 征集主题 | 外键 `user_id` 级联删除 |
| `board_replies` | 征集回复 | 外键 `topic_id` 级联删除，`attachment` 存 JSON 数组 |
| `mod_intros` | 模组介绍 | — |
| `cmd_commands` | 一键命令 | 名称 / 命令 / 描述 / 排序 / 类型 |
| `scripts` | **统一脚本表** | **name / description / content / script_type（数据库存储，无文件系统依赖）** |
| `access_logs` | 访问日志 | 含 IP 国家/地区/城市/ISP，自动清理 |
| `scheduled_tasks` | 定时任务 | 支持间隔/每日/一次性三种模式，`task_type` 强制为 shell，`command_id` 关联 `cmd_commands` 表（仅执行快捷命令） |
| `scheduled_task_logs` | 定时任务执行日志 | 外键 `task_id` 设空 |
| `cmd_run_logs` | CMD 命令执行日志 | — |
| `db_backups` | 数据库备份记录 | 备份状态/大小/耗时 |
| `settings` | **系统设置** | **key 唯一，存储用户自定义配置，支持热重载** |
| `server_guides` | **服务器指南** | **title / slug / summary / content(Markdown) / status / author_id / is_pinned / 按标题自动排序** |
| `guide_edit_bans` | **指南编辑封禁** | **user_id / ip_address / banned_by / reason / expires_at** |
| `discussion_categories` | **讨论分类** | **slug 唯一，支持排序** |
| `discussion_topics` | **讨论帖子** | **外键 `user_id`，支持分类/标签/附件/置顶/锁定/浏览量** |
| `discussion_replies` | **讨论回复** | **外键 `topic_id`，支持附件，JSON 存储** |

所有外键均启用 `enable_foreign_keys` 和 `ON DELETE CASCADE`。

### DuckDB 兼容层说明

为了最小化代码改动，[core/db/](file:///workspace/core/db/) 对 DuckDB 做了 sqlite3 兼容封装：

- **`DuckDBRow`**：模拟 `sqlite3.Row`，支持 `row['col']`、`row[0]`、`keys()` 等
- **`lastrowid`**：INSERT 后通过序列 `currval('table_id_seq')` 获取自增 ID
- **`executescript`**：按分号拆分多条 SQL 依次执行
- **`SEQUENCE + nextval()`**：模拟 SQLite 的 `AUTOINCREMENT`

### 访问日志自动清理

访问日志表会持续增长，为避免数据库膨胀，启用自动清理机制：

- **阈值**：由 `config.py` 的 `MAX_ACCESS_LOGS`（默认 500 条）控制
- **触发频率**：后台线程定期检查，不影响 Web 请求
- **清理方式**：超出阈值时，删除最旧的记录（按 `id ASC` 排序），仅删除超出部分
- **实现位置**：[services/logging/cleaner.py](file:///workspace/services/logging/cleaner.py)

### 数据库备份与优化

每日凌晨 3:00（可配置）自动执行数据库优化与备份：

**备份流程**：
1. 清理过期日志（可选，`BACKUP_CLEAN_LOGS`）
2. 执行 `CHECKPOINT` 合并 WAL 到主文件（可选，`BACKUP_CHECKPOINT`）
3. 使用 DuckDB 在线备份 `ATTACH` + `COPY FROM DATABASE` + `DETACH` 复制数据库到 `backups/db/` 目录（无需关闭数据库，避免 Windows 文件锁定）
4. 验证备份文件完整性
5. 清理超出 `MAX_BACKUPS`（默认 30 份）的旧备份

**管理面板操作**：
- 路径：管理中心 → 数据库备份
- 支持手动触发「立即优化并备份」
- 显示实时进度条（10 个阶段）
- 查看最近 20 条备份历史（状态/大小/耗时）

**配置项**：见 `config.py` 中 `BACKUP_*` 系列配置。

## 前端特性

### 磨砂玻璃效果（Glassmorphism）

- `backdrop-filter: blur(32px) saturate(220%) brightness(108%)`
- 低透明度 `rgba` 背景 + 24px 圆角
- 动态背景光球（CSS `@keyframes` 动画）

### 交互效果

| 效果 | 实现方式 |
|------|----------|
| 鼠标光晕跟随 | `requestAnimationFrame` 平滑插值，静止后自动停止 RAF |
| 按钮水波纹 | 点击时创建 `span` 元素，CSS `ripple` 动画 |
| 滚动淡入 | `IntersectionObserver` 监听可见性，从下往上淡入 |
| 平滑滚动 | 锚点链接 `scrollTo({ behavior: 'smooth' })` |
| 页面过渡 | `requestAnimationFrame` 控制 `.page-ready` 类切换 |

### 性能优化

- `overflow-x: clip` 替代 `hidden`（消除滚动回弹）
- `overscroll-behavior-y: none`（防止边界回弹）
- 尊重 `prefers-reduced-motion`（无障碍用户自动禁用动画）
- 触控设备降级光晕效果（`hover: none` 媒体查询）
- `IntersectionObserver` 触发后立即 `unobserve`（避免重复计算）

## 部署

### 方式一：CherryPy（内置 SSL 支持）

```bash
pip install -r requirements.txt

# HTTP 模式
python app.py

# HTTPS 模式
export ENABLE_SSL=1
python app.py
```

CherryPy 配置：`request_queue_size=100`，`numthreads=20`。

### 方式二：Nginx 反向代理

应用以 HTTP 模式运行，Nginx 处理 SSL：

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

### 异步架构

系统采用多线程异步执行技术，确保 Web 请求不被阻塞：

| 组件 | 文件 | 异步方式 |
|------|------|----------|
| 定时任务调度器 | `services/scheduler.py` | 后台线程扫描到期任务 + ThreadPoolExecutor 异步执行 |
| 日志写入器 | `services/logging/writer.py` | 队列 + 后台线程批量写入数据库 |
| 日志清理器 | `services/logging/cleaner.py` | 后台线程定期检查并清理超限日志 |
| IP 地理信息查询 | `services/ip.py` | 后台线程异步更新缓存，请求时返回缓存值 |
| 命令执行日志 | `services/cmd_runner.py` | 后台线程异步写入执行结果 |
| CPU 使用率 | `services/monitoring/cpu.py` | **后台线程定期采样（默认 2 秒）**，fork 安全（pid 检测重启采样线程），缓存 10 秒过期降级到阻塞采样 |
| 用户信息查询 | `core/auth.py` | 单次请求内缓存，避免重复 DB 查询 |
| 持久交互式终端 | `services/terminal/` | session-based shell 子进程 + 后台读取线程 + SSE 流式回流 |
| MiniScript 脚本执行 | `services/miniscript/` | 独立子进程 + 按 session 隔离状态 + SSE 流式回流 |

### 安全注意事项

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 定期清理 `access_logs` 表（管理后台支持一键清空，或配置自动清理）
5. 图形验证码采用服务端内存存储（`CaptchaService` 单例），答案不依赖 session，返回随机 `captcha_id` 供前端提交，校验后一次性删除防止重放攻击与 curl 绕过
6. Session Cookie 启用 `HttpOnly` 与 `SameSite=Lax` 安全选项，防止 JS 读取与跨站请求伪造

## 更新日志

项目的版本变更历史详见 [docs/CHANGELOG.md](file:///workspace/docs/CHANGELOG.md)。

### 最近修复

**讨论区回复功能优化（分段加载 + 实时刷新）：**
- 发表回复窗口移至回复列表上方，优化交互流程
- 回复列表改为前端分页加载（JS 动态渲染），点击"加载更多"按钮分段加载
- 新增实时自动刷新功能（默认 5 秒间隔）：只获取比当前已加载最大 ID 更新的回复，不重复加载已存在的回复
- 刷新间隔和每页数量可通过管理后台在线编辑（`DISCUSSION_REFRESH_INTERVAL`、`REPLIES_PER_PAGE`）
- 新增 API 端点：`GET /discussion/<id>/api/replies`（分页获取）和 `GET /discussion/<id>/api/new-replies`（获取最新）
- 删除回复改为 AJAX 异步操作，无需刷新页面
- 性能优化：数据库查询仅返回必要字段，前端 `Set` 去重避免重复渲染

**指南编辑功能重构（独立页面 + 独立滚动）：**
- 将成员新建/编辑指南从弹窗模式改为独立页面（`/guides/create` 和 `/guides/<id>/edit`）
- 新增 `templates/guides/form.html`：独立的指南编辑表单页面，包含 Markdown 编辑器 + 实时预览 + flash 消息显示
- 修复 `templates/guides/index.html`：新建指南按钮改为页面跳转链接，修改按钮改为独立页面链接，移除旧弹窗相关代码
- 修复 `templates/admin_guides.html`：预览按钮改用 `data-*` 属性传递数据，避免 JSON 转义问题
- 修复 `templates/admin_guide_form.html` 和 `templates/guides/form.html`：编辑器和预览区域添加独立滚动（`max-height: 70vh` + `overflow-y: auto` + `min-height: 0`），工具栏和标题栏固定不滚动（`flex-shrink: 0`）
- 修复 `routes/guides/pages.py`：添加 `guide_create()` 和 `guide_edit()` 路由，支持成员提交新指南和编辑自己的指南
- 修复 `routes/guides/api.py`：移除旧 API 端点（`/api/guides/submit` 和 `/api/guides/<id>/edit-request`），统一使用页面路由

**注册页面验证码弹窗居中修复：**
- 修复 `templates/register.html`：使用绝对定位方式实现弹窗居中（`position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%)`），避免 `base.css` 中 `.pixel-card` 的 `content-visibility: auto` 和 `contain-intrinsic-size: 0 300px` 导致弹窗宽度为 0 的问题
- 弹窗使用内联样式定义磨砂玻璃效果，避免与全局 CSS 冲突

**修改邮箱群内验证码逻辑修复：**
- 修复 `routes/api/email_code.py`：群内验证码校验仅在 `purpose == '注册'` 时生效，修改邮箱场景不再要求群内验证码
- 修复 `templates/settings.html`：修改邮箱时发送验证码请求不携带 `verify_code` 字段

**日志服务包导入错误修复：**
- 修复 `services/logging/__init__.py`：将 `from .writer import log_writer, LogWriter` 修改为 `from .writer import log_writer, AsyncLogWriter`，与实际类名一致
- 修复 `services/logging/writer.py`：日志打印从 `[LogWriter]` 改为 `[AsyncLogWriter]`，保持命名一致性

**统一邮件 HTML 模板模块（消除重复代码 + 移动端适配）：**
- 新增 `services/email/templates.py`：集中构建所有邮件 HTML，提取公共组件（外层容器、高亮块、验证码块、次要提示），消除散落在 `services/email/code.py`、`routes/guides/api.py`、`routes/admin/guides.py` 三处的重复模板代码
- 三个对外构建函数：`verification_code()`（验证码邮件）、`guide_review_pending()`（新指南待审核）、`guide_review_result()`（审核结果通知）
- 顶部内联 `<style>` 含 `@media (max-width: 480px)` 媒体查询：移动端自适应缩小验证码字号（32px→26px）、字间距（8px→4px）、内边距，避免横向溢出
- 容器 `max-width: 480px` + `width: 100%` + `box-sizing: border-box`，适配任意屏幕宽度
- 所有用户输入内容（验证码、指南标题、用户名、拒绝原因）经 `html.escape()` 转义，防止 XSS 注入

**统一网页弹窗系统（替换浏览器原生弹窗）：**
- 新增 `CustomModal` 弹窗组件（放大居中动画 + 触发元素位置感知）与 `Toast` 提示组件（四种类型），位于 `static/js/base.js`
- `base.js` 新增 `initCustomConfirm` 拦截器：自动将 `form[onsubmit*="confirm("]` 与 `a[onclick*="confirm("]` 替换为自定义弹窗，统一磨砂玻璃风格
- `base.js` 新增附件上传进度条（XHR + `progress` 事件），上传时显示百分比与状态
- `templates/admin_db_backup.html`：脚本块内调用的 `confirm()` 手动替换为 `CustomModal.confirm()`，与全站弹窗风格一致
- 所有页面已不再使用浏览器原生 `alert`/`confirm`，统一使用磨砂玻璃风格的网页弹窗

**前端移动端彻底适配：**
- `templates/admin_settings.html`：内联固定宽度输入框改为响应式 `w-full sm:w-48` / `w-full sm:w-32`，设置项行布局在移动端纵向堆叠（`flex flex-col sm:flex-row`）
- `templates/admin_logs.html`：工具栏改为移动端纵向布局 + 操作行 `flex-wrap`
- 多处页面 H1 标题改为响应式变体（`text-xl sm:text-2xl` / `text-2xl sm:text-3xl`）
- `templates/admin.html`：统计卡片数字改为 `text-xl sm:text-2xl break-all`，防止大数字溢出
- `templates/performance.html`：系统信息卡片在小屏单列显示（`grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`）
- `templates/docs.html` / `templates/guides/detail.html`：Markdown 表格添加 `display: block; overflow-x: auto;`，移动端可横向滚动
- `templates/register.html` / `templates/login.html`：卡片容器响应式边距与内边距（`mx-4 sm:mx-6`、`p-5 sm:p-8`）
- `templates/manage_mod_intros.html` / `templates/community.html`：长文本行添加 `truncate` + `min-w-0` + `flex-shrink-0`，避免按钮被挤出可视区

**验证码服务内存清理机制：**
- `services/captcha.py` `CaptchaService`：新增后台清理线程（每 60 秒清理过期验证码），避免内存泄漏
- `services/email/code.py` `EmailCodeService`：新增后台清理线程（每 5 分钟清理过期验证码），避免内存泄漏
- 两个服务的 docstring 完善安全特性说明（服务端内存存储、一次性删除防重放、过期时间、后台清理）

**验证码安全性增强（防止 curl 等工具绕过）：**
- `services/captcha.py`：新增 `CaptchaService` 单例类，验证码答案改用服务端内存存储（`{captcha_id: {answer, expire, created_at}}`），不再依赖 session；`verify()` 校验后一次性删除防止重放攻击；线程锁保证线程安全；过期时间 300 秒
- `services/captcha.py`：扩大答案空间，数学题从 1+1~10+10（答案 2-20，仅 19 种）改为两位数运算 a∈[10,99] + b∈[10,99]（答案 20-198，179 种），防止暴力枚举
- `services/captcha.py`：`verify_captcha` 函数增加时间戳校验参数 `created_at`，超过 300 秒视为过期
- `routes/api/captcha.py`：生成接口改用 `CaptchaService`，返回 `{success, image, captcha_id}`
- `routes/api/email_code.py`、`routes/main.py`（注册/登录）、`routes/guides/api.py`：验证码校验改用 `captcha_service.verify(captcha_id, user_input)`，从请求中获取 `captcha_id`
- 前端模板（register.html、login.html、settings.html、guides/index.html）：验证码图片加载后保存返回的 `captcha_id`，表单/请求中携带 `captcha_id` 字段提交
- `app.py`：添加 Session Cookie 安全选项 `SESSION_COOKIE_HTTPONLY=True` 与 `SESSION_COOKIE_SAMESITE='Lax'`

**邮件功能与稳定性修复：**
- 修复 yagmail SMTP 连接参数错误：移除 `smtp_set_debug_level` 参数，解决 `SMTP_SSL.__init__() got an unexpected keyword argument` 错误
- 邮箱验证码发送前增加图形验证码校验，防止恶意刷短信
- 注册页面和设置页面的邮箱验证码发送按钮增加图形验证码，发送失败时自动刷新图形验证码
- 修复 DuckDB WAL 文件损坏导致启动失败：自动检测并删除损坏的 WAL 文件，自动重试连接
- 优化多进程子进程检测函数，移除冗余代码

**修复 MiniScript 脚本编辑器输出重复问题：**
- `static/js/cmd/terminal-core.js`：`TerminalBuffer._finalizeCurrentLine()` 在换行时不再调用 `_flushLine()` 创建新的 div，而是直接移除 `.term-current-line` 类，将已渲染的当前行转为 finalized 行，避免同一行内容被重复输出两次
- `templates/admin_cmd_editor.html`：更新 `terminal-core.js` 缓存版本号 `v=2`，强制浏览器加载修复后的文件

**终端与 MiniScript 架构重构（稳定性提升）：**
- 前端提取 `static/js/cmd/terminal-core.js`：统一 ANSI 解析、SSE 连接管理、命令历史、输入发送，供终端弹窗和编辑器内嵌终端复用，消除重复代码
- 后端拆分 `services/terminal/` 包：`TerminalSession` 封装单个持久 shell 会话的生命周期与 IO，`TerminalManager` 按用户 session 隔离管理多个 shell 进程
- MiniScript 改为 session-based 状态管理：`services/miniscript/session.py` 的 `ScriptSessionManager` 按 Flask session 隔离执行器与 prompt/confirm 响应，彻底解决多用户/多 worker 环境下响应串扰问题
- 路由层瘦身：`routes/cmd/terminal.py` 与 `routes/cmd/script.py` 仅负责 HTTP/SSE 协议转换，所有子进程状态管理下沉到服务层

**跨平台子进程基础设施（统一迁移到 `core/`）：**
- 新增 `core/process_utils.py`：跨平台编码解码（UTF-8/GBK/CP936/GB18030/MBCS）、无缓冲环境变量、`run_process` 统一封装
- 新增 `core/process_manager.py`：统一处理 Windows `CREATE_NO_WINDOW` / `CREATE_NEW_PROCESS_GROUP` 与 Unix `setsid`、进程组 SIGTERM/SIGKILL、Windows `CTRL_BREAK_EVENT` 进程组信号、阶梯式终止
- 新增 `core/shell.py`：自动检测 Windows cmd/PowerShell 与 Unix bash/sh，构造统一环境变量与初始化命令（如 `chcp 65001`、`TERM=xterm-256color`）
- 删除已废弃的 `utils/process.py` 与 `utils/__init__.py`，所有子进程调用统一走 `core/process_utils.py` 与 `core/process_manager.py`

**终端与编码修复：**
- 修复 `print`/`echo` 输出不实时问题：设置 `PYTHONUNBUFFERED=1` 禁用 Python 输出缓冲，后端分块（4096字节）读取子进程输出
- 修复快捷命令无输出问题：实现命令队列 `pendingInputQueue`，SSE 连接建立后自动发送缓存命令，移除不安全的 `setTimeout` 延迟
- 修复 Windows CMD 中文乱码：Windows 下自动执行 `chcp 65001` 切换到 UTF-8 代码页；统一跨平台编码解码（UTF-8/GBK/CP936/GB18030 多编码回退）
- 修复 ANSI 颜色不显示：实现完整 ANSI SGR 解析器，支持 16 色、256 色、真彩色 RGB，支持加粗/斜体/下划线/闪烁等样式
- 修复 `\r\n` (CRLF) 序列导致行内容丢失问题：添加 `pendingCr` 标记，回车后遇到换行时保留行内容

**DuckDB 多进程并发修复：**
- 彻底修复 Windows `multiprocessing spawn` 模式下子进程重新导入 `app.py` 导致的 DuckDB 文件锁定错误
- 多层防护机制：
  1. 父进程启动子进程前临时设置 `_BH_CHILD_PROCESS=1` 环境变量，子进程继承该变量（最早检测点）
  2. `app.py` 在所有导入前检测环境变量、`__name__`、`sys.argv` 特征判断子进程
  3. `connection.py` 的 `get_db()` 在连接数据库前再次检测子进程并抛出保护性异常
  4. 子进程入口函数 `run_script()` 中再次设置环境变量作为双重保险
- 默认管理员创建逻辑修复：仅当系统中无任何管理员时创建默认账户 `admin/admin1324`，删除管理员后重启不会自动重建

**默认账户：**
- 管理员用户名：`admin`
- 管理员密码：`admin1324`

**新增功能：公开文件/目录管理**
- 管理员可在后台控制面板「公开文件管理」中配置将本地文件或目录对外公开访问
- 支持**相对路径**（以项目根目录为基准）：如 `sw.js`、`verify`
- 支持**绝对路径**（任意位置）：如 `/opt/files`、`/home/user/docs`、`C:\Users\Public\docs`
- 支持单文件公开：例如将 `sw.js` 映射到 `http://域名/sw.js`
- 支持目录公开：例如将 `verify` 映射到 `http://域名/verify`，目录下所有文件自动可访问
- 目录自动首页：访问公开目录根路径时自动返回 `index.html` 或 `index.htm`
- 安全防护：
  - 禁止路径包含 `..` 防止目录遍历攻击
  - 禁止公开 `core`、`services`、`routes`、`templates` 等源码目录
  - 禁止访问 `.env`、`config.py`、`site.duckdb` 等敏感文件
  - 禁止访问 `/etc`、`/proc`、`/dev`、`/boot`、`/root` 等系统敏感目录
  - 禁止访问 Windows 系统目录（`C:\Windows`、`System32`、`Program Files` 等）
  - 相对路径严格限制在项目根目录内
- MIME类型自动识别：正确返回 JS、CSS、HTML、JSON、图片等文件类型
- 支持启用/禁用单个公开路径，无需删除即可临时关闭访问

**数据库备份修复（彻底解决 Windows 文件锁定问题）**
- 修复手动/自动备份时 `[WinError 32] 另一个程序正在使用此文件，进程无法访问` 错误
- 将 `shutil.copy2` 文件复制替换为 **DuckDB 在线备份**：`ATTACH` + `COPY FROM DATABASE` + `DETACH`
- 备份过程中数据库无需关闭，不影响正常读写，彻底解决 Windows 文件锁冲突
- 自动动态获取当前数据库名（如 `site`），避免硬编码 `main` 导致的兼容性问题
- 备份失败时自动清理残留临时文件

**征集附件（恢复简单机制）**
- 支持单次回复上传多个附件，后端使用 `request.files.getlist('attachments')` 遍历保存
- 支持多次点击“添加附件”追加文件：前端使用 `DataTransfer` 累积历次选择的文件，避免后一次选择覆盖前一次
- 附件以 JSON 文件名数组形式存储在 `board_replies.attachment`，保持与旧版一致
- 前端选择文件后实时显示文件名列表，修复了内联 `onchange` 中 `"` 转义错误导致按钮文本显示为 JavaScript 代码碎片的问题
- 不再做文件类型/大小/数量白名单校验，恢复为简单上传机制

**修复 Windows 终端输出重复问题**
- `services/terminal/session.py`：`read_pending_output` 增加 `caller_generation` 参数，旧 SSE 连接在 generation 切换后不再消费输出队列，避免同一段输出被多个连接重复发送
- `services/terminal/session.py`：`next_generation()` 非首次切换时清空旧输出队列，防止重连时残留输出被新连接重复显示；首次连接保留会话初始化输出
- `routes/cmd/terminal.py`：SSE 生成器将当前 generation 传入 `read_pending_output`，实现代际一致性校验
- `static/js/cmd/terminal-core.js`：`SseTerminal` 新增 `_connecting` 锁，防止并发调用 `connect()` 产生多个 EventSource 连接
- `core/shell.py`：Windows cmd 启动参数改为 `cmd.exe /q /k`，关闭命令回显，减少命令被前后端重复渲染的概率

