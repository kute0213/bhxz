# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票、留言板（多附件上传）、模组介绍、管理后台、服务器性能监控等功能。

## 项目结构

```
/workspace
├── app.py                        # 应用入口：Flask 实例、蓝图注册、CherryPy 服务器（支持 SSL）
├── config.py                     # 全局配置（数据库路径、上传限制、密钥、日志上限、调度器、备份）
├── requirements.txt              # Python 依赖
├── migrate_sqlite_to_duckdb.py   # 一次性迁移脚本：SQLite → DuckDB（用完可删）
│
├── core/                         # 核心基础设施
│   ├── __init__.py
│   ├── database.py               #   DuckDB 数据库层（兼容 sqlite3 接口：Row/lastrowid/executescript）
│   ├── auth.py                   #   认证模块（login_required / admin_required 装饰器、当前用户，含请求内缓存）
│   └── middleware.py             #   请求中间件（异步访问日志记录，不阻塞请求）
│
├── services/                     # 业务服务（含异步后台线程）
│   ├── __init__.py
│   ├── monitoring.py             #   系统监控（CPU 使用率/温度、内存、运行时间，跨平台）
│   ├── ip.py                     #   IP 工具（真实 IP 解析、异步地理信息查询）
│   ├── cmd_runner.py             #   命令执行服务（SSE 流式 + 同步执行 + 异步日志记录）
│   ├── scheduler.py              #   定时任务调度引擎（后台线程 + ThreadPoolExecutor 异步执行）
│   ├── log_cleaner.py            #   日志自动清除服务（后台线程定期清理超限记录）
│   ├── log_writer.py             #   异步日志写入器（队列 + 后台线程批量写入）
│   ├── backup_manager.py         #   数据库备份管理器（CHECKPOINT + 文件复制 + 旧备份清理）
│   └── backup_scheduler.py       #   每日定时备份调度器（默认凌晨 3:00）
│
├── routes/                       # 路由控制器（Flask Blueprint）
│   ├── __init__.py
│   ├── main.py                   #   页面路由：首页、登录/注册、用户设置、性能监控页
│   ├── community.py              #   社区路由：投票 CRUD、留言板 CRUD、多附件上传
│   ├── admin.py                  #   管理路由：用户管理、日志查看、模组介绍管理、数据库备份
│   ├── cmd.py                    #   CMD 控制台路由：实时命令执行 + 一键命令管理
│   ├── scheduled.py              #   定时任务路由：任务 CRUD、启停、触发、执行日志
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
│   ├── admin_db_backup.html      #   数据库优化备份页面（进度条 + 备份历史）
│   └── 403.html / 404.html       #   错误页
│
├── static/                       # 静态资源
│   ├── css/style.css             #   主样式（磨砂玻璃、动画、响应式）
│   └── js/
│       ├── main.js               #     全局交互（滚动动画、鼠标光晕、按钮反馈）
│       └── cmd/                  #     CMD 控制台模块（7 个文件，职责清晰）
│           ├── modal.js          #       页内弹窗系统（替代原生 alert/prompt/confirm）
│           ├── script.js         #       MiniScript 解释器（带行号追踪错误）
│           ├── terminal.js       #       终端弹窗（SSE 流式输出 + 拖拽 + 动画 + 固定尺寸滚动）
│           ├── presets.js        #       快捷命令管理（增删改查）
│           ├── editor.js         #       专业脚本编辑器（Monaco：高亮/补全/诊断）
│           ├── scheduled.js      #       定时任务管理（任务列表/创建/编辑/日志）
│           └── main.js           #       主入口（整合各模块）
│
├── docs/                         # Markdown 文档（通过 /docs 页面渲染）
│   ├── README.md                 #   项目说明（README 副本）
│   └── cmd-guide.md              #   CMD 控制台使用说明
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
| **服务** | `services/` | 系统监控、IP 解析 — 可被任意路由调用 |
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

### config.py

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

### CMD 控制台（管理员）

后端接口位于 [routes/cmd.py](file:///workspace/routes/cmd.py)，前端代码位于 [static/js/cmd/](file:///workspace/static/js/cmd/)，共 5 个模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| 脚本解释器 | [script.js](file:///workspace/static/js/cmd/script.js) | MiniScript 语言：词法分析 + 递归下降解析 + 解释执行 + 行号追踪错误 |
| 终端弹窗 | [terminal.js](file:///workspace/static/js/cmd/terminal.js) | SSE 流式输出、命令历史（↑↓）、清屏快捷键 |
| 快捷命令 | [presets.js](file:///workspace/static/js/cmd/presets.js) | 增删改查一键命令（CMD / 脚本两种类型） |
| 脚本编辑器 | [editor.js](file:///workspace/static/js/cmd/editor.js) | 专业脚本编辑器（Monaco）：高亮、补全、诊断、批量替换 |
| 主入口 | [main.js](file:///workspace/static/js/cmd/main.js) | 整合各模块、脚本运行逻辑、定时器生命周期管理 |

**页面布局**：快捷命令在上（网格卡片），实时终端为弹窗模式，独立的「脚本编辑器」页面提供专业代码编写环境。

#### 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/cmd` | CMD 控制台页面 |
| GET | `/admin/cmd/editor` | **专业脚本编辑器页面**（支持 `?edit=<id>` 编辑现有命令） |
| GET | `/admin/cmd/commands` | 获取一键命令列表（JSON） |
| POST | `/admin/cmd/commands` | 新增一键命令 |
| PUT / POST | `/admin/cmd/commands/<id>` | 更新一键命令 |
| POST / DELETE | `/admin/cmd/commands/<id>/delete` | 删除一键命令 |
| POST | `/admin/cmd/run` | 同步执行命令（一次性返回全部输出） |
| GET / POST | `/admin/cmd/run-stream` | **实时流式执行**（SSE，逐行返回输出） |
| POST | `/admin/cmd/run-preset/<id>` | 执行一键命令 |

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

### MiniScript 前端脚本语言

类 Python 语法的极简脚本语言，全部在浏览器内解释执行，运算在前端，CMD 命令通过 API 发送到服务端。

**语法特性**：
- 变量赋值：`x = 10`、`name = "hello"`
- 算术运算：`+ - * / % ( )`，支持字符串拼接
- 比较运算：`== != > < >= <=`
- 逻辑运算：`&& || !`（短路求值）
- 条件判断：`if cond:` / `elif cond:` / `else:`，支持缩进块和内联写法
- 循环：`while cond:` / `for var in iterable:`，支持 `break` / `continue`
- 列表：`[1, 2, 3]` 字面量、`list[0]` 索引、`list[-1]` 负索引、`+` 拼接
- 注释：`# 行注释`

**错误信息**：所有错误（语法错误与运行时错误）都包含**具体出错的行号和列号**，格式统一为 `第 N 行：错误描述` 或 `第 N 行:M列：错误描述`。在脚本编辑器中以红色波浪线实时标注错误位置。

**循环保护**：while/for 最大 100,000 次迭代，每 100 次让出 UI 执行权；脚本最大执行 30 秒，超时自动中止；定时器代码在独立上下文执行，终端关闭/新脚本启动时自动清理所有定时器；手动中止按钮支持随时停止脚本。

### 专业脚本编辑器

独立页面 `/admin/cmd/editor`，基于 Monaco Editor（VS Code 核心编辑器）实现，提供专业代码编写环境：

- **语法高亮**：自定义 `miniscript` 语言 Monarch 词法规则，关键字/字符串/数字/注释/运算符不同颜色
- **代码补全**：输入时自动弹出关键字与内置函数列表，含函数签名和文档
- **实时错误诊断**：输入时调用 tokenizer + parser，错误以红色波浪线标注，状态栏显示错误数量
- **悬浮提示**：鼠标悬停在内置函数上显示签名和用法
- **行号标注**：行号栏，当前行高亮
- **查找/批量替换**：`Ctrl+F` 查找、`Ctrl+H` 替换、`Ctrl+Shift+L` 选中所有匹配项（多光标批量编辑）
- **多光标编辑**、代码折叠、括号匹配着色、Minimap、自动缩进
- **测试运行**：`Ctrl+Enter` 运行（无需保存），运行时按钮变红色「中止」
- **保存为快捷命令**：`Ctrl+S` 保存到数据库，可在 CMD 控制台重复运行
- **示例代码**：内置 6 个示例（Hello World、循环列表、条件判断、定时器、索引切片、执行 CMD）

**内置函数**：

| 函数 | 说明 |
|------|------|
| `alert(title, message)` | 弹窗提示（页内弹窗，非原生） |
| `prompt(title, message)` | 弹窗获取用户输入，返回字符串 |
| `confirm(title, message)` | 确认弹窗，返回 true/false |
| `cmd(command)` | **流式**执行服务端 CMD，输出到终端，返回完整输出字符串 |
| `cmd_sync(command)` | 同步执行服务端 CMD，一次性返回输出 |
| `echo(message)` | 输出到终端（紫色脚本标识） |
| `print(...args)` | 输出到控制台（支持列表自动格式化） |
| `regex(str, pattern)` | 正则匹配，返回匹配数组或 null |
| `regex_test(str, pattern)` | 正则测试，返回 true/false |
| `sleep(ms)` | 等待指定毫秒 |
| `range(start, end, step)` | 生成整数范围（用于 for 循环） |
| `set_timeout(code, ms)` | 延迟执行代码（一次性） |
| `set_interval(code, ms)` | 定时重复执行代码 |
| `clear_timer(id)` | 取消定时器 |
| `append(list, ...items)` | 向列表追加元素 |
| `push(list, item)` | 追加元素，返回新长度 |
| `pop(list, index?)` | 弹出元素（默认末尾，支持负索引） |
| `slice(obj, start, end?)` | 切片（列表/字符串） |
| `join(list, sep?)` | 列表转字符串 |
| `reverse(list)` | 反转（返回新列表） |
| `sort(list)` | 排序（返回新列表） |
| `contains(obj, item)` | 是否包含元素 |
| `len(obj)` | 获取长度 |
| `parseInt(str)` / `parseFloat(str)` | 字符串转数字 |
| `str(val)` | 转字符串 |
| `now()` | 当前时间戳（秒） |

**示例脚本**：

```python
# 弹窗获取用户名
name = prompt('用户信息', '请输入你的名字：')

# 执行 CMD 并获取结果
result = cmd_sync('whoami')

# 弹窗显示
alert('结果', '你好, ' + name + '!\\n当前系统用户: ' + result)
```

**条件判断示例**：

```python
x = 15
if x > 20:
    echo("huge")
elif x > 10:
    echo("medium-large")
else:
    echo("small")
```

**循环示例**：

```python
# while 循环
i = 0
while i < 5:
    echo(str(i))
    i = i + 1

# for + range
for i in range(0, 10, 2):
    if i == 6:
        continue
    echo(str(i))
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
- `cmd-guide.md` — CMD 控制台详细使用说明

主页底部「关于官网」链接跳转至文档页面。


## 数据库

使用 **DuckDB**（高性能嵌入式 OLAP 数据库，单文件、支持列存、窗口函数），首次启动自动建表。

> 从 SQLite 迁移？运行 `python migrate_sqlite_to_duckdb.py` 即可将旧数据迁移到 DuckDB，迁移完成后可删除该脚本。

共 13 张表：

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
| `access_logs` | 访问日志 | 含 IP 国家/地区/城市/ISP，自动清理 |
| `scheduled_tasks` | 定时任务 | 支持间隔/每日/一次性三种模式 |
| `scheduled_task_logs` | 定时任务执行日志 | 外键 `task_id` 设空 |
| `cmd_run_logs` | CMD 命令执行日志 | — |
| `db_backups` | 数据库备份记录 | 备份状态/大小/耗时 |

所有外键均启用 `enable_foreign_keys` 和 `ON DELETE CASCADE`。

### DuckDB 兼容层说明

为了最小化代码改动，[core/database.py](file:///workspace/core/database.py) 对 DuckDB 做了 sqlite3 兼容封装：

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

### 定时任务

定时任务功能允许管理员设置定时自动执行的 CMD 命令，支持三种调度模式：

| 模式 | 说明 | 示例 |
|------|------|------|
| 间隔执行 | 每隔指定秒数执行 | 每 3600 秒备份一次 |
| 每日定时 | 每天在指定时间执行 | 每天 03:00 清理日志 |
| 一次性执行 | 在指定时间执行一次后自动禁用 | 2024-12-25 00:00 执行任务 |

- 访问路径：`/admin/cmd/scheduled`
- 所有任务通过后台线程异步执行，不阻塞 Web 请求
- 执行结果（输出、退出码、耗时）自动记录到 `scheduled_task_logs` 表
- 支持手动触发、启用/禁用、编辑、删除
- 支持查看单个任务或全部任务的执行日志

### 日志自动清除

系统自动管理日志表的大小，超出上限时自动删除最旧的记录：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MAX_ACCESS_LOGS` | 500 | 访问日志最大条数 |
| `MAX_CMD_LOGS` | 1000 | CMD 命令执行日志最大条数 |
| `MAX_TASK_LOGS` | 2000 | 定时任务执行日志最大条数 |
| `LOG_CLEANUP_INTERVAL` | 300 | 日志清理检查间隔（秒） |

- 后台线程定期检查各日志表，超限时自动删除最旧记录
- 在 `config.py` 中修改对应配置即可调整上限

### 异步架构

系统采用多线程异步执行技术，确保 Web 请求不被阻塞：

| 组件 | 文件 | 异步方式 |
|------|------|----------|
| 定时任务调度器 | `services/scheduler.py` | 后台线程扫描到期任务 + ThreadPoolExecutor 异步执行 |
| 日志写入器 | `services/log_writer.py` | 队列 + 后台线程批量写入数据库 |
| 日志清理器 | `services/log_cleaner.py` | 后台线程定期检查并清理超限日志 |
| IP 地理信息查询 | `services/ip.py` | 后台线程异步更新缓存，请求时返回缓存值 |
| 命令执行日志 | `services/cmd_runner.py` | 后台线程异步写入执行结果 |
| CPU 使用率 | `services/monitoring.py` | 非阻塞模式 `cpu_percent(interval=None)` |
| 用户信息查询 | `core/auth.py` | 单次请求内缓存，避免重复 DB 查询 |

### 安全注意事项

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 定期清理 `access_logs` 表（管理后台支持一键清空，或配置自动清理）

## 更新日志

### 2024-XX-XX

**新增：**
- 定时任务功能：支持间隔执行、每日定时、一次性执行三种调度模式
- 日志自动清除：访问日志、CMD 日志、任务日志超限自动删除，上限可在 `config.py` 配置
- 异步架构改造：日志写入、IP 查询、命令执行日志全部改为异步多线程，不阻塞 Web 请求
- 用户信息查询优化：单次请求内缓存，避免 middleware 和路由重复 DB 查询
- CPU 使用率改为非阻塞模式

**修复：**
- 修复弹窗（alert/prompt/confirm）按钮点击无反应的问题
  - 移除了遮挡按钮的 `escapeLayer` 透明层，改为在 `document` 级别监听 ESC 键
  - 修复弹窗显隐控制：内联样式 `display:flex` 优先级高于 Tailwind `.hidden` 类，改用 `style.display` 直接控制
  - `close()` 函数添加 300ms 超时 fallback，确保即使 CSS 动画未定义也能正常关闭弹窗
  - 编辑器页面补充弹窗动画 CSS 样式
