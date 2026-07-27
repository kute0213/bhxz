# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票、留言板（多附件上传）、模组介绍、管理后台、服务器性能监控、CMD 控制台与 MiniScript 脚本引擎等功能。

## 项目结构

```
/workspace
├── app.py                        # 应用入口：Flask 实例、蓝图注册、CherryPy 服务器（支持 SSL）
├── config.py                     # 全局配置（数据库路径、上传限制、密钥、日志上限、调度器、备份）
├── requirements.txt              # Python 依赖
│
├── core/                         # 核心基础设施
│   ├── __init__.py
│   ├── db/                       #   DuckDB 数据库层（兼容 sqlite3 接口：Row/lastrowid/executescript）
│   │   ├── __init__.py           #     包入口，导出 get_db / init_db / DuckDBConnection 等
│   │   ├── connection.py         #     连接、游标、行对象封装 + get_db
│   │   └── schema.py             #     建表 SQL、迁移、默认数据 + init_db
│   ├── auth.py                   #   认证模块（login_required / admin_required 装饰器、当前用户，含请求内缓存）
│   └── middleware.py             #   请求中间件（异步访问日志记录，不阻塞请求）
│
├── services/                     # 业务服务（含异步后台线程）
│   ├── __init__.py
│   ├── monitoring/               #   系统监控（CPU 使用率/温度、内存、运行时间，跨平台）
│   │   ├── __init__.py           #     包入口，导出 get_cpu_usage / get_cpu_temperature / get_memory_info / get_system_info
│   │   ├── cpu.py                #     CPU 使用率与温度采集
│   │   ├── memory.py             #     内存信息采集
│   │   └── system.py             #     系统信息采集 + psutil 可用性检测
│   ├── ip.py                     #   IP 工具（真实 IP 解析、异步地理信息查询）
│   ├── cmd_runner.py             #   命令执行服务（SSE 流式 + 同步执行 + 异步日志记录）
│   ├── scheduler.py              #   定时任务调度引擎（后台线程 + ThreadPoolExecutor 异步执行）
│   ├── log_cleaner.py            #   日志自动清除服务（后台线程定期清理超限记录）
│   ├── log_writer.py             #   异步日志写入器（队列 + 后台线程批量写入）
│   ├── backup_manager.py         #   数据库备份管理器（CHECKPOINT + 文件复制 + 旧备份清理）
│   ├── backup_scheduler.py       #   每日定时备份调度器（默认凌晨 3:00，支持热重载）
│   ├── settings_manager.py       #   系统设置管理器（数据库存储 + 内存缓存，支持热重载）
│   ├── script_store.py           #   统一脚本存储服务（数据库存储，按名称自动排序）
│   └── miniscript/               #   MiniScript 后端执行引擎（独立子进程执行）
│       ├── __init__.py           #     包入口，导出 ScriptExecutor
│       ├── builtins.py           #     内置函数工厂（echo/cmd/file_*/db_*/alert/prompt/confirm）
│       ├── runner.py             #     子进程入口（exec 执行脚本 + 管道通信 + 超时看门狗）
│       └── executor.py           #     ScriptExecutor 类（multiprocessing + Pipe + abort）
│
├── routes/                       # 路由控制器（Flask Blueprint）
│   ├── __init__.py
│   ├── main.py                   #   页面路由：首页、登录/注册、用户设置、性能监控页
│   ├── community/                #   社区蓝图包：投票 CRUD、留言板 CRUD、多附件上传
│   │   ├── __init__.py           #     创建 community_bp，导入子模块注册路由
│   │   ├── pages.py              #     社区首页渲染 + 附件下载
│   │   ├── polls.py              #     投票创建/投票/删除/启停
│   │   ├── board.py              #     留言板主题/回复/删除（含附件管理）
│   │   └── helpers.py            #     _is_ajax / _respond 辅助函数
│   ├── admin/                    #   管理蓝图包：用户管理、日志、模组介绍、数据库备份、系统设置
│   │   ├── __init__.py           #     创建 admin_bp，导入子模块注册路由
│   │   ├── pages.py              #     管理后台首页 + 请求头调试
│   │   ├── users.py              #     用户列表/切换管理员/删除用户
│   │   ├── mod_intros.py         #     模组介绍 增/改/删
│   │   ├── logs.py               #     访问日志分页查看/清空
│   │   ├── settings.py           #     系统设置页面 + API（在线编辑配置，热重载）
│   │   └── backup.py             #     数据库备份页面/启动/进度/历史
│   ├── cmd/                      #   CMD 控制台蓝图包：实时命令执行 + 一键命令管理 + 脚本
│   │   ├── __init__.py           #     创建 cmd_bp，导入子模块注册路由
│   │   ├── pages.py              #     命令控制台首页 + 脚本编辑器页面
│   │   ├── commands.py           #     快捷命令 CRUD + 执行预设命令
│   │   ├── execution.py          #     Shell 命令同步执行 + SSE 流式执行
│   │   ├── script.py             #     MiniScript SSE 执行 + _admin_check 辅助函数
│   │   ├── scripts.py            #     统一脚本管理 CRUD（文件系统 + 数据库）
│   │   └── terminal.py           #     交互式终端（持久 shell 会话 + SSE 流式 + 命令输入）
│   ├── scheduled/                #   定时任务蓝图包：任务 CRUD、启停、触发、执行日志
│   │   ├── __init__.py           #     创建 scheduled_bp + _admin_check，导入子模块注册路由
│   │   ├── tasks.py              #     任务 CRUD/启停/触发/状态查询
│   │   └── logs.py               #     任务执行日志（单任务/全部/详情）
│   ├── docs.py                   #   文档路由：Markdown 文档列表 + 内容 API
│   └── api/                      #   API 接口（按功能模块拆分）
│       ├── __init__.py
│       ├── monitoring.py         #     /api/performance  性能数据
│       ├── stats.py              #     /api/stats         网站统计
│       ├── polls.py              #     /api/polls       投票数据
│       └── admin.py              #     /api/admin/logs    访问日志（管理员）
│
├── templates/                    # Jinja2 模板（18 个页面）
│   ├── base.html                 #   基础模板（全局样式、磨砂玻璃、导航栏、动画）
│   ├── index.html                #   首页（模组介绍卡片 + 关于官网链接）
│   ├── community.html            #   社区页（投票 + 留言板）
│   ├── login.html / register.html
│   ├── settings.html             #   用户设置（改用户名/密码/注销）
│   ├── performance.html          #   服务器性能监控
│   ├── docs.html                 #   文档中心（Markdown 渲染 + 侧边栏导航）
│   ├── admin.html                #   管理后台首页
│   ├── admin_users.html          #   用户管理
│   ├── admin_logs.html           #   访问日志
│   ├── admin_debug_headers.html  #   请求头调试
│   ├── manage_mod_intros.html    #   模组介绍管理
│   ├── admin_cmd.html            #   CMD 控制台
│   ├── admin_cmd_editor.html     #   脚本编辑器（专业代码编辑器页面）
│   ├── admin_cmd_scheduled.html  #   定时任务管理页面
│   ├── admin_settings.html       #   系统设置（在线编辑配置，支持重置，热重载）
│   ├── admin_db_backup.html      #   数据库优化备份页面（进度条 + 备份历史）
│   └── 403.html / 404.html       #   错误页
│
├── static/                       # 静态资源
│   ├── css/
│   │   ├── style.css             #   主样式（磨砂玻璃、动画、响应式）
│   │   └── base.css              #   base.html 提取的全局样式（导航栏、模态框、动画）
│   └── js/
│       ├── main.js               #     全局交互（滚动动画、鼠标光晕、按钮反馈）
│       ├── base.js               #     base.html 提取的全局脚本（导航、Toast、键盘快捷键）
│       └── cmd/                  #     CMD 控制台模块（9 个文件，职责清晰）
│           ├── modal.js          #       页内弹窗系统（替代原生 alert/prompt/confirm）
│           ├── terminal.js       #       终端弹窗（持久 shell 会话 + SSE 流式输出 + 拖拽 + 动画 + 断线重连）
│           ├── presets.js        #       快捷命令管理（增删改查，按 [脚本] 前缀区分类型）
│           ├── editor.js         #       脚本编辑器核心（Monaco 初始化、工具栏、可折叠输出面板、自动保存）
│           ├── editor-highlight.js  #    编辑器语法高亮 / 补全 / 主题 / 实时语法诊断（拆分自 editor.js）
│           ├── editor-sse.js     #       编辑器 SSE 执行 / 事件分发 / 强制终止（拆分自 editor.js）
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
| 性能监控 | [monitoring.py](file:///workspace/routes/api/monitoring.py) | `/api/performance` | CPU / 内存 / 温度 / 运行时间 |
| 网站统计 | [stats.py](file:///workspace/routes/api/stats.py) | `/api/stats` | 用户 / 投票 / 留言数 |
| 投票数据 | [polls.py](file:///workspace/routes/api/polls.py) | `/api/polls` | 投票列表 + 选项 + 投票状态 |
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

社区路由（投票、留言板）同时支持传统表单提交和 AJAX 请求：

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
| POST | `/board/create` | 创建留言板（管理员） |
| POST | `/board/<id>/reply` | 回复留言板（支持多附件） |
| POST | `/board/<id>/delete` | 删除留言板（管理员） |
| POST | `/board/reply/<id>/delete` | 删除回复（管理员或作者） |

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

## 数据库

使用 **DuckDB**（高性能嵌入式 OLAP 数据库，单文件、支持列存、窗口函数），首次启动自动建表。共 15 张表：

| 表名 | 说明 | 关键约束 |
|------|------|----------|
| `users` | 用户 | `username` 唯一 |
| `polls` | 投票 | — |
| `poll_options` | 投票选项 | 外键 `poll_id` 级联删除 |
| `poll_votes` | 投票记录 | 唯一约束 `(poll_id, user_id, option_id)` 防重复投票 |
| `board_topics` | 留言板主题 | 外键 `user_id` 级联删除 |
| `board_replies` | 留言板回复 | 外键 `topic_id` 级联删除，`attachment` 存 JSON 数组 |
| `mod_intros` | 模组介绍 | — |
| `cmd_commands` | 一键命令 | 名称 / 命令 / 描述 / 排序 / 类型 |
| `scripts` | **统一脚本表** | **name / description / content / script_type（数据库存储，无文件系统依赖）** |
| `access_logs` | 访问日志 | 含 IP 国家/地区/城市/ISP，自动清理 |
| `scheduled_tasks` | 定时任务 | 支持间隔/每日/一次性三种模式，`task_type` 强制为 shell，`command_id` 关联 `cmd_commands` 表（仅执行快捷命令） |
| `scheduled_task_logs` | 定时任务执行日志 | 外键 `task_id` 设空 |
| `cmd_run_logs` | CMD 命令执行日志 | — |
| `db_backups` | 数据库备份记录 | 备份状态/大小/耗时 |
| `settings` | **系统设置** | **key 唯一，存储用户自定义配置，支持热重载** |

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
- **实现位置**：[services/log_cleaner.py](file:///workspace/services/log_cleaner.py)

### 数据库备份与优化

每日凌晨 3:00（可配置）自动执行数据库优化与备份：

**备份流程**：
1. 清理过期日志（可选，`BACKUP_CLEAN_LOGS`）
2. 执行 `CHECKPOINT` 合并 WAL 到主文件（可选，`BACKUP_CHECKPOINT`）
3. 复制数据库文件到 `backups/db/` 目录
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
| 日志写入器 | `services/log_writer.py` | 队列 + 后台线程批量写入数据库 |
| 日志清理器 | `services/log_cleaner.py` | 后台线程定期检查并清理超限日志 |
| IP 地理信息查询 | `services/ip.py` | 后台线程异步更新缓存，请求时返回缓存值 |
| 命令执行日志 | `services/cmd_runner.py` | 后台线程异步写入执行结果 |
| CPU 使用率 | `services/monitoring/cpu.py` | **后台线程定期采样（默认 2 秒）**，fork 安全（pid 检测重启采样线程），缓存 10 秒过期降级到阻塞采样 |
| 用户信息查询 | `core/auth.py` | 单次请求内缓存，避免重复 DB 查询 |
| MiniScript 脚本执行 | `services/miniscript/` | 独立子进程 + SSE 流式回流 |

### 安全注意事项

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 定期清理 `access_logs` 表（管理后台支持一键清空，或配置自动清理）

## 更新日志

项目的版本变更历史详见 [docs/CHANGELOG.md](file:///workspace/docs/CHANGELOG.md)。
