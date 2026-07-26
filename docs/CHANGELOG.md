# 更新日志

本文件记录滨海小镇官网项目的所有重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

### 新增
- 脚本自动保存：编辑已有脚本时防抖 2 秒自动保存，工具栏四态状态指示器（已修改/保存中/已保存/保存失败）
- 可折叠输出面板：编辑器输出区支持展开/收起，折叠状态 localStorage 记忆
- 脚本文件系统：MiniScript 脚本从数据库移到 `scripts/` 目录，每个脚本一个独立 `.py` 文件，文件头注释存储名称和描述元数据
- 脚本管理服务（`services/script_manager.py`）：增删改查、文件名安全检查、元数据解析
- 脚本文件 API（`/admin/cmd/scripts`）：列表、获取、保存、删除
- 编辑器可折叠侧边栏：左侧显示脚本文件列表，支持展开/收起（localStorage 记忆状态）、点击打开、新建脚本
- CMD 控制台首页分开展示「脚本」和「快捷命令」两个区块
- 定时任务从文件系统读取脚本内容执行，`command` 字段存储文件名
- 一次性迁移脚本 `migrate_scripts_to_files.py`：将数据库中脚本类命令迁移到文件系统
- 前端实时 Python 语法检查（`editor-highlight.js` 新增 `registerDiagnostics` / `checkPythonSyntax`）：检查括号匹配、缩进一致性、冒号缺失、续行符错误、未闭合字符串，编辑器内实时显示错误波浪线
- 定时任务「从快捷命令选择」功能：创建/编辑定时任务时可直接从已有快捷命令列表中选择，自动填充命令内容和任务类型
- 代码结构重组：6 个大文件拆分为包结构（`core/db/`、`services/monitoring/`、`routes/community/`、`routes/admin/`、`routes/cmd/`、`routes/scheduled/`）
- 前端模块化拆分：`base.html` 拆分为 `base.css` + `base.js`；`editor.js` 拆分为 `editor-highlight.js` + `editor-sse.js`；`scheduled.js` 拆分出 `scheduled-logs.js`

### 修复
- 修复编辑器保存弹窗闪退：`CmdModal` 单例连续弹窗时，旧 `close()` 的 300ms 超时 `setTimeout` 会隐藏新弹窗。新增 `closeTimer` 在 `show()` 时清除旧定时器

### 变更
- 更新日志文件从项目根目录移至 `docs/CHANGELOG.md`

### 重构（代码结构优化）
- **`core/database.py`**(526行) → `core/db/` 包（`connection.py` + `schema.py`）
- **`services/monitoring.py`**(404行) → `services/monitoring/` 包（`cpu.py` + `memory.py` + `system.py`）
- **`routes/community.py`**(476行) → `routes/community/` 包（`pages` + `polls` + `board` + `helpers`）
- **`routes/admin.py`**(385行) → `routes/admin/` 包（`pages` + `users` + `mod_intros` + `logs` + `backup`）
- **`routes/cmd.py`**(383行) → `routes/cmd/` 包（`pages` + `commands` + `execution` + `script`）
- **`routes/scheduled.py`**(369行) → `routes/scheduled/` 包（`tasks` + `logs`）
- **`templates/base.html`**(1194行) → 提取 `static/css/base.css` + `static/js/base.js`
- **`static/js/cmd/editor.js`**(607行) → 拆分 `editor-highlight.js` + `editor-sse.js`
- **`static/js/cmd/scheduled.js`**(593行) → 拆分 `scheduled-logs.js`
- **executor 稳定性**：阶梯式终止（SIGTERM→SIGKILL）防止僵尸进程
- **SSE 稳定性**：短轮询替代长 wait，客户端断开时及时退出
- **scheduler 异常隔离**：单任务失败不影响调度循环

### 新增（MiniScript 后端化）
- MiniScript 后端 Python 执行引擎（`services/miniscript/`，独立子进程 + AST 沙箱 + 管道通信）
- 脚本定时执行功能：`scheduled_tasks` 表新增 `task_type` 字段（`shell` / `script`，默认 `shell`），调度器按类型分发到 `subprocess.run` 或 `ScriptExecutor`
- 数据库优化备份功能（手动触发 + 自动清理旧备份，备份写入 `./backups/db/`）
- 定时数据库备份调度器（默认每天 03:00 执行 CHECKPOINT + 文件复制 + 完整性校验）
- 数据库备份管理面板（`admin_db_backup.html`，含 10 阶段进度条与最近 20 条备份历史）
- 文件读写/数据库访问内置函数：`file_read` / `file_write` / `file_append` / `file_list` / `file_exists` / `db_query` / `db_execute`
- AST 沙箱校验器（`validate_script`）：拒绝 `exec` / `eval` / `compile` / `__import__` 等危险调用、双下划线属性访问、`global` / `nonlocal` 声明
- 脚本强制终止功能：`POST /admin/cmd/abort-script` 接口 + 编辑器/终端「强制终止」按钮
- 脚本内 `set_timeout(seconds)` 动态调整超时（上限 300 秒）
- MiniScript 脚本执行 SSE API：`POST /admin/cmd/run-script` 流式返回 `output` / `alert` / `prompt` / `confirm` / `error` / `done` 六种事件
- 交互响应接口 `POST /admin/cmd/script-response`：通过 `threading.Event` 唤醒等待中的 SSE 线程
- 脚本执行互斥控制：同时只允许一个脚本执行，并发请求返回 `409`
- 交互响应超时保护：等待前端响应超过 60 秒时，`prompt` 返回 `None`、`confirm` 返回 `False`
- 循环迭代上限保护：`while` / `for` 最大 100,000 次迭代
- `db_backups` 表：记录备份状态/大小/耗时
- 兼容老库：`init_db` 自动通过 `ALTER TABLE ADD COLUMN` 补齐 `task_type` 字段

### 变更
- 数据库从 SQLite 迁移到 DuckDB（高性能嵌入式 OLAP，单文件、列存、窗口函数）
- DuckDB 兼容层：`core/database.py` 封装 `DuckDBRow` / `lastrowid` / `executescript` / `SEQUENCE + nextval()` 模拟 sqlite3 接口
- 前端编辑器移除 JS 解释器，改用后端 SSE API 执行脚本
- Monaco 编辑器语法高亮改为 Python 配色（自定义 `pythonDark` 深色主题），编辑器模块从 `MiniScriptEditor` 重命名为 `ScriptEditor`
- 定时任务支持 `shell` 和 `script` 两种类型，前端管理页面新增任务类型选择器与徽章展示
- 定时任务状态实时反馈：任务卡片底部显示执行状态徽章，页面每 15 秒拉取 `/admin/cmd/scheduled/status` 轻量接口
- 访问日志自动清理迁移至独立服务 `services/log_cleaner.py`（后台线程定期检查），不再在中间件中每 10 条检查一次
- 日志清理扩展为多表：`access_logs` / `cmd_run_logs` / `scheduled_task_logs` 均支持自动清理

### 重构（前端模块化拆分 + 稳定性优化）
- **`templates/base.html`** 拆分：内联 CSS 提取至 `static/css/base.css`，内联 JS 提取至 `static/js/base.js`，模板改用 `<link>` / `<script>` 引用，模板行数大幅下降
- **`static/js/cmd/editor.js`** 拆分为三个职责清晰的文件：
  - `editor-highlight.js` — Monaco Python 语法高亮、代码补全、自定义主题（`window.ScriptEditor.highlight`）
  - `editor-sse.js` — SSE 执行、事件分发、强制终止（`window.ScriptEditor.execute` / `abort`）
  - `editor.js` — 核心初始化、工具栏绑定、输出面板管理
  - 模板 `admin_cmd_editor.html` 按依赖顺序加载：`editor-highlight.js` → `editor-sse.js` → `editor.js`
- **`static/js/cmd/scheduled.js`** 拆分为两个文件：
  - `scheduled.js` — 任务核心管理（CRUD / 启停 / 触发 / 状态轮询），暴露 `window.ScheduledCore`（含 `escapeHtml`）
  - `scheduled-logs.js` — 执行日志查看（分页 / 详情），暴露 `window.ScheduledLogs.openLogsModal(taskId | null)`
  - 模板 `admin_cmd_scheduled.html` 按顺序加载：`scheduled.js` → `scheduled-logs.js`
- **`services/miniscript/executor.py` 稳定性优化**：`_terminate_process` / `_cleanup` 采用「SIGTERM → 等待 → SIGKILL → 等待」阶梯式终止策略，确保子进程在任何异常路径下都被回收，避免僵尸进程；`proc.start()` 失败时显式关闭未使用的子端管道，避免 fd 泄漏
- **`routes/cmd/script.py` SSE 稳定性优化**：新增 `_wait_for_response` 短轮询（2 秒间隔）替代单次长 `wait()`，客户端断开 / 执行器被终止时能及时退出等待；显式捕获 `GeneratorExit` 不再尝试向已断开的连接 `yield` 错误；`finally` 中唤醒响应事件避免死锁，防御性释放 `_running_lock`
- **`services/scheduler.py` 任务异常隔离**：调度主循环 / `_tick` / `_execute_task` / `trigger_now` 全链路异常隔离 — 数据库异常不冒泡到主循环、单个任务提交失败不影响其他任务、收尾失败也确保从 `_running_tasks` 移除（避免任务卡死无法再次调度）；所有异常均带 `traceback` 输出便于排查

### 删除
- 前端 JavaScript MiniScript 解释器（`static/js/cmd/script.js`，约 1082 行）
- SQLite 数据库支持（`site.db`）
- 旧的 `cmd_sync()` / `regex()` / `append()` / `push()` / `pop()` / `slice()` / `set_interval()` / `clear_timer()` 等已废弃脚本函数
- 前端实时语法诊断（改为后端执行时通过 SSE `error` 事件回传）
- 一次性迁移脚本 `migrate_sqlite_to_duckdb.py`

### 修复
- 修复弹窗（alert/prompt/confirm）按钮点击无反应：移除遮挡按钮的 `escapeLayer` 透明层，改为 `document` 级别监听 ESC 键；修复 `display:flex` 优先级高于 Tailwind `.hidden` 类的问题；`close()` 添加 300ms 超时 fallback

## [历史版本]

### 新增
- 定时 CMD 终端命令运行功能：支持间隔执行、每日定时、一次性执行三种调度模式
- 日志自动清除功能：访问日志、CMD 日志、任务日志超限自动删除最旧记录，上限可在 `config.py` 配置
- CMD 代码编辑器（Monaco Editor）：语法高亮、代码补全、查找替换、多光标编辑、Minimap
- 用户系统、社区投票、留言板（多附件上传）、模组介绍、管理后台、服务器性能监控
- 异步多线程架构改造：日志写入、IP 查询、命令执行日志全部改为异步多线程，不阻塞 Web 请求
- 用户信息查询优化：单次请求内缓存（Flask `g` 对象），避免 middleware 和路由重复 DB 查询
- CPU 使用率改为非阻塞模式（`psutil.cpu_percent(interval=None)`）
- 社区页面数据库查询优化：批量查询消除 N+1 问题，N 个投票 + M 个主题从 `1 + 3N + 2M` 次查询降至 `4` 次
- AJAX 双模式支持：社区路由同时支持表单提交（flash + 重定向）与 AJAX 请求（JSON 响应）
- 文档系统：`/docs` 页面渲染 Markdown 文档（marked.js + 侧边栏导航）
- CherryPy WSGI 服务器（内置 SSL 支持）
- 磨砂玻璃（Glassmorphism）设计风格：`backdrop-filter` 模糊、动态背景光球、鼠标光晕跟随、按钮水波纹、滚动淡入
