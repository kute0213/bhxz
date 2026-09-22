# 更新日志

## [Unreleased]

### 新增

* **用户待审核内容数量限制**：新增 `MAX_PENDING_CONTENT` 配置项（默认 5），用户在建筑/指南/音频/背景上的待审核内容总数达到上限后无法继续发布。管理员豁免。可在管理后台 → 系统设置 → 内容审核中调整
* **公共建筑审核流程回归**：用户发布建筑后进入待审核状态（`status=pending`），管理后台建筑管理页新增「待审核」状态标签、通过/拒绝按钮（可填拒绝原因），列表按待审核优先排序；公开列表仅展示已审核通过的建筑，作者可在「我的建筑」中查看全部状态
* **一键更新脚本 rewrite**：根目录 [`update.py`](update.py) 完全重写——全平台兼容 Python 脚本，并发检测 15 个 GitHub 镜像源并自动选用延迟最低的，支持 `--yes` 静默模式，支持 git 仓库更新（含本地修改暂存/恢复）与非 git 环境 ZIP 下载覆盖两种模式，`git stash` 暂存本地修改，更新后自动安装依赖；**不会自动启动服务器**，仅提示手动重启
* **删除废弃 `services/easy_auth_db/` 模块**：密码直连验证模块已废弃，删除整个目录及 `services/rcon/easy_auth/` 中的引用，改密统一走 RCON 命令；同步删除关联文档 `docs/easyauth_bind_account_doc.md`

### 修复

* **IPv6 防火墙拦截模块**：防火墙设置页面新增「IPv6 拦截」开关，开启后所有 IPv6 连接（除 ::1 本地回环）直接被断开，拦截点覆盖连接层（Cheroot BanFilterConnection）、WSGI 层（FirewallWSGIWrapper）、中间件层（Flask before_request），三层兜底确保 IPv6 无法访问

### 修复

* **防火墙设置无法保存**：① AJAX 请求中新增 `X-CSRF-Token` 头，通过 CSRF 校验；② 将 `FIREWALL_CONFIG_KEYS` 传入模板上下文，修复前端获取空配置键列表导致无法保存的问题
* **管理员 403 无权限（CSRF 校验失败）**：`core/csrf.py` 新增 Content-Type: application/json 豁免，JSON POST 请求无需 CSRF Token（浏览器无法通过 HTML 表单伪造跨域 JSON POST，天然防 CSRF），解决所有管理后台 JSON API 路由的 403 问题

### 调整

* **防火墙日志改为 DEBUG 级别**：封禁创建/解除、白名单添加/移除等防火墙操作日志从 INFO 降为 DEBUG，减少 INFO 日志噪音
* **删除服务器启动成功提示日志**：移除 app.py 中的 `log('INFO', 'App', '所有服务已加载完成，服务器已启动')` 冗余日志
* **优化模块加载顺序**：按 6 层架构（基础设施→监控→路由→中间件→视图→服务）组织初始化流程，添加分层注释；删除 app.py 中不必要的启动打印

### 新增

* **防火墙日志筛选页面**：防火墙管理页面新增「日志」Tab，自动筛选 Firewall 相关日志，支持等级筛选、清空、自动滚动、3 秒轮询刷新

### 安全

* **自动封禁屡教不改升级永久封禁**：新增 `AUTO_BAN_PERMANENT_AFTER`（阈值次数，0=关闭）和 `AUTO_BAN_OFFENSE_WINDOW_HOURS`（统计窗口）配置，IP 在窗口内被自动封禁达到阈值次数后升级为永久封禁；配置后台热更新，内存违规记录每 120 秒自动清理

### 样式

* **全站统一弹窗系统重构**：创建 `macros/modal.html` 统一弹窗模板宏（`modal_shell`/`modal_captcha`/`modal_overlay`/`modal_close_script`），新增磨砂玻璃弹窗 CSS（尺寸变体、图标颜色类、响应式适配、过渡动画）；统一 `openModal`/`closeModal` 全局函数；重构 `admin_settings`/`broadcast`/`firewall`/`guides` 及 `register` 页面所有弹窗使用模板宏；修复 `admin_broadcast.html` 引用已删除元素的 ESC 处理器

### 新增

* **一键更新镜像源扩充至 14 个 + 并发检测**：内置 GitHub 加速镜像由 4 个扩充到 14 个（gh-proxy.com / ghproxy.net / mirror.ghproxy.com / ghfast.top / github.moeyy.xyz / slink.ltd / gh.ddlc.top / gh.h233.eu.org / ghproxy.1888866.xyz / hub.gitmirror.com / gh-proxy.net / github.boki.moe / gh.llkk.cc / kkgithub.com）；代理连通性检测由串行改为**多线程并发**（14 个镜像最坏耗时从 42s 降到约 3s），并按延迟升序返回全部可用源，下载时依次尝试，不再只依赖第一个
* **一键更新不再自动重启服务器**：更新完成后仅同步代码并提示「请手动重启服务器使新代码生效」，由管理员确认后自行重启，避免自动重启导致的服务中断；同步删除全部自动重启逻辑（重启辅助脚本、`RESTART_COMMAND` 配置与设置项、前端重启轮询）

* **统一任务注册模块（`core/shared/scheduler/` 包）**：全站所有定时执行功能的唯一入口（**防火墙除外**，防火墙保持独立实现）。任务按下次执行时间排序（`ScheduledTask`），注册表单线程（`TaskRegistry`）**每秒检测队首最早到期任务**，到期即取出派发并继续检查下一个；派发走 `TaskExecutor` 两种后台执行方式（`pool` 共享守护线程池 / `thread` 独立守护线程），**tick 线程永不阻塞**；任务执行期间从注册表取出、完成才重新入列，**天然防重叠执行**；基于 `time.monotonic()` 计时，不受系统时间跳变影响。保留两种调度模式：固定间隔（连续失败按 `backoff_factor/backoff_max` 退避）与每日时间点 `HH:MM`（支持配置热重载、当天去重、`mark_done()` 手动跳过当天）。8 个既有定时任务（验证码清理、邮箱验证码清理、RCON 连接池清理、玩家列表追踪、被驳回内容自动清理、每日数据库备份、站点地图刷新、游戏服务器封禁到期自动解封）全部迁移到注册表，行为与原逻辑一致；删除旧 `core/shared/scheduler.py`。全局 API：`register_task / unregister_task / start_task_scheduler / stop_task_scheduler`

* **游戏服务器封禁申请（用户申请 → 管理员审批 → RCON 自动执行）**：用户在「申请封禁玩家」页提交封禁玩家名、封禁玩家QQ名、封禁理由（图形验证码保护）；管理员在管理中心「游戏账号封禁」页（新增入口卡片）查看待审批 / 生效封禁 / 历史记录三个 Tab，可同意（可设封禁天数，留空为永久）或驳回（可填驳回原因），支持手动提前解封；同意后通过 RCON 执行 `ban 玩家游戏名`（无引号），封禁到期由后台定时任务（`game-ban-scheduler`，每 60 秒检查一次）执行 `pardon 玩家游戏名`（无引号）自动解封。新增 `game_server_ban_applications` 表（含 `idx_game_ban_expiry (status, expires_at)` 索引）与 `services/game_server_ban/` 服务层；玩家名经 `sanitize_rcon_username` 清洗杜绝 RCON 命令注入；RCON 连接失败（返回 `RCON ` 前缀错误）不推进状态、下个周期自动重试，单周期最多处理 50 条避免 RCON 长时间占用

### 结构优化（本次）

* **`static/` 合并至 `templates/static/`**：Flask 通过 `static_folder='templates/static'` 显式指定静态目录，模板与静态资源统一存放；静态资源 URL 路径 `/static/*` 保持不变，模板中全部 `url_for('static', ...)` 引用无需改动；同步更新 `build_static.py` / `package.py` / 验证码字体 / favicon 路由 / `.gitignore` 中的文件系统路径，移除启动检查中遗留的死目录 `static/uploads/*`
* **删除根目录 `utils/`**：`utils/` 所有文件已迁至 `core/shared/`，删除空的 `utils/` 目录
* **`services/` 和 `routes/` 全部子包化**：所有非 `__init__.py` 的 Python 文件均已转换为子包结构，实现彻底的文件夹分类
* **`web/` 独立顶层包回滚至 `core/`**：因根目录不允许新增文件夹，将临时迁出的 `web/` 顶层包（`csrf.py`、`errors.py`、`helpers.py`、`middleware.py`、`template_context.py`）移回 `core/` 扁平放置，导入路径从 `web.*` 恢复为 `core.*`

### 修复

* **防火墙：被封 IP 直接断开连接，不再返回 403 页面**：三层联动优化——① WSGI 门禁（`FirewallWSGIWrapper`）检测被封 IP 后立即关闭底层 socket（Cheroot 连接对象、werkzeug socket、wsgi.input 流三选一），不产生 HTTP 响应；② Flask fallback 从完整 HTML 403 页面缩为 `('', 403, {'Connection': 'close'})` 零内容响应；③ `server.py` 中 Flask 回退路径由 `app.run()` 改为 `run_simple` + 防火墙包装器，确保 WSGI 门禁始终生效。DDOS 攻击者仅消耗一次 `is_banned()` O(1) 缓存查询，不进入 Flask 处理管道、不分配内存、不写日志，不影响其他用户访问

* **`routes/admin/logs` 模块缺失（`No module named 'routes.admin.logs'`）**：`.gitignore` 的 `logs/` 规则会匹配任意层级的 `logs/` 目录，导致源码包 `routes/admin/logs/` 从未被 git 追踪、未上传 GitHub，用户 `git pull` 后启动必然失败。现将规则收窄为 `/logs/`（仅忽略根目录日志目录），并强制纳入 `routes/admin/logs/` 源码包
* **循环导入错误（`cannot import name from partially initialized module`）**：全部路由包（`admin` / `main` / `community` / `docs` / `guides` / `discussion` / `backgrounds` / `public`）子模块导入方式由 `from routes.package import X` 重构为 `import routes.package.X`。原写法属 fromlist 自导入反模式：父包 `__init__.py` 正在加载时，子模块反向导入父包中尚未定义完成的名称（如 `admin_bp`），在 Windows / 部分 Python 版本下必然触发循环导入。改用普通 `import` 仅绑定包名，加载完成后子模块内再通过属性访问，彻底消除该错误
* **防火墙误封内置回环地址**：添加 `BUILTIN_SAFE_IPS`（`127.0.0.1` / `::1` / `localhost`），在所有检查路径（`is_whitelisted`、`ban_ip`、`is_banned`、`sync_blacklist`、WSGI 门禁）中跳过这些地址，确保永远不会被封禁
* **`_refresh_ban_cache` 死锁**：该函数在被 `is_banned` 持有 `_ban_cache_lock` 时调用，其内部又试图重复获取同一个非可重入锁导致死锁；移除内部重复加锁，改为由调用方保证锁安全
* **白名单未合并 config.py 配置**：`get_whitelist()` 只查询 DuckDB `firewall_whitelist` 表，未包含 `config.py` 定义的 `FIREWALL_WHITELIST`；现改为合并两者，config 的白名单作为启动基线，DuckDB 的白名单为运行时补充
* **Windows 兼容性修复：重命名 `services/email/` → `services/mail/` 避免与 stdlib `email` 包命名冲突（Windows 大小写不敏感文件系统下尤其严重）**
* **`services/mail/code/` → `services/mail/verification/`**：`code` 与 stdlib `code` 模块命名冲突
* **`services/user/profile/` → `services/user/profiles/`**：`profile` 与 stdlib `profile` 模块命名冲突
* **`services/mail/code/__init__.py` 相对导入错误**：`from .service` → `from ..service`，子包化后 `.service` 错误解析为 `code.service` 而非同级 `service`
* **`services/backup/scheduler/__init__.py` 相对导入错误**：`from .manager` → `from ..manager`，同理 `scheduler.manager` 而非 `backup.manager`
* **17 处 `core.shared.helpers` 残留旧路径**：`helpers.py` 已合并至 `core/helpers.py`，但 17 个路由模块仍引用 `core.shared.helpers`，已全部批量修正为 `core.helpers`

### core 精简（本次）

* **扁平化 `core/auth/` → `core/auth.py`**：单文件子包降级为普通模块，减少一层目录嵌套
* **扁平化 `core/server/` → `core/server.py`**：同上
* **`core/web/helpers.py` → `core/helpers.py`**：依赖 Flask 的辅助函数归入 core 根层
* **`core/web/template_context.py` → `core/template_context.py`**：Flask 模板上下文处理器归入 core 根层
* **`core/shared/helpers.py` → `core/helpers.py`**：合并 shared 与 web 的 helpers 为统一文件
* **`core/shared/template_context.py` → `core/template_context.py`**：同上
* **`core/system/scheduler.py` → `core/shared/scheduler.py`**：通用调度工具从系统层归入共享工具

### 重构

* **彻底模块化重构项目文件结构**：
  * **core 精简**：将 8 个非核心工具函数（`helpers.py` / `ip.py` / `ratelimit.py` / `validation.py` / `captcha.py` / `security_scanner.py` / `process_utils.py` / `template_context.py`）从 `core/web/` 迁至新 `utils/` 目录，防火墙 (`core/firewall/`) 保持不变
  * **全部文件夹分类**：消除所有目录根目录的散乱文件（`__init__.py` 除外），将 12 个单文件转换为子包结构：
    * `services/`：`attachment_service/`、`background_service/`、`cleanup_service/`、`easy_auth_db/`、`settings_manager/`、`sitemap_cache/`（兼容层同步删除）
    * `routes/`：`sitemap/`（原 `routes/sitemap.py`）
    * `scripts/`：`migrate_db/`、`restore_db/`（原 `scripts/migrate_db.py`、`scripts/restore_db.py`）
  * **删除兼容层**：移除 `services/music_service.py`、`services/user_service.py`、`services/updater.py`、`routes/registry.py` 等所有单文件重导出兼容层，更新全部 12 处相关导入
  * **配置层统一**：`routes/__init__.py` 合并蓝图注册，消除独立 `routes/registry.py`

### 调整

* **全站统一错误页（错误号 / 原因 / 建议）**：新增 `core/errors.py` 统一错误页模块与 `templates/error.html` 统一模板，覆盖 400/401/403/404/405/413/429/500/502/503/504 全部常见错误码，每页展示「错误号（如 403 Forbidden）+ 错误原因 + 建议处理方法」；`abort(code, description)` 传参可覆盖默认原因；IP 封禁、可疑访问拦截（`core/middleware.py`）与防火墙黑名单拦截（`core/firewall.py`）均改用统一三要素错误页；删除旧的 `templates/403.html`、`templates/404.html`。同时整理 `core` 目录：错误页逻辑从 `core/server.py` 迁出（该文件恢复为纯 WSGI 服务器职责），`app.py` 改从 `core.errors` 注册错误处理器，`core/helpers.py` 移除重复的渲染函数。

* **新增 /robots.txt（三档爬虫策略，管理面板可配）**：新增 `routes/sitemap.py` 的 `/robots.txt` 路由，与 Sitemap 配合自动在文件中引用 `Sitemap: {站点}/sitemap.xml`；策略通过管理后台 → 系统设置 → Sitemap 分类新增的 `ROBOTS_POLICY` 下拉框切换（热更新即时生效）：`all` 允许所有爬虫（`Allow: /`）、`home` 仅允许主页爬虫（`Allow: /$` + `Disallow: /`）、`none` 禁止所有爬虫（`Disallow: /`）；Sitemap 引用地址优先取 `SITE_URL` 配置，未设置时取当前请求根地址。

* **Sitemap 全量携带 lastmod（自动读取数据库）**：`services/sitemap_cache.py` 重构 URL 条目构建逻辑，新增 `_latest_time()`（查询指定表最新时间字段）与 `_site_latest()`（跨内容表取全站最近更新时间）两个辅助函数；静态页面统一使用全站最近内容更新时间作为 `lastmod`，内容列表页取各自内容表最新一条（比全站时间更准确），指南/讨论帖/公开路径等动态页面取各自记录的 `updated_at`/`created_at`，生成的 sitemap 所有链接均带 `<lastmod>`，不再有缺失项。

* **数据库位置迁移至 `./db` 文件夹**：`config.py` 的 `DB_PATH` 由根目录 `./site.db` 改为 `./db/site.db`，启动时自动创建 `db` 目录；`core/db/connection.py` 新增 `_migrate_legacy_db()`，首次启动自动将旧版根目录下的 `site.db`（含 `-wal`/`-shm`）迁移到新位置，避免升级丢数据；`scripts/restore_db.py`、`scripts/uploads.py` 同步新路径；一键更新不替换列表（`UPDATE_EXCLUDED_FILES` / `services/updater/config.py` 的 `DEFAULT_EXCLUDED` / 更新页占位提示）由 `site.db,site.db-wal,site.db-shm` 改为 `db`；`routes/public/files.py` 敏感路径列表加入 `db` 防止数据库被公开访问。

### 修复

* **启动时反复提示添加缺失配置项**：`core/startup_checks.py` 的 `_check_config()` 原先用 `get_setting(key, None)` 判断配置是否存在，空字符串值（如留空的 `GITHUB_PROXIES`、`MAIL_SERVER`、`MAIL_USERNAME`、`MAIL_PASSWORD`、`MAIL_DEFAULT_SENDER`）被误判为缺失导致每次启动重复写入；改为通过 `get_all_settings()` 获取现有键集合，基于键存在性判断，空字符串是合法值不再误判。

* **/admin/public-files 页面 500 错误**：`templates/admin/admin_public_files.html` 缺少 `{% endblock %}` 闭合标签导致 Jinja2 `TemplateSyntaxError: Unexpected end of template`，已基于 `admin_music.html` 结构重建模板，恢复公开路径添加表单、路径列表表格与删除按钮；并编写脚本批量校验全部 54 个 Jinja2 模板语法，全部通过，确保不再出现同类错误。

### 新增

* **DDoS 攻击防护（极高性能多线程防火墙）**：新增 `core/firewall.py` —— 运行在 WSGI 入口（先于一切 Flask 逻辑）的高性能多线程防火墙。① **黑名单快速拦截**：进程内维护黑名单内存镜像（O(1) 集合查询，每 0.5 秒从数据库同步），命中黑名单的请求不进入路由/模板/数据库/静态文件等任何业务处理，直接返回最小 403 响应并标记 `Connection: close`；后台监控线程同时利用 Cheroot 连接特性（`linger=False` + `close()`）强制关闭黑名单 IP 的现存连接（含 keep-alive 空闲与处理中的请求，覆盖连接管理器 selector 与 WSGI 门禁登记两路来源），客户端表现为连接被重置而非收到页面。② **DDoS 检测**：按检测强度统计单位检测窗口（10 秒）内每个 IP 的请求数（low=宽松 300 次 / medium=中等 150 次 / high=严格 80 次），超阈值立即自动封禁来源 IP（复用 `ip_ban_service.create_ban`，操作人显示「系统」，白名单 IP 跳过）；首次限时封禁（时长可配，默认 30 分钟，0 为直接永久封禁），在违规记录时间窗口（默认 24 小时）内多次触发（默认 3 次）自动升级为**永久封禁**（屡教不改）；静态资源（`/static/`）不计入计数避免误判，计数器与违规记录由后台线程定期清理。③ **配置热更新**：`config.py` 新增 `DDOS_GUARD_ENABLED` / `DDOS_GUARD_INTENSITY` / `DDOS_GUARD_BAN_MINUTES` / `DDOS_GUARD_PERMANENT_AFTER` / `DDOS_GUARD_OFFENSE_WINDOW_HOURS`，管理后台 → 系统设置新增「DDoS 防护」分类，检测强度/封禁时长/触发次数等修改 5 秒内生效，无需重启。④ `core/server.py` 使用 `FirewallServer`（自定义网关向 environ 注入 `cheroot.connection`）集成防火墙，服务器启动/关闭时自动启停防火墙后台线程。

### 移除

* **移除 CPU 温度检测功能**：`routes/api/public.py` 删除跨平台温度采集（psutil 传感器 / Windows WMI / PowerShell / macOS sysctl 与全部子进程调用）与 `/api/server-status` 响应中的 `cpu_temp` 字段；`templates/server_status.html` 删除 CPU 温度展示板块与对应 JavaScript 刷新逻辑。

### 调整

* **「申请账号」入口调整**：从导航栏「互动」分类移至「导航」分类，并更名为「申请服务器账号」（桌面端主导航下拉与移动端侧栏同步调整，`templates/base.html`）。

### 修复

* **IP 封禁管理页内联编辑配置**：IP 封禁管理页面（`/admin/ip-bans`）新增自动封禁开关与时长、可疑访问拦截开关与时长、封禁白名单的内联编辑与保存（新接口 `POST /admin/ip-bans/settings`，仅接受白名单/自动封禁/可疑拦截相关配置键）；`services/ip_ban_service.py` 新增 `get_whitelist()` 优先读取数据库配置实现热更新，`is_whitelisted()` 改为实时读取，白名单修改立即生效，无需跳转系统设置。

* **自定义启动指令（彻底修复自动更新重启失败）**：`config.py` 新增 `RESTART_COMMAND` 配置（默认空，支持环境变量 `RESTART_COMMAND`，管理后台 → 系统设置 / 一键更新配置页均可在线编辑）；`services/updater/core.py` 的 `_get_restart_cmd()` 优先使用自定义指令（`shlex` 解析参数，裸 `python`/`python3` 自动替换为当前真实解释器保证运行环境一致），留空回退自动构建「当前解释器 + app.py + 原启动参数」，覆盖 `python` / venv / `uv run` 任意启动方式。

* **可疑访问拦截**：新增攻击特征扫描器（`services/security_scanner.py`），在请求进入业务处理前扫描路径/查询串/请求体/User-Agent，识别 SQL 注入、XSS、路径穿越、命令注入、敏感文件与漏洞端点探测、恶意扫描 UA 六类攻击特征；命中即返回 403 拦截请求并自动封禁来源 IP（`ban_suspicious_ip`，复用 IP 封禁白名单与 30 秒缓存，封禁原因标注攻击类型与命中片段，操作人显示「系统」，到期自动解除）；管理后台 → 系统设置新增「可疑访问拦截」分类（总开关 `SUSPICIOUS_BLOCK_ENABLED`、封禁时长 `SUSPICIOUS_BLOCK_DURATION_MINUTES`（分钟，0 为永久）、SQL 注入/XSS/路径穿越/命令注入/敏感探测/恶意 UA 六类独立子开关，热更新即时生效）；IP 封禁管理页展示可疑访问拦截状态卡片；静态资源（`/static/`）跳过扫描，URL 层全量特征 + 原始与 URL 解码两层匹配，请求体仅扫描文本类且 ≤1MB 内容中的高置信度特征，避免用户生成内容（Markdown 代码块等）误判；新增 `scripts/tests/test_security_scanner.py` 与 `test_ip_ban.py` 可疑封禁用例（96 项安全用例全部通过）。

* **自动 IP 封禁**：触发限流的可疑操作（登录/注册/找回密码/邮箱验证码）自动封禁来源 IP，封禁时长可配置（默认 30 分钟，0 为永久封禁），到期自动解除；管理后台 → 系统设置新增「IP 封禁」分类（总开关、封禁时长、各操作独立开关），IP 封禁管理页展示自动封禁与白名单状态；封禁白名单在 `config.py` 的 `IP_BAN_WHITELIST` 配置（默认 `112.82.136.172`），白名单 IP 不会被手动或自动封禁。

### 修复

* **修复 /admin/settings 500 错误**：`templates/admin/admin_settings.html` 因文件截断缺少 `{% endblock %}` 闭合标签，Jinja2 编译抛出 `TemplateSyntaxError: Unexpected end of template`（错误页报告为 Internal Server Error），已基于完整版本重写模板，恢复设置项动态渲染、自动保存、单项/全部恢复默认与确认弹窗等全部功能。

* **subprocess 编码统一 UTF-8（补全 Windows 10 场景）**：`services/process_utils.py` 的 `make_env()` 新增 `PYTHONUTF8=1`（强制 Python 子进程启用 UTF-8 模式），与既有 `PYTHONIOENCODING=utf-8` 一起从源头消除 Windows 10 下子进程 GBK 输出乱码 / `UnicodeDecodeError`；已覆盖 CPU 温度获取、ffmpeg/ffprobe 转码、数据库备份恢复、一键更新等全部子进程场景

* **自动更新重启改为通用启动命令（修复 uv 运行下无法自动启动）**：`services/updater/core.py` 重启逻辑不再写死 `[python, app.py]`，改为 `_get_restart_cmd()` 用「当前真实解释器 + 原启动脚本 + 原启动参数（sys.argv）」重建完整启动命令——无论服务器用 `python`、venv 还是 `uv run` 启动，解释器路径与 uv/虚拟环境变量（随重启脚本继承）天然一致，不针对 uv 做任何特殊处理；同时完整保留 `--host/--port` 等命令行参数，兜底 `_direct_restart()` 同步生效

* **服务器状态页整合玩家板块**：`/server-status` 在线玩家、最大玩家数、服务器状态三个小卡片移入「在线玩家列表」卡片头部，以紧凑徽章展示（在线=绿 / 状态=红/绿），页面更简洁，数据刷新逻辑不变

* **图形验证码进一步优化（字更大 + 干扰更丰富 + 颜色更多）**：字号比例由 `min(96, height*0.68)` 提升为 `min(120, height*0.76)`；干扰横线/斜线由 3~6 条增至 5~8 条、干扰字符由 20~40 个增至 30~50 个，并新增 2~5 个随机彩色圆点干扰；干扰线色池扩充至 14 色、字符深色池扩充至 12 色、浅色干扰字符池扩充至 14 色，随机性更强、更难被机器识别，同时保持人类可读（登录页图片 200×72、`object-fit: contain` 完整显示）

* **修复背景图片与评论等删除失败问题**：`services/background_service.py` 的 `remove_background_files`/`_pick_variant` 对 `sqlite3.Row` 使用 `.get()` 导致 `AttributeError`（背景图片删除/取图失败），改为按键访问 `bg['file_path']`/`bg['id']`；`routes/community/helpers.py` 的 `_respond` 默认重定向端点从不存在的 `community.community_page` 改为 `main.home`，修复讨论区删除回复/帖子时 `url_for` 构建失败返回 500；`templates/discussion/detail.html` 回复删除错误提示统一为「删除失败，请重试。」；删除权限校验正常返回 JSON 失败结果（如「无权限」）而非 500

### 样式

* **导航栏动画流畅度优化**：导航栏下拉 caret 箭头与滚动收缩动画补上 `will-change: transform`，提前告知浏览器对变换动画元素做合成层优化，减少重绘重排，动画更流畅——仅做性能提升，动画时长、缓动曲线与视觉效果完全不变

* **控件全面改为白色略微透明磨砂玻璃**：主按钮（`.btn-primary`）由黑色渐变改为白色半透明磨砂玻璃（深色文字 + 蓝色强调边），次按钮/危险按钮/输入框/导航/弹窗/Toast 等控件统一为白色磨砂玻璃质感，更好适配全站背景图片；深色工具类（`.bg-forest-900` 系列）全局映射为白色半透明背景；Markdown 编辑器面板、讨论区与指南正文的代码块保持深色卡片保证可读性，行内代码改为浅蓝底深蓝字；浅色状态文字（红/黄/绿/蓝 300/400 系列）全局映射为深色可读版本（代码块内除外）；指南卡片、广播富文本编辑器、更新日志面板等同步改为白色磨砂玻璃。

* **主页改为白色浅蓝磨砂玻璃风格**：首页从深色海洋风格全面转换为白色浅蓝主题，背景图片在滚动时保持可见（浅白渐变叠层自顶部至中部渐隐、底部再渐显，保证导航可读性且不遮挡背景）；标题改为深色 + 浅蓝渐变强调字，图标统一浅蓝色；滚动条与进度条统一为浅蓝渐变磨砂玻璃风格。

* **危险操作按钮统一为淡红色磨砂玻璃**：管理中心的驳回按钮（`admin_game_accounts.html`）等危险操作按钮改用 `.btn-danger` 类——淡红色半透明磨砂玻璃质感，与全站白色磨砂玻璃控件风格一致，同时通过颜色区分危险操作；控件样式集中定义（`.btn-primary`/`.btn-secondary`/`.btn-danger`/`.pixel-card`/`.input-field`），便于后续统一修改

### 新增

* **背景图片按屏幕比例最适配取图**：保存时记录图片自然宽高比（`backgrounds` 表新增 `ratio` 列，默认 16:9；不再强制裁剪 16:9，裁剪推迟到取图时按屏幕比例进行）；客户端在页面解析到背景元素后立即发起预加载（内联脚本，不等动画与其他脚本），自动获取屏幕宽高比（宽/高，保留 2 位）与物理像素长边，携带 `size` + `ratio` 参数请求图片；服务端将所选档位中心裁剪到该比例后返回（`_crop_to_ratio`，32 项内存缓存，比例已匹配时直接返回原数据不重复编码）。横屏/竖屏均获得与屏幕比例完全匹配且像素充足的图片，移动端清晰度大幅提升、传输量减少；无比例参数时保持原自然比例图片，向后兼容。

* **IP 封禁功能**：管理后台新增「IP 封禁」页面（`/admin/ip-bans`），管理员可添加封禁 IP（支持 IPv4/IPv6 与 CIDR 段）、设置临时封禁时长或永久封禁、填写封禁原因；被封禁 IP 的所有请求（含静态资源）由中间件统一拦截返回 403；管理员可随时在后台解封；服务层内置 30 秒内存缓存降低全站每次请求的数据库查询压力，创建/解封时立即失效缓存，临时封禁到期自动清理。

* **模组介绍链接功能**：`mod_intros` 表新增 `link` 字段（后台添加/编辑表单新增「模组链接」输入框，`_normalize_link` 自动补全 `https://` 协议）；首页模组卡片带链接时整卡变为可点击链接（新窗口打开，`target="_blank" rel="noopener noreferrer"`），并显示「查看详情」跳转提示

* **系统日志页改为控制台式顺序**：`/admin/logs` 日志由「最新在前」反转为按时间顺序从上到下展示（旧→新，与控制台一致），自动滚动改为定位到底部跟随最新日志

* **被驳回内容 24 小时自动删除**：新增 `services/cleanup_service.py` 的 `CleanupScheduler` 定时调度（`core/init.py` 注册，每 30 分钟执行一次），自动清理被驳回超过 24 小时的内容——服务器指南、背景图片等，删除数据库记录的同时删除关联的本地文件（背景主图与响应式变体等），释放存储空间

* **「申请账号」入口（互动分类）**：导航栏「互动」下拉菜单新增「申请账号」入口（`account_apply` 蓝图，页面 `/game-accounts/apply`；管理 API 见 `routes/admin/account_applications.py`），登录用户可申请注册 MC 游戏账号，提交后进入管理员审批队列（`game_account_registrations` 表），管理后台「账号注册申请管理」可审批/驳回/封禁

* **背景图片支持一次性上传多个文件**：`/backgrounds/upload` 支持拖放/选择多个图片文件（前端文件列表展示、单个移除、格式与 10MB 大小校验），后端为每个文件创建独立上传任务并返回任务 ID 数组（`routes/backgrounds/pages.py` 改用 `request.files.getlist` 批量处理），前端聚合展示整体上传进度

### 重构

* **统一定时调度算法**：新增 `core/scheduler.py`（`Scheduler` 类 + 纯算法辅助函数），统一收敛全站定时逻辑——固定间隔模式（含失败退避：基础间隔 + 失败次数 × 系数，封顶上限）、时间点模式（每日 HH:MM 触发、当天去重）、分片等待（`Event.wait` 及时响应停止信号）、优雅停止与失败计数；已接入被驳回内容自动清理（`cleanup_service.py`）、每日备份（`backup/scheduler.py`）、玩家列表追踪（`rcon/player_tracker.py`）、验证码过期清理（`captcha.py`、`email/code.py`）、连接池清理（`rcon/pool.py`）、站点地图刷新（`sitemap_cache.py`），行为与原有逻辑保持一致

* **背景图片统一命名**：上传的背景图片不再使用原始文件名，统一按 `bg_<id>_<hash>.webp` 规则重命名存储（原扩展名规范化），避免文件名冲突并便于管理；`background_service.py` 新增 `_background_filename` 命名辅助函数。

* **清理无用代码**：删除顶层残留的 `static/js/base.js`、`static/js/main.js`（模板实际引用 `js/core/base.js` 与 `js/pages/main.js`），删除空的 `static/js/script/` 目录；`static/lib/lib-version.json` 移除已废弃的 `xterm_version` 字段；`scripts/build/package.py` 打包排除项由 `*.duckdb` 更新为 `*.db-wal`/`*.db-shm`；`.gitignore` 移除 DuckDB 残留条目；管理后台备份页文案同步去除「命令日志/定时任务日志」过期描述

* **大文件按功能模块拆分为子包**：`services/music_service.py`（861行）→ `services/music/`（constants.py / queries.py / crud.py / upload.py / favorites.py），`services/user_service.py`（648行）→ `services/user/`（auth.py / profile.py / admin.py），`services/updater.py`（660行）→ `services/updater/`（config.py / core.py），`services/discussion_service.py`（531行）→ `services/discussion/`（topics.py / replies.py / categories.py）；保留原文件作为兼容性重导出层（`from services.music import *`），旧代码无需修改导入路径

* **空异常捕获增加日志**：`core/init.py` 中两个 `except Exception: pass` 改为 `log('WARNING', ...)` 记录，便于排查问题

* **彻底删除游戏账号绑定/改密功能**：移除游戏账号绑定、改密、解绑相关代码与数据——删除 `routes/game_accounts/bind.py`、`routes/game_accounts/register.py`、`services/game_accounts/binding_service.py`、`services/easyauth_bind.py` 及模板 `game_accounts/bind.html`、`game_accounts/change_password.html`、`game_accounts/index.html`、`admin/admin_game_account_bindings.html`；数据库删除 `game_account_bindings` 表（`core/db/schema.py` 与 `scripts/migrate_db.py` 同步）；**保留 RCON 服务**（`services/rcon/`）与申请注册能力；`game_accounts` 蓝图重构为纯申请注册（`/game-accounts/apply` + `/api/apply-register`），管理后台合并为「账号注册申请管理」

### 修复

* **背景图片审核通过直接启用**：管理员在后台审核通过背景图片时，该背景自动设为当前显示（`status=approved` 且 `is_active=1`），并同时取消其他背景的激活状态，无需再手动点击启用；「当前显示」按钮与状态徽章（黄色/绿色/蓝色）改为深色文字 + 浅色底，修复 `/backgrounds` 页面浅色文字与浅色底融合导致按钮/徽章不可见的问题。

* **站点地图更新**：移除已删除的 `/performance` 页面，新增 `/server-status` 和 `/interact` 页面的 sitemap 条目

* **平板导航简化为横屏/竖屏模式**：移除独立的平板端导航代码路径（`md:flex lg:hidden`），平板横屏直接使用桌面端导航（`md:flex`），竖屏使用移动端导航，减少代码冗余

* **图形验证码优化（修复「验证码太小」）**：默认尺寸 360x128 → 420x150，字号增大（`font_size = min(96, int(height*0.68))`）；干扰元素升级——3~6 条明快色系（红/橙/蓝/绿/紫/青等）彩色干扰横线/斜线、字符后方 20~40 个浅色小号干扰字符（数字/字母/短横线/点）、背景噪点数量增加并随机浅色着色（不再只是灰色）；字符颜色改为从深色系（深蓝/深红/深绿/深紫/墨黑/深棕）随机选取，保持清晰可辨；位数（4 位）与字符集不变，`generate()`/`verify()`/`consume()` 接口不变；弹窗图片 `max-w-[360px]` 放宽至 `max-w-[420px]`

* **subprocess 编码统一 UTF-8（修复 Windows 10 GBK 乱码/UnicodeDecodeError）**：`services/music/upload.py` 的 ffmpeg/ffprobe 子进程去除 `text=True`，统一改用 `env=services.process_utils.make_env()`（`PYTHONIOENCODING=utf-8`）+ `decode_output()` 解码字节输出；`routes/admin/backup.py` 启动恢复脚本、`scripts/restore_db.py` 启动服务器均传入 `env=make_env()`，跨平台统一处理，不再依赖系统 locale 编码

### 文档

* **项目结构文档同步**：README.md 项目结构、架构目录、services 子模块列表全面同步最新代码结构

### 安全

* **指令执行安全增强**：所有 RCON 指令输入（用户名、密码）均经过 `sanitize_rcon_username` / `sanitize_rcon_password` 清洗，移除命令注入字符（`; | & \` $ ( ) { } " \n \r\`），防止命令注入攻击；密码参数始终用引号包裹

* **弱密码数据库**：集成 150+ 常见易猜密码黑名单（含数字序列、字母序列、键盘模式、常见中文密码等），并检测纯重复字符密码和纯连续序列密码

* **双重验证防御**：前端 JS 和后端 Python 均执行相同的格式和强度验证，避免绕过

### 优化

* **集中化验证模块**：创建 `services/validation.py`，统一管理所有输入验证（MC 用户名、网站用户名、密码强度、RCON 安全、邮箱格式、封禁理由），避免重复代码和验证遗漏

* **用户名严格验证**：MC 用户名字符限制（3-16 位，仅字母数字下划线）+ 连续下划线禁止；网站用户名禁止 HTML/JS 注入字符（`< > ' " ; &` 等），Unicode 类别白名单

* **密码强度提升**：游戏账号密码从 4 位提升到 8 位，要求含字母和数字；网站密码新增弱密码检测

* **模型层验证下沉**：`registration_service.create_application` 和 `binding_service` 等底层函数也内嵌验证，形成多层防御

* **项目结构优化**：按功能模块全面分类组织代码，`services/` 新增 `game_accounts/`、`monitoring/tracker.py`、`rcon/easy_auth.py`、`terminal/` 等子包；`routes/` 新增 `game_accounts/`、`backgrounds/`、`community/`、`scheduled/`、`script/` 等子包；`templates/` 按模块细分目录；消除根目录文件堆积

* **RCON 客户端统一**：合并重复的 RCON 客户端代码，`services/rcon/easy_auth.py` 统一封装 EasyAuth 插件指令（注册、改密、删除等），`services/rcon/client.py` 作为唯一 RCON 连接入口

* **代码清理**：删除未使用的导入（`re`、`json`、`shlex`、`Flask` 等）、删除重复代理配置（`updater.py` 中 `ghproxy.net` 重复条目）、删除死代码和冗余文件（`services/game_accounts/rcon_client.py`）

* **性能监控独立追踪器**：`services/monitoring/tracker.py` 新增 `PerformanceTracker`，后台线程每 5 秒采集 CPU/内存/系统信息并缓存，前端轮询读取，避免每次请求都调用 psutil

* **文档同步更新**：README.md 项目结构、架构目录、API 接口、功能特性章节全面同步最新代码结构

### 修复

* **修复指南列表页500错误**：`templates/guides/index.html` 中 `guide.content[:120]` 在 `content` 为 `None` 时抛出 `TypeError`，导致页面崩溃。现使用 `(guide.content or '')[:120]` 安全处理 None 值

* **修复 settings\_manager 类型转换错误**：`_cast_value` 函数在 `raw` 参数为整数时调用 `raw.lower()` 抛出 `AttributeError`，现统一先转 `str(raw)` 再处理

### 新增

* **安全风险自评估报告**\[docs/SECURITY\_REPORT.md]：按 OWASP Top 10（2021）逐项评估交互式服务安全检查表，涵盖 12 大类 40+ 检查项，发现 3 项严重、4 项高危、8 项中危、8 项低危风险，并提供优先级排序的改进建议

* **手动广播邮件改为富文本（所见即所得）**：广播编辑由 Markdown 编辑器升级为 contenteditable 富文本编辑器（`templates/admin/admin_broadcast.html` 工具栏：加粗/斜体/下划线/删除线、H2/H3 标题、无序/有序列表、引用、插入链接、清除格式 + 字数统计 + 插入示例），所见即所得直接编辑排版；发送时提交 `html` 字段，后端经白名单清洗后嵌入邮件模板（`services/email/sanitize.py` 新增 `sanitize_email_html`/`html_to_plain_text`，`routes/admin/broadcast.py` 校验/清洗/纯文本兜底逻辑同步更新，`services/email/templates.py` 的 `broadcast_message()` 改为接收富文本 HTML），仅保留常见排版标签与安全 `a[href]`/`font[color]`，script/style/iframe 及 `javascript:` 链接等危险内容一律剔除，防 XSS 与邮件注入；管理中心广播邮件入口按钮下方说明文案同步更新为「向全体用户发送富文本（所见即所得）格式的邮件广播」

* **大喇叭音频收藏**：公开音频列表 / 我的音频均提供「收藏」按钮（`templates/macros/music_macros.html` 新增 `music_favorite_button` 宏），可收藏**别人上传的公开音频**，收藏后可在「我的收藏」页（`/music/my/favorites`，`templates/music/favorites.html`）统一查看与播放（含收藏时间、上传者、标签、播放器与复制链接按钮）；同一用户对同一音频仅一条收藏（数据库新增 `music_favorites` 表，联合主键 `(user_id, music_id)`），重复点击即取消，收藏操作走 AJAX 局部刷新（`static/js/base.js` 全局事件委托）；仅已公开音频可被收藏，删除音频时自动级联清理收藏记录（`services/music_service.py` 新增 `toggle_favorite`/`get_favorite_ids`/`get_user_favorites`，`routes/main/music.py` 新增 `/music/my/favorites` 页面与 `/music/<id>/favorite` 接口）

* **大喇叭音频标签**：上传音频时可填标签（`services/music_service.py` 新增 `parse_tags`：逗号/顿号/分号/空白分隔、自动去重、最多 10 个、每个 ≤12 字），「我的音频」与管理后台「大喇叭音频管理」可随时编辑（`static/js/base.js` 标签编辑交互 + `templates/macros/music_macros.html` 新增 `music_tags_list` 展示宏，金色徽章展示）；权限控制：普通用户仅可编辑自己上传的音频，管理员可编辑任意；**搜索可直接命中标签**——公开列表搜索 `get_public_musics(keyword)` 同时匹配 `title LIKE` 与 `tags LIKE`（数据库 `music.tags` 列，`core/db/schema.py` 自动迁移新增），不再只能搜到标题

* **全部弹窗统一为网页内自定义弹窗（无原生弹窗）**：

  * `templates/macros/modal.html` 新增 `modal_overlay` 宏，统一渲染自定义弹窗骨架（alert / confirm / prompt 共用磨砂玻璃风格），由 `base.html` 引入一次，替代原先内联在 base 中的弹窗 HTML

  * `static/js/base.js` 的 `CustomModal` 升级为 **Promise + 回调双风格** API，并新增 **`prompt`** 方法（含输入框聚焦/预填/占位提示、确认返回输入值、取消返回 `null`），同时支持字符串标题简写（如 `CustomModal.confirm('...', '确认清空').then(...)`）

  * **移除全部原生弹窗调用**：富文本广播「插入链接」的 `prompt()` 改用 `CustomModal.prompt`（`templates/admin/admin_broadcast.html`）；大喇叭音频「编辑标签」的 `prompt()` 改用 `CustomModal.prompt`（`static/js/base.js`）；讨论区「删除回复」的 `confirm()`/`alert()` 改用 `CustomModal.confirm` + `Toast.error`（`templates/discussion/detail.html`）

  * 各页面 `onsubmit="return confirm(...)"` 删除确认仍由 `base.js` 全局拦截自动转为自定义弹窗；`static/css/base.css` 新增 `.modal-input-wrap` 输入区样式（与弹窗磨砂风格一致、金色聚焦态、窄屏适配）；`base.js` 缓存版本升至 v=19

  * 顺带修复：管理中心广播页「清空内容」确认此前调用 `CustomModal.confirm(...).then(...)` 因旧版 `CustomModal` 不返回 Promise 而失效，升级后正常工作

### 修复

* **全站响应式适配所有屏幕大小**：

  * **音频卡片按钮「穿模」/无法点击**：竖屏/窄屏（≤640px）下，音频卡片操作按钮组（复制广播 m3u / 唱片 MP3 / 时长 Ns / 申请公开/审核操作）此前 `flex-shrink-0` 单行不换行，横向溢出后被 `body{overflow-x:clip}` 裁切导致按钮相互重叠、无法点击；现新增 `.music-card-actions` 样式（`static/css/base.css`）：窄屏时占满整行并自动换行排列，≥640px 恢复单行右对齐，`music/list.html`、`music/my.html`、`admin/admin_music.html` 三处卡片统一改用

  * **倍速/音量弹层窄屏被裁切**：弹层靠近播放器右缘、居中展开时窄屏下会超出卡片/视口边界被裁切无法操作；`@media (max-width:480px)` 下改为右对齐（`.mp-vol-slider`/`.mp-speed-menu`），保证弹层始终落在卡片内可操作

  * **全局兜底**：`body` 增加 `overflow-wrap: break-word`，长 URL/连续字符自动换行不再撑破布局，配合 `overflow-x: clip` 彻底杜绝页面横向滚动（所有页面共用 base 布局，导航栏桌面/平板/移动端三套 + 管理员表格 `overflow-x-auto` + 文档 `pre/table` 自带横向滚动均已覆盖）

* **私有/待审核音频改为「凭链接任何人可访问」**：此前非公开音频仅上传者本人或管理员可播放（`_can_access` 按用户身份拦截），现移除该访问限制——所有音频（含私有/待审核）的 m3u8 播放链接、唱片 MP3、HLS 分片均可直接凭链接访问（无需登录），私有仅表示该音频不会出现在公开音频列表中，公开仍需管理员审核（`routes/main/music.py` 删除 `_can_access` 及三处播放路由的身份校验）

* **「复制链接」按钮更名为「复制广播m3u链接」**：公开列表 / 我的音频 / 管理员审核队列 / 上传成功卡片中的广播链接复制按钮文案统一改为「复制广播m3u链接」（并补充 tooltip 说明用于游戏内大喇叭在线播放），与「唱片 MP3」「时长 Ns」按钮语义区分更清晰（`templates/macros/music_macros.html`、`templates/music/upload.html`）

* **修复播放器进度条圆点不跟随进度、倍速/音量弹层被卡片遮挡**：

  * 进度条圆点（`.mp-thumb`）此前始终停在进度条最前端——`setFill()` 只更新了填充条宽度，从未更新圆点的 `left` 位置，现已同步设置 `thumb.style.left = pct%`，圆点随播放进度实时移动（拖动 seek 时同样跟随）

  * 倍速/音量弹层向上展开时被卡片裁切/遮挡——根因是 `.pixel-card` 上 `contain: paint` 与 `content-visibility: auto` 会强制裁切溢出内容，`overflow:visible` 无法覆盖；现为内含播放器的卡片显式添加 `.music-card` 修饰类，降级为 `contain: layout style` + `content-visibility: visible`，弹层可正常越出卡片边界显示（`static/css/base.css`，`templates/music/list.html`、`templates/music/my.html`、`templates/admin/admin_music.html` 同步添加类）

### 新增

* **复制音频时长（秒）按钮**：公开音频列表 / 我的音频 / 管理员审核队列中的每个音频新增「时长 Ns」按钮，点击一键复制**以秒为单位的音频总时长**（如 `215`）。时长由 HLS 播放列表各分片 `EXTINF` 累计得出（`services/music_service.py` 新增 `get_music_duration_seconds` 与 `attach_durations`，公开列表/我的音频/管理后台路由统一调用补充 `duration_seconds` 字段），对所有音频（含历史数据）都适用、无需存库迁移；复制逻辑由 `static/js/base.js` 新增的全局事件委托（`.copy-duration-btn`）统一处理，任意页面/动态加载的按钮均可一键复制并 Toast 提示已复制秒数；模板宏新增 `music_duration_button`（`templates/macros/music_macros.html`），三个页面入口同步接入

### 修复

* **修复大喇叭音频并发上传时编号错乱导致无法播放、删除不清理文件**：`_insert_music_record` 原在 `conn.commit()` 之后、线程锁之外读取共享游标的 `cursor.lastrowid`，并发上传时该值会被其他线程的 INSERT 覆盖，返回错误 ID——导致音频文件被写入错误的 `<ID>` 目录（播放 404）、按真实 ID 删除时也清理不到对应目录。现改为在持锁事务（`with get_db() as conn:`）内完成 INSERT 并立刻读取 `lastrowid`（`DuckDBCursor` 在 INSERT 后即用 `currval` 计算），保证返回的 ID 与数据库记录一一对应；20 线程并发插入测试全部返回唯一且正确的 ID

### 新增

* **唱片 MP3（供游戏内烧录唱片）**：上传转码由「仅 HLS」升级为一次同时输出 HLS 流（`index.m3u8` + `seg_*.ts`）与 **192kbps 唱片 MP3**（`index.mp3`，`libmp3lame` + ID3v2.3 标签），新增路由 `GET /music/<id>.mp3` 服务下载（权限与 m3u8 播放链接完全一致，公开音频所有人可下载），公开列表页 / 我的音频 / 管理后台 / 上传成功卡片均提供「唱片 MP3」复制链接按钮，供游戏内「电脑」下载后烧录成唱片（`services/music_service.py` 新增 `get_music_mp3_path` 与 `_build_transcode_cmd` 双输出，`routes/main/music.py` 新增 `serve_music_mp3`，`templates/macros/music_macros.html` 新增 `music_mp3_link_button`）

* **转码后自动删除原音频源文件**：`_finalize_music_files` 在转码成功、落库完成后自动清理原始上传文件（`source.*`）与临时进度/错误日志（`progress.log`、`transcode.err`），目录内仅保留播放与唱片所需的 `index.m3u8`、`seg_*.ts`、`index.mp3`，避免源文件占用空间与泄露原始文件名

* **ffmpeg 转码实时进度条填充真实百分比**：后台轮询 ffmpeg `-progress` 文件（`out_time_us`）与 m3u8 已生成分片的累计时长**双源取较大值**计算真实百分比，前端转码进度条随百分比实时填充（真实百分比未知时保持不确定态滑动动画，不再只有文字百分比），解决快速转码时进度条停留在 0% 的问题（`services/music_service.py` 新增 `_read_transcode_percent`，`static/js/music_upload.js` 转码进度条逻辑改为按 `percent>0` 填充并显示百分比文本）

* **全站安全响应标头**：在 `core/middleware.py` 集中新增 `after_request` 钩子，为所有响应（HTML/JSON API/SSE 流/静态资源/错误页）统一下发安全标头——`Content-Security-Policy`（仅本站资源，禁用 `object`，限制 `form-action`/`frame-ancestors`，放行内联脚本/样式与 HLS blob worker 避免误伤自身功能）、`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`、`Permissions-Policy`（默认禁用摄像头/麦克风/定位/传感器，仅放行本域剪贴板写入）、`Cross-Origin-Opener-Policy: same-origin`，以及**仅 HTTPS 请求下发**的 `Strict-Transport-Security`（避免锁死 HTTP 部署）；新增 `test_basic.py` 三项安全标头测试

* **音频独立上传页与详细进度条**：上传从列表页内嵌面板拆分为独立页面 `/music/upload`（`templates/music/upload.html` + `static/js/music_upload.js`），列表页/「我的音频」页改为跳转独立上传页；采用「异步任务 + 轮询进度」——上传请求立即返回 `task_id`，后台线程执行 ffmpeg 转码，前端分两阶段展示进度条（文件上传百分比 + ffmpeg 转码进度条），`ffprobe` 探测音频时长、解析 ffmpeg `-progress` 输出实时计算转码进度；**转码阶段在真实百分比未知时显示不确定态滑动动画进度条（`.is-indeterminate`），不再只有文字百分比**，成功后展示播放链接并可复制/再传一个，失败展示错误并可一键重试（`services/music_service.py` 新增 `start_upload`/`_run_upload_task`/`get_upload_progress`/`_probe_duration`，`config.py` 新增 `FFPROBE_BIN`，每个上传任务独立临时目录与 ffmpeg 子进程，多用户并发互不冲突）

* **音频列表与公开控制**：板块内展示全部公开音频与「我的音频」列表，用户可随时切换公开/私有；公开后所有用户（含未登录）可在游戏内大喇叭音频列表看到并播放

* **管理员后台管理**：新增「大喇叭音频管理」页，管理员可查看全部音频并一键下架（删除）

* **删除同步清理文件**：音频在数据库删除记录时同步删除 `uploads/music/<ID>/` 目录，无文件残留；数据库表 `music` 记录上传者/标题/公开状态/时间

* **内置 ffmpeg 自动调用**：Windows 调用 `scripts/ffmpeg/ffmpeg.exe`，Linux/macOS 调用 `scripts/ffmpeg/ffmpeg`，未内置时回退系统 PATH 中的 `ffmpeg`（config 新增 `FFMPEG_DIR`/`FFMPEG_BIN`）

* **公开音频审核机制**：申请公开的音频进入「待审核」，管理员在后台可试听并选择通过/驳回；通过后才在游戏内大喇叭展示，**驳回后音频自动转为私有**（用户可重新申请公开或删除）；已公开转私有再申请公开需重新审核。`music` 表以 `status`（0=私有 1=待审核 2=已公开，历史 3=已驳回 数据归并为私有）替代 `is_public`，历史公开数据自动迁移为「已通过」

* **音频审核结果邮件通知**：管理员通过/驳回公开申请后，自动向上传者邮箱发送审核结果邮件（后台线程异步发送，不阻塞请求）；邮件未启用或上传者无邮箱时自动跳过。`services/email/templates.py` 新增 `music_review_result()` 构建函数与 `templates/emails/music_review_result.html` 模板，`services/music_service.py` 新增 `get_author_email()` 查询上传者邮箱

* **公开音频名称搜索**：公开音频列表支持按名称模糊搜索（`GET /music?q=关键词`，`get_public_musics()` 新增 keyword 参数），展示搜索结果数与无结果空态，支持一键清除

* **「我的音频」独立页面**：原内嵌在公开列表页的「我的音频」拆分为单独页面 `/music/my`（`templates/music/my.html` + `static/js/music_my.js`），公开页顶部提供入口；公开/私有切换与删除操作通过 `next` 参数跳回来源页；公开页上传面板支持 `#upload-panel` 锚点自动展开

* **一键更新支持子目录不替换**：不替换列表现支持子目录路径（如 `scripts/ffmpeg`），命中后该子目录删除/复制阶段均跳过，完全保持本地现状（不被覆盖、不新增仓库文件、本地独有文件保留）；重构同步为 `_sync_item`（`_rmtree_skip_protected`/`_copy_tree_skip_protected`，删除带 Windows 文件占用重试），新增 3 个子目录/本地独有文件保护测试

* **ffmpeg 多线程转码**：新增 `FFMPEG_THREADS` 配置（0=自动按 CPU 核数，1=单线程降级），上传转码统一加 `-threads` 参数；每个上传任务是独立 ffmpeg 子进程与独立输出目录，多用户同时上传天然并行，不会出现「文件正在使用」冲突

* **一键更新保护本地资产**：更新同步新增「本地独有文件暂存恢复」机制——同步前暂存本地存在而仓库中没有的文件（如 `scripts/ffmpeg/` 下未入库的二进制），复制完成后自动恢复，解决更新后 ffmpeg 文件夹等本地资产被误删的问题（`services/updater.py` 新增 `_preserve_local_only`/`_restore_local_only`）

### 优化

* **邮件模板与官网风格完全一致**：`templates/emails/base.html` 配色由暗绿改为与官网 `static/css/base.css` 一致的**暗灰蓝 + 金色（#fbbf24）磨砂玻璃**——背景深灰蓝渐变 + 靛蓝/紫/金三色光晕、卡片玻璃渐变、金色顶部高光描边、光线散射层与噪点纹理，标题/链接/强调块统一金色；通过/失败/待审核状态卡分别用绿/红/金，验证码、指南审核、音频审核、广播邮件全部复用同一外层模板

* **管理中心数据统计调整**：移除已删除功能（投票活动/投票次数/征集/征集回复）的统计卡片，修复因 `polls`/`board_*` 表已从 schema 移除导致的管理中心 500 错误；新增「大喇叭音频」总数与「待审核大喇叭音频」数量统计（`routes/admin/pages.py` 与 `templates/admin/admin.html`）

* **邮件模板统一磨砂玻璃风格**：`templates/emails/base.html` 重做为暗绿金黄玻璃卡片，新增背景光晕、噪点纹理、光线散射层、顶部高光描边与通过/失败状态卡样式（`.mail-status-success` / `.mail-status-fail`），验证码 / 指南审核 / 音频审核 / 广播邮件共用同一外层与样式

* **邮件 HTML 全面统一风格**：`guide_review_result.html` 改用通过/失败状态卡（与音频审核邮件一致），`guide_review_pending.html` 新增待审核状态卡（`.mail-status-pending` 金黄色样式 + 时钟图标），`broadcast_message.html` 移除内联样式改为复用基础样式类（`mail-muted`/`mail-content`），所有邮件模板视觉风格统一

* **大喇叭音频页充分使用模板宏**：新增 `templates/macros/music_macros.html`，提取音频状态徽章（`music_status_badge`）、复制链接按钮（`music_copy_link_button`）、HLS 播放器（`music_audio_player`）为公共宏，`music/list.html` 与 `admin/admin_music.html` 统一调用，消除重复的内联代码；播放器补充磨砂玻璃质感样式（`.music-audio`）

* **统一全站进度条为磨砂玻璃质感**：新增 `.progress-track` / `.progress-fill` 组件（半透明磨砂轨道 + 渐变流光扫过动画 + 顶部高光 + 柔光晕），提供 `gold / green / blue / purple / red / yellow` 六种颜色变体与 `xs / sm / md / lg` 四档尺寸；一键更新、数据库备份、CPU/内存监控、背景上传、附件上传等所有进度条统一改用该组件，视觉一致且不削弱原有动效

* **充分使用模板宏**：新增 `templates/macros/progress.html` 进度条宏 `progress_track()`，`admin_update.html`、`admin_db_backup.html`、`performance.html`、`index.html` 统一通过宏生成进度条，消除重复的内联样式代码

### 重构

* **清理模板冗余**：移除 `base.html` 中未被任何页面覆写的空 `{% block nav %}`；进度条颜色切换由内联 `background` 改为语义化的 `progress-fill <variant>` 类

### 移除

* **彻底删除大喇叭实时直播台**：移除 `services/live_service.py`、`routes/main/live.py`、`templates/music/live.html`、`static/js/live.js`、`scripts/tests/test_live.py`，删除 `config.py` 中 `LIVE_BROADCAST_DIR`/`LIVE_HLS_SEGMENT_SECONDS`/`LIVE_HLS_LIST_SIZE`/`LIVE_IDLE_TIMEOUT`/`LIVE_MAX_DURATION` 等直播配置，`app.py` 移除 `live_service` 引用与清理，`routes/main/__init__.py` 移除直播路由，音频列表与管理后台移除「实时直播台」入口按钮；**保留 ffmpeg 多线程转码**（`FFMPEG_THREADS` 继续用于音频上传转码，多用户同时上传互不冲突）

* **彻底删除 MinIO 对象存储**：移除 `services/object_storage.py`、`config.py` 中 MinIO 相关配置、`app.py` 中 MinIO 初始化检查、`routes/main/media.py` 中 MinIO 引用改为本地文件存储、`services/user_service.py` 中 MinIO 清理逻辑改为本地文件清理；删除 `.env.example` 和 `docs/MINIO.md`

* **移除系统设置中的背景图片开关**：从 `SETTINGS_REGISTRY` 中移除 `ENABLE_BACKGROUND_IMAGE` 和 `BACKGROUND_FADE_IN_MS`，首页背景只保留上传按钮 + 图片预览弹窗

* **删除投票与征集功能**：彻底移除 `routes/community/polls.py`、`routes/community/board.py`、`services/poll_service.py`、`services/board_service.py`、`templates/community.html`，从数据库 schema 中移除 `polls`、`poll_options`、`poll_votes`、`board_topics`、`board_replies` 表，从导航和首页移除入口链接

* **彻底删除音频声音增益功能**：移除 `music` 表 `gain` 字段（迁移与插入代码）、`services/music_service.py` 中 `_clamp_gain`/`update_gain` 及 `_build_transcode_cmd`/`start_upload` 的 gain 参数与 `volume` 滤镜、`routes/main/music.py` 中 `POST /music/<id>/gain` 路由、`templates/music/upload.html` 音量增益滑块、`templates/music/my.html` 与 `templates/admin/admin_music.html` 的增益输入框、`static/js/music_upload.js` 增益逻辑与相关测试；上传转码保持纯 ffmpeg AAC/HLS 转码

* **驳回后音频自动转为私有**：管理员驳回公开申请后音频直接转为「私有」（`review_music` 由旧状态 3=已驳回 改为 0=私有），用户可重新申请公开或删除；历史「已驳回」（status=3）数据在展示与切换逻辑中归并为私有处理

### 优化

* **首页背景图片交互优化**：上传改用 XHR 异步 + 进度条，新增预览弹窗，点击预览按钮即可查看大图

* **全站文件上传进度条**：全局进度条自动拦截所有 `multipart/form-data` 表单提交，显示实时上传进度

* **指南卡片金色上边框优化**：渐变两端淡出，增加柔光晕效果，与玻璃质感卡片更融合

### 重构

* **终端彻底升级为 xterm.js**：用业界标准的分享终端模块 `terminal-xterm.js` 替代旧版自制 ANSI 字符网格渲染器，彻底修复「回车只输入不执行」「字符排版错乱」。字符绘制、光标、清屏、行宽、输入回显与本地终端完全一致；输入走 `term.onData` 将原始字节直送后端 PTY 驱动，回车即可执行；尺寸自适应（`xterm-addon-fit`）将行列数同步到 PTY，避免换行错位与黑屏

* **「CMD」全面改名为「脚本」**：后端包 `routes/cmd`→`routes/script`、蓝图 `cmd_bp`→`script_bp`、URL `/admin/cmd*`→`/admin/script*`，前端 `static/js/cmd`→`static/js/script`、模板 `admin_cmd_*.html`→`admin_script_*.html`，同步更新快捷命令/定时任务/终端/编辑器全部入口与可见文案，并同步测试用例与文档

### 新增

* **更新脚本机制**：创建 `scripts/uploads.py`，每次一键更新完成后自动执行（不存在则跳过），用于清理旧数据、迁移文件等；`scripts/migrate_uploads.py` 委托 `uploads.py` 并可触发静态资源构建

* **复原「弹窗终端」且无独立入口**：脚本控制台不再有「实时终端」按钮；点击任意快捷命令/脚本卡片的「运行」即自动打开弹窗终端（`terminal-modal.js`）并在其中执行——Shell 命令发到共享持久 PTY 会话、脚本走后端 SSE 独立子进程。顶栏提供「中断/清屏/重置/关闭」，`Esc` 或点击遮罩可关闭

* **MiniScript 解除安全限制**：删除 AST 沙箱校验、危险函数黑名单、双下划线属性保护、循环次数限制与运行时长限制，脚本可无限循环、无限运行；仅保留独立子进程隔离与资源访问控制作为「防误炸服务器」底线

* **退出网页即强制终止脚本**：前端监听 `visibilitychange`/`pagehide`/`beforeunload` 主动上报终止，后端以心跳监控线程兜底，覆盖意外关闭浏览器/tab 崩溃场景

* **定时任务调度优化**：改为按到期时间升序排队、每秒判断一次，不再每轮全表扫描；新增「运行中任务」面板，实时查看已触发的脚本

* **直接运行任务**：任务卡片「立即执行」直接运行，不受超时限制，可一路运行到底，并在「运行中任务」中查看

* **任务级最大超时**：创建/编辑定时任务时可单独设置「最大超时时间（秒）」，超时自动终止（直接运行不受此限制）

### 修复

* **修复实时终端「回车只输入不执行」与排版错乱**：改用 xterm.js 渲染 + PTY 字节级输入，输入回车由终端驱动真实执行并回显（详见上方「重构」）

* **修复弹窗终端初始黑屏/尺寸为 0**：为终端容器固定高度、每次显示弹窗时重新 `fit`、并限制后端 `/resize` 只在合法尺寸（≥2×2）时回传，杜绝初始零尺寸容器触发 `400`

* **修复 DuckDBRow 在 Debian 下** **`description`** **列数多于实际行数据导致** **`dict(r)`** **崩溃**：构造时自动以 `None` 补齐，确保 `dict(行)` 总是安全返回

* 修复定时任务「创建定时任务」「执行日志」按钮无反应：`scheduled.js`/`scheduled-logs.js` 移入 `extra_script` 块，确保在 `page_modals` 弹窗 DOM 渲染后再加载绑定

* 修复快捷命令「运行/编辑/删除」按钮无反应：`presets.js` 事件绑定读取 ID 时改用与模板一致的 `dataset.scriptId`（原误用 `dataset.cmdId`），模态框选择器同步为 `script-modal`/`script-form`

* 修复脚本编辑器输入区无法输入：Monaco 加载路径由不存在的 `loader.min.js` 改为正确的 `loader.js`

### 优化

* **终端升级为伪终端（跨平台）**：SSH 式交互体验，Python `input()`/readline 原生可用、输入回显与行编辑正确、清屏与 ANSI 光标控制真实响应、输出实时流式返回；移除前端强制插入的 `$` 提示符，只保留真正的命令提示符。Unix/macOS 走原生 `os.openpty()`，**Windows 无 pty/termios，改用 pywinpty（ConPTY）提供同等的真伪终端**（未安装 pywinpty 时自动回退到管道实现，避免启动失败；`requirements.txt` 已按平台标记引入 `pywinpty`）

* 构建脚本 `build_static.py` 新增 xterm.js 本地化下载（`xterm.min.js`/`xterm.min.css`/`addon-fit.min.js`），写入 `static/lib/xterm/`

* **清理历史遗留命名**：`CmdPresets`→`ScriptPresets`、`__abortCmdScript`→`__abortRunningScript`，删除编辑器退出上报中一处无意义的错误兜底逻辑

* 文档体系二次整合，最终精简为单一入口：

  * 将 `docs/ARCHITECTURE.md` 与 `docs/cmd-guide.md` 内容完整并入 `README.md`（架构、目录结构与技术栈；CMD 控制台使用说明），删除两文件

  * `README.md` 成为唯一综合文档入口（总览/快速开始/功能/配置/API/架构/CMD 使用说明），`docs/` 仅保留开发准则与更新日志

  * `docs/DEVELOPMENT.md` 新增「文档写入准则」章节，明确文档结构、命名规范、内容组织与更新流程

  * 修正各处指向已删除文档的链接（README 文档索引、DEVELOPMENT 引用）

  * 复制 `README.md` 到 `docs/README.md` 作为镜像副本，并修正其内部相对链接使其在 docs/ 目录下可用

  * 精简 CMD 控制台说明中的 MiniScript 介绍：删除大段 Python 语法教程（变量/运算/条件/循环/列表/字典/函数/类/异常等），改为一句「语法与 Python 一致」，具体语法参考 Python 文档

* 导航栏性能优化：`.glass-nav-inner` 的 `translateX(-50%)` 改为 `translate3d(-50%,0,0)` 提升为独立合成层，并 `will-change: transform, backdrop-filter` 缓存磨砂模糊，滚动时不再逐帧重模糊；移除无益的 `will-change: width, border-radius`

  * 视觉与磨砂玻璃效果保持不变，仅降低滚动期的重绘/重合成开销

* 重构项目文档结构，按职责拆分，消除"乱塞"：

  * 新增 `docs/ARCHITECTURE.md`：架构分层、目录结构、技术栈、异步架构、数据库设计、一键更新机制（从 README/DEVELOPMENT/DEPLOYMENT 迁移）

  * `docs/DEVELOPMENT.md` 整合为「开发与部署规范」：分层规范/易错点/测试/路由检测 + 构建打包与发布流程 + 更新规则（吸收原 README 开发注意事项与 DEPLOYMENT 内容）

  * 移除 `docs/DEPLOYMENT.md`（一键更新机制并入 ARCHITECTURE，其余并入 DEVELOPMENT）

  * `README.md` 精简为总览 + 快速开始 + 功能特性 + 配置 + API，并补充「文档索引」统一入口

* 图形验证码字体加大：`services/captcha.py` 字体从 40 提升到 52，画布增至 300×96，并增加左右留白避免旋转后裁切；弹窗/表单中验证码图片显示高度从 `h-16` 提升到 `h-20`，整体更清晰易读

* 指南提交改为「点击提交审核后再弹验证码」：移除 `guides/form.html` 内联验证码字段，改为隐藏字段 + 全局 `CaptchaModal` 弹窗

  * 点击「提交审核」按钮后才弹出图形验证码，验证通过才真正提交表单

  * 验证码出错时弹窗内直接刷新验证码，**不刷新页面**，保留已填写的标题/摘要/正文内容

### 修复

* 修复 `/admin/guides` 预览弹窗无法滚动：预览卡片作为 flex 子项默认 `min-height:auto` 导致内容撑破 `max-h-[85vh]`，`overflow-y-auto` 失效；为卡片补加 `min-h-0` 使其可收缩，预览内容超长时可正常纵向滚动

* 修复打开首页白屏：页面入场动画改用纯 CSS animation 自动播放，不再依赖 `base.js` 在 `DOMContentLoaded` 添加类显示

  * 原实现用 `.js .page-content{opacity:0}` 常驻隐藏内容，显示依赖 body 末尾同步脚本 `base.js`；脚本加载慢/失败时内容长时间不可见 → 白屏

  * 新实现元素首次渲染即自动播放入场动画，脚本加载问题不再导致白屏；JS 禁用时内容默认可见

  * 同步更新 `DEVELOPMENT.md` 易错点 #4，记录避免白屏的方法

### 优化

* 导航栏收缩动画流畅化修复：改用 `width` 数值过渡 + `translateX(-50%)` 居中，替代无法插值的 `max-width:auto`/`margin:auto`，彻底消除切换跳变

  * 弹性曲线 `cubic-bezier(0.34, 1.3, 0.64, 1)` + 0.45s，更迅捷自然，带轻微回弹

  * 新增 `will-change` 提升合成层，动画更顺滑

* 导航栏增强：向下滚动后收缩为居中漂浮的椭圆胶囊，细腻磨砂玻璃质感

  * 滚动前为顶部通栏磨砂条，滚动超过 32px 后收缩为居中椭圆胶囊（`max-width: 68rem` + `border-radius: 999px`），两侧留白

  * 磨砂质感更凝实：提高背景不透明度、`backdrop-filter: blur(40px) saturate(140%)`、顶部渐变高光细线、双层内阴影

  * 弹性缓出动画（`cubic-bezier(0.22, 1, 0.36, 1)`），滚动状态切换流畅

  * 尊重系统「减少动态效果」偏好（`prefers-reduced-motion`）

  * 新增 `initNavShrink()`（`main.js`）监听滚动，`base.html` 导航栏包裹 `.glass-nav-inner` 胶囊容器

* 一键更新下载进度条优化：成功开始下载 ZIP 压缩包后进度条正常实时推进

  * 服务器未返回 `Content-Length` 时按估算大小推进进度，避免进度条卡死

  * 改用"变化阈值"触发回调（每 1% 或每 512KB），进度平滑且不漏最终值

  * 下载完成时强制回调 100，避免进度跳变

  * 直连 GitHub 下载路径同样接入进度回调，不再无进度显示

  * 新增 `scripts/tests/test_updater.py` 覆盖 Content-Length 已知/未知两种下载场景

* 磨砂玻璃 UI 全面升级：去除塑料感，模拟真实酸蚀刻玻璃效果

  * 卡片/按钮/弹窗/输入框/导航栏改用 `linear-gradient` 渐变背景，替代纯色 `rgba`

  * 降低 `backdrop-filter` 饱和度（`saturate(220%)` → `saturate(100%)`），效果更自然通透

  * 添加光线散射伪元素（`radial-gradient` 模拟漫射光），模拟磨砂玻璃内部光线散射

  * 添加边缘光晕伪元素（`mask-composite` 渐变边框），模拟玻璃切割面折射

  * 降低背景透明度（`0.18` → `0.08~0.10`），让背景光晕充分透出

  * 全局噪点纹理优化（`fractalNoise` 频率降低、增加去饱和度），微观蚀刻感更真实

  * 添加环境光晕叠加（`body::after`），模拟玻璃微弱冷色/暖色环境反光

  * 背景光球透明度降低（`0.85` → `0.50`），模糊半径增大（`60px` → `80px`），光晕更柔和

  * 统一所有页面内联玻璃样式

* `uploads/` 目录按功能分类重组：附件归 `uploads/attachments/`、背景图片归 `uploads/backgrounds/`、社区文件归 `uploads/community/`，根目录不再堆文件

* 新增**全站背景图片**功能：可在 `config.py` 或管理后台「系统设置→背景图片」中开启/关闭

  * 背景图片存放在 `uploads/backgrounds/`，命名规范 `bg_<比例>.jpg/webp/png`（如 `bg_16_9.jpg`）

  * 前端自动检测屏幕宽高比（`16:9`/`16:10`/`4:3`/`9:16`/`3:4`/`1:1`），请求匹配的背景图

  * CSS `background-size: cover` + 暗化覆层（`rgba(7,18,12,0.35)`）确保文字可读性，加载时淡入过渡

  * 图片由 `background/<比例>` 路由提供，服务端精确匹配或降级到第一张可用背景图，无图片时静默不显示

  * 关闭时完全恢复默认玻璃光晕背景，零开销（`index.html`、`settings.html`、`guides/index.html`、`register.html`、`admin/admin_mod_intros.html`、`admin/admin_cmd.html`、`base.html`）

### 重构

* 统一 Markdown 编辑器组件：新建 `templates/macros/markdown_editor.html` 宏 + 共享脚本 `static/js/markdown-editor.js`，覆盖广播邮件、指南编辑、讨论帖创建等 4 个页面，消除重复的内联样式与脚本

* 移除 highlight.js 代码语法高亮（CSS/JS/语言包约 200KB），代码块改为原生 `<pre><code>` 渲染，性能与资源体积优化，保留一键复制功能（`base.js` 的 `CodeBlocks` 模块）

* 邮件 Markdown 渲染移除 `codehilite` 扩展，改用邮件客户端兼容的基础 HTML 标签，修复自定义 Markdown 邮件无法正常显示的问题

* 图形验证码弹窗模块化：将验证码弹窗 HTML 提取到 `base.html`，JS 逻辑提取到 `base.js` 的 `CaptchaModal` 全局对象，消除 `register.html` 和 `forgot_password.html` 中的重复代码

* 邮箱唯一性检查：注册和修改邮箱时检查邮箱是否已被其他账号使用，确保一个邮箱仅可注册一个账号

### 修复

* 彻底修复端点名不一致导致的 500：除 `/settings` 外，`routes/discussion/api.py` 的 `delete_reply`/`toggle_pin`/`toggle_lock`/`delete_topic` 原带 `_view` 后缀，与模板 `url_for('discussion.delete_reply')` 等端点不匹配，讨论区删除/置顶/锁定操作会抛 `BuildError`。已统一移除 `_view` 后缀并对 service 导入用别名（`svc_*`）避免递归

* 新增回归测试防止此类低级 bug 再现：`test_routes.py` 增加「登录后渲染关键页面返回 200」与「模板中所有 `url_for` 端点必须已注册」两项检测

* 修复管理后台「删除用户」接口对任何用户均返回 500：`routes/admin/users.py` 漏导入 Flask 的 `request` 对象导致 `NameError`

* 修复静态资源构建脚本 `build_static.py` 项目根目录路径计算错误：原 `SCRIPT_DIR/..` 指向 `scripts/`，导致构建产物写入错误目录，全新部署无法加载静态资源

* 新增静态检查脚本 `scripts/tests/check_undefined_names.py` 并集成进测试套件，自动扫描"使用但未定义/未导入"的名字，防止同类 NameError 运行时错误回归

* 修复 DuckDB 多进程并发写入假阳性错误：`_is_mp_child_process()` 检测结果模块级缓存，避免多次调用时 `sys.argv` 或 `multiprocessing.current_process().name` 产生假阳性

* `AsyncLogWriter` 和 `LogCleaner` 容错增强：捕获 `get_db()` 抛出的 `RuntimeError`，在子进程中静默跳过而非崩溃

### 新增

* 外部链接配置化：卫星地图网址、QQ 群链接可在管理后台在线编辑（热重载）

* 注册页面图形验证码改为点击"发送验证码"按钮后弹窗，优化交互流程

* `MAP_URL` 和 `QQ_GROUP_URL` 配置项，支持管理后台实时修改

* 广播邮件页面 Markdown 编辑器升级为分栏布局（编辑区 + 实时预览区），支持工具栏、滚动同步

* 一键更新功能：从 GitHub 自动获取并覆盖代码文件，智能代理检测，自动重启（`services/updater.py`）

* 代码块一键复制：Markdown 代码块使用原生 `<pre><code>` 渲染，鼠标悬停时显示复制按钮，点击复制代码并反馈"已复制"状态

* 图形验证码（服务端内存存储、一次性删除防重放）

* 邮箱验证码（SMTP）

* IP 频率限制

* 异步日志写入与自动清理

* DuckDB 数据库兼容层

### 修复

* 修复发布指南/编辑指南时图形验证码缺失的问题：在表单中添加验证码字段，路由中增加 `captcha_service.verify()` 校验

* 修复控制台日志（`services/logger.py`）显示 `127.0.0.1` 的问题：`log()` 函数自动使用 `get_client_ip()` 获取真实客户端 IP，统一与访问日志的 IP 判断逻辑

* 修复验证码文字渲染：每个字符独立随机颜色 + 轻微上下抖动，增强安全性

* 删除首页顶部导航栏（特色玩法、模组介绍、服务器理念、加入我们）

* 一键更新：移除空命令时系统自动处理启动的 fallback 逻辑，统一使用 `{python} app.py` 默认命令

* 修复 `/performance` 页面 500 错误：`url_for` 端点名从 `api.performance` 修正为 `api.api_performance`

* 修复 `/admin/broadcast` 发送广播按钮无反应：脚本移入 `extra_script` 块，确保 `page_modals` 中的弹窗元素已加载

* 广播邮件页面移除了 `var body` 与 `document.body` 的变量名冲突

* 注册页面移除内联图形验证码，统一为弹窗方式

* 注册表单提交不再重复验证图形验证码（已在邮箱发送时验证）

* 讨论区回复实时刷新功能（默认 5 秒间隔，仅后台可配置）

* 讨论区回复分段加载（分页加载 + "加载更多"按钮）

* 发表回复窗口移至回复列表上方，优化交互流程

* 删除回复改为 AJAX 异步操作，无需刷新页面

* 回复实时刷新只获取最新回复，不对已加载内容重复请求

### 优化

* 图形验证码逻辑精简：仅在邮箱验证码发送时校验，不再冗余校验

* 数据库查询仅返回必要字段，减少网络传输

* 前端 `Set` 去重机制，避免重复渲染

* 回复列表改为 JS 动态渲染，减少初始页面加载时间

* 管理后台模板统一移入 `templates/admin/` 子目录，按功能分类整理模板文件

* 新增 `templates/emails/` 邮件模板目录，与页面模板分离

* 重新生成 Tailwind CSS 静态文件（`static/css/tailwind.css`）

### 修复

* **修复音频播放器只能播放列表第一个音频**：`static/js/music_player.js` 初始化时在收起弹层代码处误引用未定义的 `root` 变量（应为 `self.root`），抛出 `ReferenceError` 中断了所有播放器的初始化循环，导致只有第一个 `.music-player` 被实例化、其余播放器无法播放；改为 `self.root.addEventListener(...)` 后每个播放器均可独立播放

* **修复音频倍速/音量控件被遮挡**：`.mp-speed-menu` 与 `.mp-vol-slider` 的 `z-index` 由 30 提升至 100，并移除 `.pixel-card` 的 `overflow: hidden`（改为 `visible`），弹层不再被卡片裁切、正确显示在其他内容之上

***

## \[2024-01-15] 之前版本

### 新增

* 指南编辑功能重构为独立页面，修复弹窗滚动问题

* 统一网页弹窗系统，替换浏览器原生 alert/confirm

* 前端移动端彻底适配

* 统一邮件 HTML 模板模块

* 公开文件/目录管理功能

* 数据库在线备份功能（DuckDB ATTACH + COPY FROM DATABASE）

* 持久交互式终端（session-based shell 子进程）

* MiniScript 脚本执行引擎

* 定时任务调度引擎

* 服务器指南系统（审核工作流、封禁管理）

* 讨论帖子系统（分类、标签、附件、置顶、锁定）

* 征集系统（多附件上传）

* 投票系统

* 模组介绍

* 服务器性能监控

* CMD 控制台

* 用户系统（注册、登录、密码修改）

* 图形验证码（服务端内存存储、一次性删除防重放）

* 邮箱验证码（SMTP）

* IP 频率限制

* 异步日志写入与自动清理

* DuckDB 数据库兼容层

### 修复

* 注册页面验证码弹窗居中问题

* 用户注册验证码重复验证失败问题

* 讨论详情页操作后重定向到社区页问题

* 管理页面预览按钮无响应问题

* 指南编辑后重定向错误问题

* 前端 Lucide 图标名错误

* 实时预览不能在窗口内滚动问题

* 验证码安全性增强（扩大答案空间、服务端存储）

* 跨平台子进程兼容性（Windows/Unix）

* Windows 终端输出重复问题

* DuckDB 多进程并发文件锁定问题

* 日志服务包导入错误

* 邮件 SMTP 连接参数错误

* MiniScript 编辑器输出重复问题

* 终端与 MiniScript 架构重构（稳定性提升）

### 优化

* 整体代码结构优化，删除无用代码

* Tailwind CDN 迁移为本地静态构建

* 前端模块化拆分（editor.js、scheduled.js）

* 跨平台子进程基础设施统一迁移到 core/

* 多线程异步架构

