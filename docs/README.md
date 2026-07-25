# 滨海小镇 - Minecraft 服务器社区网站

基于 Flask 的 Minecraft 服务器社区门户，采用磨砂玻璃（Glassmorphism）设计风格。提供用户系统、社区投票、留言板（多附件上传）、模组介绍、管理后台、服务器性能监控等功能。

## 项目结构

```
/workspace
├── app.py                        # 应用入口：Flask 实例、蓝图注册、CherryPy 服务器（支持 SSL）
├── config.py                     # 全局配置（数据库路径、上传限制、密钥、注册验证码）
├── requirements.txt              # Python 依赖
│
├── core/                         # 核心基础设施
│   ├── __init__.py
│   ├── database.py               #   数据库连接与初始化（建表、迁移、默认数据）
│   ├── auth.py                   #   认证模块（login_required / admin_required 装饰器、当前用户）
│   └── middleware.py             #   请求中间件（访问日志记录，含 IP 地理信息）
│
├── services/                     # 业务服务
│   ├── __init__.py
│   ├── monitoring.py             #   系统监控（CPU 使用率/温度、内存、运行时间，跨平台）
│   └── ip.py                     #   IP 工具（真实 IP 解析、ip-api 地理信息查询）
│
├── routes/                       # 路由控制器（Flask Blueprint）
│   ├── __init__.py
│   ├── main.py                   #   页面路由：首页、登录/注册、用户设置、性能监控页
│   ├── community.py              #   社区路由：投票 CRUD、留言板 CRUD、多附件上传
│   ├── admin.py                  #   管理路由：用户管理、日志查看、模组介绍管理
│   ├── cmd.py                    #   CMD 控制台路由：实时命令执行 + 一键命令管理
│   ├── docs.py                   #   文档路由：Markdown 文档列表 + 内容 API
│   └── api/                      #   API 接口（按功能模块拆分）
│       ├── __init__.py
│       ├── monitoring.py         #     /api/performance  性能数据
│       ├── stats.py              #     /api/stats         网站统计
│       ├── polls.py              #     /api/polls       投票数据
│       └── admin.py              #     /api/admin/logs    访问日志（管理员）
│
├── templates/                    # Jinja2 模板（16 个页面）
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
│   └── 403.html / 404.html       #   错误页
│
├── static/                       # 静态资源
│   ├── css/style.css             #   主样式（磨砂玻璃、动画、响应式）
│   └── js/
│       ├── main.js               #     全局交互（滚动动画、鼠标光晕、按钮反馈）
│       └── cmd/                  #     CMD 控制台模块（5 个文件，职责清晰）
│           ├── modal.js          #       页内弹窗系统（替代原生 alert/prompt/confirm）
│           ├── script.js         #       MiniScript 解释器（前端脚本语言）
│           ├── terminal.js       #       终端弹窗（SSE 流式输出 + 拖拽 + 动画 + 固定尺寸滚动）
│           ├── presets.js        #       快捷命令管理（增删改查）
│           └── main.js           #       主入口（整合各模块）
│
├── docs/                         # Markdown 文档（通过 /docs 页面渲染）
│   ├── README.md                 #   项目说明（README 副本）
│   └── cmd-guide.md              #   CMD 控制台使用说明
│
├── uploads/                      # 用户上传文件（自动创建）
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
| `DB_PATH` | SQLite 数据库路径 | `./site.db` |
| `UPLOAD_DIR` | 上传文件目录 | `./uploads` |
| `MAX_CONTENT_LENGTH` | 最大上传大小 | 100 MB |
| `SECRET_KEY` | Flask Session 密钥 | `mc_server_site_random_secret_key_2024` |
| `REGISTER_VERIFY_CODE` | 注册验证码 | `binhai_xz` |
| `MAX_ACCESS_LOGS` | 访问日志最大保留条数，超出自动删除最旧记录 | `500`（10 × 50） |

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

后端接口位于 [routes/cmd.py](file:///workspace/routes/cmd.py)，前端代码位于 [static/js/cmd/](file:///workspace/static/js/cmd/)，共 4 个模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| 脚本解释器 | [script.js](file:///workspace/static/js/cmd/script.js) | MiniScript 语言：词法分析 + 递归下降解析 + 解释执行 |
| 终端弹窗 | [terminal.js](file:///workspace/static/js/cmd/terminal.js) | SSE 流式输出、命令历史（↑↓）、清屏快捷键 |
| 快捷命令 | [presets.js](file:///workspace/static/js/cmd/presets.js) | 增删改查一键命令（CMD / 脚本两种类型） |
| 主入口 | [main.js](file:///workspace/static/js/cmd/main.js) | 整合各模块、脚本编辑器运行逻辑 |

**页面布局**：快捷命令在上（网格卡片），脚本编辑器在下，实时终端为弹窗模式（点击"实时终端"按钮打开）。

#### 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/cmd` | CMD 控制台页面 |
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
- 注释：`# 行注释`

**内置函数**：

| 函数 | 说明 |
|------|------|
| `alert(title, message)` | 弹窗提示（页内弹窗，非原生） |
| `prompt(title, message)` | 弹窗获取用户输入，返回字符串 |
| `confirm(title, message)` | 确认弹窗，返回 true/false |
| `cmd(command)` | **流式**执行服务端 CMD，输出到终端，返回完整输出字符串 |
| `cmd_sync(command)` | 同步执行服务端 CMD，一次性返回输出 |
| `echo(message)` | 输出到终端（紫色脚本标识） |
| `print(...args)` | 输出到控制台 |
| `regex(str, pattern)` | 正则匹配，返回匹配数组或 null |
| `regex_test(str, pattern)` | 正则测试，返回 true/false |
| `sleep(ms)` | 等待指定毫秒 |
| `range(start, end, step)` | 生成整数范围（用于 for 循环） |
| `set_timeout(code, ms)` | 延迟执行代码（一次性） |
| `set_interval(code, ms)` | 定时重复执行代码 |
| `clear_timer(id)` | 取消定时器 |
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

使用 SQLite，首次启动自动建表。共 8 张表：

| 表名 | 说明 | 关键约束 |
|------|------|----------|
| `users` | 用户 | `username` 唯一 |
| `polls` | 投票 | — |
| `poll_options` | 投票选项 | 外键 `poll_id` 级联删除 |
| `poll_votes` | 投票记录 | 唯一约束 `(poll_id, user_id, option_id)` 防重复投票 |
| `board_topics` | 留言板主题 | 外键 `user_id` 级联删除 |
| `board_replies` | 留言板回复 | 外键 `topic_id` 级联删除，`attachment` 存 JSON 数组 |
| `mod_intros` | 模组介绍 | — |
| `cmd_commands` | 一键命令 | 名称 / 命令 / 描述 / 排序 |
| `access_logs` | 访问日志 | 含 IP 国家/地区/城市/ISP，自动清理 |

所有外键均启用 `PRAGMA foreign_keys = ON` 和 `ON DELETE CASCADE`。

### 访问日志自动清理

访问日志表会持续增长，为避免数据库膨胀，启用自动清理机制：

- **阈值**：由 `config.py` 的 `MAX_ACCESS_LOGS`（默认 500 条）控制
- **触发频率**：每写入 10 条日志才检查一次总量，避免每次请求都查询数据库
- **清理方式**：超出阈值时，删除最旧的记录（按 `id ASC` 排序），仅删除超出部分
- **实现位置**：[core/middleware.py](file:///workspace/core/middleware.py) 的 `log_access()` 函数

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

### 安全注意事项

1. 修改 `config.py` 中的 `SECRET_KEY` 为随机强密钥
2. 修改默认管理员密码
3. 生产环境启用 HTTPS
4. 定期清理 `access_logs` 表（管理后台支持一键清空）
