# 开发准则

> 本文档规定本项目的**分层、编码、模板、测试、构建发布与文档**规范。架构总览与快速开始见 [README](../README.md)，接口细节见 [API 指南](API.md)。

## 目录

- [1. 分层规范](#1-分层规范)
- [2. 编码规范](#2-编码规范)
- [3. 模板与前端规范](#3-模板与前端规范)
- [4. 数据库与 ID](#4-数据库与-id)
- [5. 日志规范](#5-日志规范)
- [6. 测试规范](#6-测试规范)
- [7. 构建、打包与发布](#7-构建打包与发布)
- [8. 核心易错点](#8-核心易错点)
- [9. 需求落地检查清单](#9-需求落地检查清单)
- [10. 文档写入准则](#10-文档写入准则)

---

## 1. 分层规范

调用方向固定：

```
app.py ──→ routes/（HTTP 薄层）──→ services/（纯业务逻辑）──→ core/（基础设施）
```

| 层级 | 目录 | 职责 | 禁止 |
| --- | --- | --- | --- |
| 入口 | `app.py` `config.py` | Flask 实例、蓝图注册、WSGI 服务器、配置注册表 | 业务逻辑 |
| 路由 | `routes/` | 请求解析、参数校验、Session、响应构造 | SQL、事务、文件系统业务操作、业务规则 |
| 服务 | `services/` | 纯业务逻辑，返回 `(success, data_or_error)` | 导入 Flask / request / session |
| 核心 | `core/` | DB 连接、认证、中间件、日志、共享工具 | 业务逻辑、导入 services |

### 1.1 路由层

每个视图只做三件事：取参数 → 调 service → 构造响应。

```python
@main_bp.route('/example', methods=['POST'])
@login_required
def example():
    user = get_current_user()
    value = request.form.get('value', '').strip()
    success, result = some_service.do_something(user['id'], value)
    flash(result, 'success' if success else 'error')
    return redirect(url_for('main.settings'))
```

禁止在路由中写 SQL、`commit/rollback`、复制业务逻辑。AJAX 与普通表单需要同时兼容时，统一提供 `_is_ajax()` / `_respond()` 辅助。

### 1.2 服务层

- 所有函数返回 `(success, data_or_error)`。
- 仅通过 `get_db()` 获取连接，`finally` 中 `close()`；异常时 `rollback()`。
- 日志使用 `from core.system.logger import log`。
- 不导入任何 Flask 符号。

```python
def do_something(user_id, value, ip_address):
    conn = get_db()
    try:
        # ... 业务 ...
        conn.commit()
        log('INFO', 'Module', '操作成功', user_id=user_id, ip=ip_address)
        return True, '操作成功'
    except Exception:
        conn.rollback()
        return False, '操作失败'
    finally:
        conn.close()
```

### 1.3 核心层

只提供通用能力：`core/db`、`core/auth`、`core/csrf`、`core/middleware`、`core/system`、`core/shared`、`core/seo`、`core/errors`。不得包含业务判断。

---

## 2. 编码规范

- Python 4 空格缩进，函数 / 类使用 docstring 说明业务语义。
- 新增模块按职责拆分（参考 `services/mail/`：`delivery` / `service` / `retry`），避免单文件膨胀。
- 统一使用 `next_id()` 生成业务主键（雪花 ID），禁止退回自增 ID。
- 文件路径拼接必须做路径穿越校验（`core/shared` 或既有安全函数），Windows 盘符路径单独处理。
- 对外跳转使用 `url_for()`；外部链接由服务端补全协议。
- 新增高频接口必须使用独立限流桶，禁止直接调高全局 `API_RATE_LIMIT_PER_MINUTE`。
- 定时任务统一注册到 `core/shared/scheduler`，禁止自建 `threading.Timer`。

---

## 3. 模板与前端规范

### 3.1 目录

- **唯一前端目录**：`static/`。模板在 `static/templates/`（Flask `template_folder`），样式在 `static/css/`，脚本在 `static/js/`。
- 模板按业务分目录：`admin/`、`auth/`、`settings/`、`site/`、`buildings/`、`guides/`、`music/`、`live/`、`bots/`、`backgrounds/`、`emails/`、`macros/`。
- 管理后台页面使用统一骨架 `admin/_layout.html`（无 `admin_` 文件前缀）。

### 3.2 模板规范

- 页面继承 `base.html`；局部通过 `extra_head` / `extra_style` / `extra_script` 注入。
- 通用 UI 抽到 `static/templates/macros/`：模态框、Markdown 编辑器、进度条、音乐播放器、页面内搜索、日历选择器。
- **按需引入资源**：只在使用日历的页面调用 `calendar_styles()` / `calendar_script()`；不要在 `base.html` 全站加载。
- 静态资源 URL 带 `v=` 版本号（Tailwind、业务 CSS / JS），修改后 bump，避免浏览器缓存旧文件。
- 颜色使用 `:root` 变量（`--glass-bg` / `--glass-blur` 等），禁止硬编码白色系。
- 公共样式统一放在 `static/css/base.css` 的对应分区，禁止在页面 `extra_style` 重复定义。

### 3.3 前端交互约定

- **日期 / 时间输入**：统一使用 `calendar_field()`（`macros/calendar.html`），禁止原生 `date` / `datetime-local`。
- **弹窗**：使用 `macros/modal.html` 或 `.modal-overlay` + `open` class；滚动锁由 `base.js` 的 `syncModalScrollLock()` 自动处理，不要单独改 `body.style.overflow`。
- **悬浮提示**：使用 `title` 或 `data-tooltip`，由 `base.js` 统一渲染。
- **直播地址**：必须使用同源相对路径（`/live/stream/<ID>.mp3`），禁止用 `request.host_url` 拼接。
- **直播 ID 拼接**：使用 `channelUrl(tpl, id)`，禁止手写 `replace('/0/', ...)`。
- **操作后刷新**：写操作成功后必须自动刷新受影响元素。优先在页面注册 `window.registerPageRefresh(fn)`，由通用 `admin-action` 处理器在成功后调用；自定义 `fetch` 写操作直接调用 `window.refreshPageData()`。刷新函数应通过现有 API 重新拉取数据并更新列表、计数、徽章与空状态，禁止让用户手动刷新；只有完全没有列表 API 的页面才允许整页刷新兜底。

### 3.4 Tailwind

模板或 JS 新增 Tailwind 工具类后必须重新编译 `static/css/tailwind.css`，并 bump `base.html` 中的版本号。否则会出现按钮丢失内边距、圆角失效等问题。

---

## 4. 数据库与 ID

- 连接统一 `get_db()`，用完 `close()`；写操作显式 `commit()`，异常 `rollback()`。
- 业务主键统一 `next_id()`（雪花算法）。表主键即使是 INTEGER，写入值也保持雪花量级。
- 需要原子性的「先查后插」必须放进同一事务（参考 `services/live/store.transaction()`）。
- 数据库文件：`uploads/db/site.db`；防火墙 DuckDB；访问日志抓取期间临时生成 `access_logs.duckdb`。

---

## 5. 日志规范

所有日志经 `core/system/logger.py`：

| 类别 | 入口 | 存储 | 控制台 |
| --- | --- | --- | --- |
| 全局 | `log(level, event, detail, **kwargs)` | `logs/app.log` + 环形缓冲 + SSE `global` | 受 `LOG_CONSOLE_ENABLED` 控制 |
| 严重错误 | `log_fatal(...)` | `logs/fatal.log`（每次覆盖） | 始终打印 |
| 模块 | `register_module_log(name)` + `log_module(...)` | 模块缓冲 + 可选 `logs/modules/<name>.log` | 默认不打印 |

- 等级：`DEBUG < INFO < WARNING < ERROR < CRITICAL`。
- 启动时 `purge_logs_on_startup()` 清空全部日志文件与缓冲。
- 禁止绕过 logger 直接 `print` 或写日志文件。

---

## 6. 测试规范

```bash
python -m compileall -q core services routes config.py
python -m pytest scripts/tests -q
```

- 测试位于 `scripts/tests/`，按功能命名（`test_seo.py`、`test_public_files.py`、`test_live_*.py` 等）。
- 新增业务优先补纯函数测试（命令构造、校验、解析、分页）。
- 涉及权限、路径穿越、限流、状态机的改动必须补回归测试。
- 提交前必须保证全量测试通过。

---

## 7. 构建、打包与发布

| 操作 | 命令 |
| --- | --- |
| 下载第三方静态资源 | `python scripts/build/build_static.py` |
| 编译 Tailwind | `cd scripts/build && npx tailwindcss -c tailwind.config.js -i tailwind-source.css -o ../../static/css/tailwind.css --minify` |
| 打包发布 zip | `python scripts/build/package.py` |

发布 zip 排除数据库、上传、备份、SSL、日志与第三方大文件，输出到 `release/`（不提交）。

### Git 提交约定

- 提交作者必须仅为 `kute0213 <3846415473@qq.com>`，不得出现 `trae-solo-agent` 等协作作者。
- 提交说明使用中文，概括本次变更。
- 不提交 `.screenshots/`、运行期数据库、上传文件、备份与日志。
- 推送前先确认 `git status` 与测试结果。

---

## 8. 核心易错点

### 8.1 认证、CSRF 与限流

- `/api/*` 豁免 CSRF；`/admin/api/*` **不豁免**，AJAX 写操作要带 `X-CSRF-Token`。
- `@login_required` / `@admin_required` 只有在请求被判定为 JSON/AJAX 时才返回 JSON；前端 `fetch` 请带 `X-Requested-With: XMLHttpRequest`。
- 未登录访问 `/api/live/*` 不应占用普通限流桶的异常路径；PCM / Opus 使用独立桶。
- 修改 `ROUTE_PREFIXES` 或中间件跳过逻辑时，注意 `'/'` 会让所有路径命中，曾导致公开文件映射全部 404。

### 8.2 音频直播

- 一个频道一个 ffmpeg 进程，同时输出 HLS 与 MP3；禁止为每个听众单独启动 ffmpeg。
- 实时录音输入**禁止**加 `-thread_queue_size`；必须保留 `-probesize 32 -analyzeduration 0` 与 MP3 的 `-flush_packets 1`。
- Opus 服务端只转发，不解码、不转码、不落盘；不可用时静默回退 MP3。
- 不提供直播音量 / 速度调整接口，避免重启 ffmpeg 打断听众。
- MP3 开场快照约 0.3 秒（8KB），Opus 快照约 120ms，不可调大。
- 停止直播必须删除 `uploads/live/<ID>/`，并向 MP3 / Opus 两类订阅者发送结束信号。
- 每人循环直播上限由 `LIVE_MAX_LOOP_PER_USER` 控制，实时录音固定 1 路；必须在事务内校验。

### 8.3 内容与资源

- 指南资源受 `GUIDE_RESOURCE_MAX_MB` 限制（1~1024MB），上传前后都要校验。
- 指南替换草稿：已发布指南首次编辑会复制为 `replace_of` 草稿，审核通过后接管原 ID。
- 所有用户 Markdown / HTML 内容必须经过 `services/firewall/protection/content_filter` 注入检测。
- 文件服务与资源路由必须做路径穿越校验，禁止直接拼接用户输入。

### 8.4 静态资源与缓存

- 修改 `static/css/*`、`static/js/*`、Tailwind 后必须 bump 引用版本号。
- 新增 Tailwind 类必须重新编译产物，否则线上无样式。
- 图标库保持同步加载，并在 `DOMContentLoaded` 兜底 `lucide.createIcons()`。

### 8.5 备份、邮件与调度

- 邮件统一走 `email_service.send(...)`；失败邮件进入 `email_retry_queue`，由统一调度器每 60 秒重试，最多 10 次。
- 备份默认目录 `../bhxz_backups`，可在系统设置热改；备份包含 SQLite / DuckDB 一致快照。
- 定时任务统一使用 `core/shared/scheduler` 注册，禁止新建线程 / Timer。

### 8.6 Windows 与部署

- Windows 路径可能是 `C:\...` 或 `D:/...`，路径解析需同时兼容。
- 中文 Windows 控制台需 UTF-8 环境变量，部署脚本必须包含 `chcp 65001` 与 `PYTHONUTF8=1`。
- 反向代理场景下媒体地址使用同源相对路径，避免 CSP `media-src 'self'` 拦截。

---

## 9. 需求落地检查清单

新增页面 / 功能时逐项确认：

1. 路由是否放在正确蓝图，是否使用 `@login_required` / `@admin_required`。
2. 业务逻辑是否下沉到 `services/`，路由是否保持薄层。
3. 写操作是否处理 CSRF（非 `/api/*`）。
4. 列表是否分页，分页大小是否走系统设置。
5. 用户输入是否做长度、类型、注入与路径校验。
6. 是否按需引入 CSS / JS，静态资源版本号是否更新。
7. 是否复用现有宏与公共样式，是否有重复实现。
8. 是否补充测试；`compileall` 与 `pytest` 是否通过。
9. 是否更新 `README.md`（功能 / 配置变化）与 `docs/CHANGELOG.md`。
10. 公开网站功能是否保留管理员控制台；账户功能是否支持用户自行修改密码。

---

## 10. 文档写入准则

### 10.1 文档结构

| 文档 | 职责 |
| --- | --- |
| `README.md` | 项目总览、快速开始、目录结构、功能、配置、API 概览、架构 |
| `docs/API.md` | 逐接口详细说明（方法、鉴权、参数、响应、错误、限流、实现文件） |
| `docs/DEVELOPMENT.md` | 开发准则（本文件） |
| `docs/CHANGELOG.md` | 当前版本更新日志，按时间倒序 |
| `docs/CHANGELOG_*.md` | 历史更新日志归档 |
| `docs/mcsm-deploy.md` | 面板部署指南 |
| `docs/SECURITY_REPORT.md` | 安全评估报告 |

> 不新增独立文档。确有必要时，先在 README 的「文档索引」登记并说明理由。

### 10.2 写作规范

- 文件名小写 + 连字符；章节层级清晰（`#` ~ `#####`）。
- 每个文档开头放目录。
- 接口按「方法 + 路径 — 说明」描述，字段用表格，示例用带语言标注的代码块。
- 代码示例必须可直接运行或可直接对照实现。
- 删除 / 重命名文档时同步修正所有链接。

### 10.3 更新流程

1. 功能或配置变更后更新 `README.md` 对应章节。
2. 接口新增 / 修改 / 删除时同步更新 `docs/API.md`。
3. 在 `docs/CHANGELOG.md` 的 `## [Unreleased]` 下记录变更。
4. 运行 `compileall` 与 `pytest`。
5. 按「核心易错点」自检后提交，提交说明使用中文。
