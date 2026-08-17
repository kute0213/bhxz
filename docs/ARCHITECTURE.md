# 架构说明

> 本文档描述项目的**架构分层、目录结构与技术栈**。代码编写与部署发布规范见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 架构分层

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

## 目录结构

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

## 技术栈

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

## 异步架构

| 组件 | 异步方式 |
|------|----------|
| 定时任务调度器 | 后台线程 + ThreadPoolExecutor |
| 日志写入器 | 队列 + 后台线程批量写入 |
| 日志清理器 | 后台线程定期检查 |
| IP 地理信息 | 后台线程异步更新缓存 |
| CPU 监控 | 后台线程定期采样（2 秒） |
| 交互式终端 | session-based shell + 后台读取线程 + SSE |
| MiniScript | 独立子进程 + SSE 流式回流 |

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

## 一键更新机制

用户通过管理后台的「一键更新」功能，从 GitHub 获取最新代码：

1. 系统自动检测最快代理，下载 GitHub 仓库的 ZIP 压缩包
2. 解压后同步到本地（跳过受保护文件：数据库、配置、上传文件等）
3. 自动运行 `scripts/build/build_static.py` 构建静态资源
4. 自动重启服务器

> 实现详见 `services/updater.py`（通过 SSE 推送实时下载进度到前端）。

触发发布的三要素与其文档归属：
- **打包发布** → [DEVELOPMENT.md 构建与发布](DEVELOPMENT.md#构建与发布)
- **更新机制** → 本文档（架构设计）
- **更新规则** → [DEVELOPMENT.md 更新规则](DEVELOPMENT.md#更新规则)