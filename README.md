# 滨海小镇 · Minecraft 服务器社区网站

基于 **Flask + Waitress** 的 Minecraft 服务器社区门户，采用白色磨砂玻璃（White Frosted Glass）设计风格。提供用户系统、游戏账号申请、公共建筑、服务器指南、大喇叭音频、音频直播、假人申请、管理后台、服务器状态监控、全站背景图片与搜索引擎优化等能力。

## 文档索引

| 文档 | 说明 |
| --- | --- |
| 本文档 | 项目总览、快速开始、目录结构、功能、配置、架构 |
| [docs/API.md](docs/API.md) | **API 指南**：逐接口说明方法、鉴权、参数、响应、错误码、限流与实现文件 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发准则：分层规范、代码规范、易错点、测试、构建发布、文档规范 |
| [docs/mcsm-deploy.md](docs/mcsm-deploy.md) | MCSManager 面板部署指南（Windows / Linux） |
| [docs/SECURITY_REPORT.md](docs/SECURITY_REPORT.md) | 安全风险自评估报告（OWASP 逐项） |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 更新日志（当前版本） |
| [docs/CHANGELOG_ARCHIVE_2026-11-22.md](docs/CHANGELOG_ARCHIVE_2026-11-22.md) | 历史更新日志归档 |

## 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装与启动

```bash
pip install -r requirements.txt
python scripts/build/build_static.py   # 首次运行：下载图标库与字体到 static/lib
python app.py
```

默认 HTTP 模式，监听 `0.0.0.0:5000`。启动后会在 `uploads/db/site.db` 初始化数据库，并自动创建默认管理员。

### Windows 编码提示

中文 Windows 控制台默认 GBK，直接 `python app.py` 可能出现中文日志乱码或 `UnicodeEncodeError`。请先开启 UTF-8：

```bat
chcp 65001
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
python app.py
```

长期部署（尤其是 MCSM 等面板）请把上述变量写入启动脚本，详见 [docs/mcsm-deploy.md](docs/mcsm-deploy.md)。

### 默认管理员

| 用户名 | 密码 |
| --- | --- |
| `admin` | `admin1324` |

> 首次登录后请立即在「账户设置」修改默认密码。

## 静态资源与发布

### 构建第三方静态资源

```bash
python scripts/build/build_static.py
```

下载并本地化：Lucide Icons、Marked.js、JetBrains Mono、站酷庆科黄油体、站酷快乐体。字体按 `unicode-range` 分片，零外部 CDN 依赖；构建产物已随仓库提交。

### 重新编译 Tailwind

模板或 JS 中新增 / 修改 Tailwind 工具类后必须重新生成 `static/css/tailwind.css`：

```bash
cd scripts/build
npm install            # 仅首次
npx tailwindcss -c tailwind.config.js -i tailwind-source.css \
    -o ../../static/css/tailwind.css --minify
```

编译后同步 bump `static/templates/base.html` 中 `css/tailwind.css` 的 `v=` 版本号，避免缓存旧样式。

### 打包发布 zip

```bash
python scripts/build/package.py
```

输出 `release/bhxz-YYYYMMDD-HHMMSS.zip`（排除数据库、上传、备份、SSL、日志与第三方大文件）。`release/` 与 `*.zip` 已在 `.gitignore` 中。

## 目录结构

```
/workspace
├── app.py / config.py / requirements.txt   # 入口、配置、依赖
├── core/                 # 基础设施层（不含业务逻辑）
│   ├── db/               #   数据库连接与 schema
│   ├── system/           #   应用初始化、日志
│   ├── shared/           #   雪花 ID、IP、验证码、限流、校验、调度器
│   ├── auth.py           #   认证装饰器、密码哈希
│   ├── csrf.py           #   CSRF 防护
│   ├── middleware.py     #   安全标头、攻击扫描、公开文件服务
│   ├── helpers.py        #   render_page / admin_page
│   ├── seo.py            #   结构化数据与 SEO 辅助
│   └── errors.py         #   精简错误页
├── services/             # 业务逻辑层（纯 Python，不依赖 Flask）
│   ├── backup/  buildings/  mail/  game_accounts/  game_server_ban/
│   ├── system_metrics/  music/  live/  rcon/  user/  bot_applications/
│   ├── background_service/  cleanup_service/  content_limits/
│   ├── firewall/         #   防火墙（DuckDB 引擎 + WSGI 门禁 + DDoS + API 限流）
│   ├── security/         #   攻击特征扫描
│   ├── settings_manager/  sitemap_cache/  indexnow/
├── routes/               # HTTP 路由层（Flask Blueprint）
│   ├── main/             #   主站（认证/设置/头像/音频）
│   ├── api/              #   公开 API（统计/验证码/邮箱）
│   ├── admin/            #   管理后台（20+ 子模块）
│   ├── buildings/ guides/ music/ live/ game_accounts/ bots/
│   ├── backgrounds/ docs/ public/ sitemap/ indexnow/ community/
├── static/               # 前端唯一目录：静态资源 + Jinja2 模板
│   ├── css/ js/ favicons/ lib/
│   └── templates/        #   base.html、页面模板、macros/ 通用宏
├── docs/                 # 项目文档
├── scripts/              # build/ 构建脚本、tests/ 测试
├── uploads/              # 运行期上传（guides/ backgrounds/ music/ live/ db/）
├── backups/              # 自动维护备份（默认 ../bhxz_backups，可配置）
└── ssl/                  # HTTPS 证书（可选）
```

## 功能特性

### 界面与交互

- **白色磨砂玻璃主题**：统一 `--glass-bg` / `--glass-blur` 变量与 `.glass-panel` / `.glass-surface`，深色背景下不发灰。
- **自定义悬浮提示**：`title` / `data-tooltip` 统一替换为磨砂气泡，自动翻转与避让视口。
- **自研日历选择器**：`macros/calendar.html` 的 `calendar_field()`，按需引入 CSS/JS，不依赖原生 `date` / `datetime-local`。
- **弹窗滚动锁**：`base.js` 的 `syncModalScrollLock()` 统一锁定背景滚动，阻止滚轮穿透。
- **操作后自动刷新**：统一 `admin-action` 事件 + `window.refreshPageData()`，管理后台与用户操作完成后自动通过 API 重新拉取数据，同步列表、计数、徽章与统计卡片，无需手动刷新页面。
- **全站 SEO / GEO**：`meta robots`、description、canonical、OG / Twitter 卡片、JSON-LD、Bing 验证码、私有页 `noindex` 与 `X-Robots-Tag`。
- **Sitemap 与 robots.txt**：只收录公开规范 URL，支持 ETag / 304；`Crawl-delay` 兼顾抓取与防火墙。
- **IndexNow 主动推送**：管理后台一键提交公开 URL，定时任务接入统一调度器，根目录提供 `/<key>.txt` 校验。

### 用户与账户

- 注册 / 登录 / 找回密码：群内验证码 + 邮箱验证码 + 图形验证码多重验证。
- 账户设置：修改用户名、密码、邮箱、头像，注销账号；**所有用户均可自行修改密码**。
- 邮箱唯一性约束；登录失败锁定与图形验证码升级。

### 内容与社区

- **公共建筑**：发布（审核）、搜索、标签、收藏、评论分页、举报。
- **服务器指南**：Markdown 编写、图片 / 视频资源上传与转码、草稿 / 审核 / 替换草稿、收藏、编辑封禁（不再提供封面字段）。
- **大喇叭音频**：上传（支持 `mp3 / wav / ogg / m4a / flac / mp4`，mp4 自动提取音轨转码）、HLS 播放、标签、收藏、公开审核。
- **音频直播**：循环播放与实时录音两种模式，HLS + MP3 + Opus 低延迟输出，支持麦克风设备 / 音量 / 降噪调整。
- **游戏账号**：注册申请与封禁申请（RCON 执行与到期自动解封）。
- **假人申请**：生成坐标 / 下线时间，审批后 RCON 生成，到期自动下线。
- **背景图片**：上传审核、按屏幕比例自动挑选、全站背景开关。

### 管理后台

- 用户、权限、游戏账号、封禁、假人、建筑、指南、音频、直播、背景、指南封禁。
- **系统设置**：在线编辑、热更新，覆盖日志、自动维护、Sitemap、IndexNow、安全、防火墙、邮件、直播、分页、RCON、备案等分类。
- **防火墙**：IP / 账号封禁、白名单、可疑访问拦截、DDoS 防护、API 限流。
- **日志中心**：全局日志、严重错误日志、模块日志，SSE 实时推送与按来源过滤。
- **访问日志抓取**、**广播邮件**、**公开路径映射**、**模组介绍**、**自动维护备份**。

## 配置

所有可热更新配置集中在 `config.py` 的 `SETTINGS_REGISTRY`，登录后台「系统设置」即可修改，无需重启。主要分类：

| 分类 | 关键配置 |
| --- | --- |
| 日志 | `LOG_LEVEL`、`LOG_CONSOLE_ENABLED` |
| 自动维护 | `BACKUP_DIR`、`BACKUP_SCHEDULED_TIME`、`MAX_BACKUPS` |
| Sitemap | `SITE_URL`、`SITEMAP_DOMAINS`、`ROBOTS_POLICY`、`BING_SITE_VERIFICATION` |
| IndexNow | `INDEXNOW_ENABLED`、`INDEXNOW_KEY`、`INDEXNOW_AUTO_SUBMIT`、`INDEXNOW_SUBMIT_TIME` |
| 安全配置 | `SESSION_LIFETIME`、`MAX_LOGIN_ATTEMPTS`、`LOGIN_LOCKOUT_TIME` |
| IP 封禁 | `FIREWALL_WHITELIST`、`AUTO_BAN_*` |
| 内容注入 / 可疑访问 / DDoS / API 防火墙 | `CONTENT_INJECTION_*`、`SUSPICIOUS_BLOCK_*`、`DDOS_GUARD_*`、`API_RATE_LIMIT_*` |
| 邮件配置 | `EMAIL_ENABLED`、`SMTP_*`、`SMTP_SENDER_NAME` |
| 音频直播 | `LIVE_MAX_LOOP_PER_USER` |
| 列表分页 | `BUILDINGS_PER_PAGE`、`MUSIC_PER_PAGE`、`GUIDES_PER_PAGE` 等 |
| 指南资源 | `GUIDE_RESOURCE_MAX_MB` |
| 外部链接 | `MAP_URL`、`QQ_GROUP_URL` |
| 背景图片 / 网站图标 | `SHOW_BACKGROUND`、`BACKGROUND_IMAGE_SIZE`、`FAVICON_ICON` |
| 服务器配置 | `SERVER_HOST`、`SERVER_PORT`、`DEBUG_MODE`、`WAITRESS_THREADS` |
| RCON 配置 | `RCON_HOST`、`RCON_PORT`、`RCON_PASSWORD`、`MC_GAME_FOLDER` |
| 网站备案 | `SHOW_BEIAN`、`ICP_BEIAN`、`POLICE_BEIAN`、版权信息 |
| 内容审核 / 假人 | `MAX_PENDING_*`、`BOT_PENDING_LIMIT`、`BOT_SPAWN_COMMAND`、`BOT_KILL_COMMAND` |

部分启动期参数仍可由环境变量覆盖（如 `SECRET_KEY`、`FFMPEG_THREADS`、`BACKUP_DIR`、防火墙默认值）。

## API 概览

完整接口文档见 [docs/API.md](docs/API.md)。核心约定：

- **认证**：Flask Session Cookie；`@login_required` / `@admin_required` 对 AJAX 返回 401/403 JSON。
- **CSRF**：`/api/*` 豁免；其余写请求需 `csrf_token` 或 `X-CSRF-Token`。
- **限流**：`/api/*` 与 AJAX 默认每 IP 60 次/分钟；PCM / Opus 上传使用独立配额。
- **响应**：统一 `{"success": bool, "message": ...}`，HTTP 状态码区分错误类型。

主要接口前缀：

| 前缀 | 说明 |
| --- | --- |
| `/api/stats`、`/api/server-status` | 站点统计与服务器状态 |
| `/api/captcha/*`、`/api/email/*` | 图形验证码、邮箱验证码 |
| `/api/settings/*` | 用户名、密码、邮箱、头像、注销 |
| `/api/music/*` | 大喇叭音频 |
| `/api/guides/*` | 服务器指南与资源 |
| `/api/buildings/*` | 公共建筑 |
| `/api/backgrounds/list` | 背景图片 |
| `/api/game-accounts/*` | 游戏账号申请与封禁 |
| `/api/bots/*` | 假人申请 |
| `/api/live/*` | 音频直播 |
| `/api/docs/*` | 站内文档 |
| `/admin/api/*` | 管理后台全部接口 |

## 架构

调用方向固定：

```
app.py ──→ routes/（HTTP 薄层）──→ services/（纯业务逻辑）──→ core/（基础设施）
```

| 层级 | 职责 | 禁止 |
| --- | --- | --- |
| `app.py` | Flask 实例、蓝图注册、WSGI 服务器 | 业务逻辑 |
| `routes/` | 请求解析、参数校验、Session、响应构造 | SQL、事务、业务逻辑 |
| `services/` | 纯业务逻辑，返回 `(success, data_or_error)` | 导入 Flask、操作 request/session |
| `core/` | 数据库连接、认证、中间件、日志、共享工具 | 业务逻辑、导入 services |

详细分层规范、模板规范、测试命令与易错点见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 安全与运维

- **防火墙**：DuckDB 高性能引擎，WSGI 入口先于业务逻辑拦截；支持 DDoS、SQL 注入、XSS、路径穿越、命令注入、敏感文件探测、恶意 UA 检测与自动封禁。
- **API 限流**：按 IP 计数，超限返回 429；刷新页面自动重置。
- **自动维护**：每日定时备份 `/uploads/`（含 SQLite / DuckDB 一致快照），按保留数量清理旧备份与日志。
- **日志**：全局日志、严重错误日志（只保留最后一次）、模块独立日志；启动时自动清空。
- **部署**：Windows / Linux 面板部署见 [docs/mcsm-deploy.md](docs/mcsm-deploy.md)；安全评估见 [docs/SECURITY_REPORT.md](docs/SECURITY_REPORT.md)。

## 开发与测试

```bash
python -m compileall -q core services routes config.py
python -m pytest scripts/tests -q
```

提交前请按 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 的分层规范 → 易错点 → 测试与构建流程自检，并同步更新相关文档。
