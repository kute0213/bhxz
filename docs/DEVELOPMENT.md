# 开发准则

> 本文档为**开发与部署规范**：分层规范、代码规范、易错点清单、测试与路由检测，构建打包与发布流程，以及文档写入准则。
> 架构分层与目录结构见 [README.md 架构](../README.md#架构)。

## 文档写入准则

本项目采用**精简文档体系**：除开发准则（`docs/DEVELOPMENT.md`）与更新日志（`docs/CHANGELOG.md`）外，其余内容统一并入 `README.md`。任何功能、代码或配置变更，都必须同步更新对应文档。

### 1. 文档结构规范

- **README.md**：项目总览、快速开始、功能特性、配置说明、API 接口、架构、脚本控制台使用说明
- **docs/DEVELOPMENT.md**（开发准则）：分层规范、代码规范、易错点、测试、路由检测、构建打包与发布、文档写入准则
- **docs/CHANGELOG.md**（更新日志）：版本更新日志，按时间倒序排列

> 不要新增独立文档。确有必要时，需先在 README 的「文档索引」登记并说明理由，否则视为乱塞。

### 2. 命名规范

- 文件名使用小写字母，单词间用连字符（-）分隔，如 `cmd-guide.md`
- 章节标题使用 Markdown 标题语法，层级分明（`#` 到 `#####`）
- API 接口文档按「方法 路径 - 说明」格式描述

### 3. 内容组织

- 每个文档开头添加目录，方便快速导航
- 技术文档应包含：背景、实现方式、使用示例、注意事项
- 代码示例使用 ``` 代码块，并指定语言类型
- 关键步骤使用有序列表，并列项使用无序列表

### 4. 更新流程

- 每次功能/代码变更后，更新 `README.md` 对应章节与 `docs/CHANGELOG.md`
- 删除或重命名文档时，同步修正所有指向它的链接（含 README 文档索引、DEVELOPMENT 引用）
- 变更完成后按开发准则流程（分层规范 → 易错点清单 → 测试与构建）过一遍再提交

## 分层总览

项目遵循 **MVC 式分层架构**，调用方向固定为：

```
app.py ──→ routes/（HTTP 薄层）──→ services/（纯业务逻辑）──→ core/（基础设施）
```

各层职责规约：

| 层级 | 目录 | 职责 | 禁止 |
|------|------|------|------|
| **入口** | `app.py` | Flask 实例、蓝图注册、WSGI 服务器 | 不得包含业务逻辑 |
| **路由** | `routes/` | HTTP 请求解析、参数校验、Session 管理、响应构造 | 不得包含 SQL、事务、业务逻辑 |
| **服务** | `services/` | 纯业务逻辑，Flask 无关，返回 `(success, data_or_error)` 元组 | 不得导入 Flask、不得直接操作 request/session |
| **核心** | `core/` | 数据库连接、认证装饰器、中间件 | 不得包含业务逻辑，不得导入 services |

## 路由层规范（routes/）

路由层是**薄层**，每个视图函数只做 3 件事：

```python
@main_bp.route('/example', methods=['POST'])
@login_required
def example():
    # 1. 从请求中提取参数
    user = get_current_user()
    value = request.form.get('value', '').strip()

    # 2. 调用 service 执行业务
    success, result = some_service.do_something(user_id=user['id'], value=value)

    # 3. 构造 HTTP 响应
    if success:
        flash(result, 'success')
    else:
        flash(result, 'error')
    return redirect(url_for('main.settings'))
```

**禁止：**
- 在路由中编写 SQL 语句（`conn.execute(...)`）
- 在路由中处理事务（`conn.commit() / conn.rollback()`）
- 在路由中处理文件系统操作
- 在不同路由间复制粘贴业务逻辑（应抽取到 service）

## 服务层规范（services/）

服务层是**纯业务逻辑层**，不依赖 Flask：

```python
def do_something(user_id, value, ip_address):
    """业务描述。返回 (success, data_or_error)。"""
    conn = get_db()
    try:
        # ... 业务逻辑 ...
        conn.commit()
        log('Module', '操作成功', user_id=user_id, ip=ip_address)
        return True, '操作成功'
    except Exception:
        conn.rollback()
        return False, '操作失败'
    finally:
        conn.close()
```

**规则：**
- 所有函数返回 `(success, data_or_error)` 元组
- `success` 为 `bool` 类型
- 日志记录在服务层统一完成（`from services.logger import log`）
- 禁止导入 `flask`、`request`、`session`、`render_template`、`redirect`、`flash`
- 数据库连接仅通过 `get_db()` 获取，用完必须 `close()`

## 核心层规范（core/）

核心层提供基础设施，不包含任何业务逻辑：

- `core/db/` — 数据库连接封装
- `core/auth.py` — 认证装饰器、密码哈希
- `core/middleware.py` — 请求中间件

## 新增功能的流程

1. 在 `services/` 中创建或扩展对应的服务函数
2. 在 `routes/` 中创建薄层路由，调用服务函数
3. 在 `scripts/tests/` 中编写测试覆盖

## 代码复用原则

发现重复代码时，正确做法是**抽取到 services**，而非复制粘贴：

- 附件处理始终使用 `services/attachment_service.py`
- 用户操作始终使用 `services/user_service.py`

- 讨论区操作始终使用 `services/discussion_service.py`

## 测试规范

测试文件位于 `scripts/tests/`，运行：

```bash
python scripts/tests/run_all.py
```

测试套件包含两类检查：
1. **静态检查**（`check_undefined_names.py`）：扫描所有 Python 文件，找出"使用但未定义/未导入"的名字，防止 NameError 类运行时错误（如漏导入 `request`）
2. **功能测试**：`test_*.py` 中的单元与集成测试

每个测试函数应：
- 测试成功路径
- 测试失败路径（边界条件、权限不足、参数错误）
- 使用 `app.test_client()` 模拟 HTTP 请求
- 使用 `db` 事务隔离避免测试间相互影响

## 易错点清单（新增代码前必查）

以下规则来自实际线上事故，**每次新增/修改路由和模板时必须逐条检查**：

### 1. 路由函数名 ≡ 模板 `url_for` 端点名（最常见 Bug）

Flask 默认以**函数名**作为端点名（`蓝图名.函数名`），模板中 `url_for('蓝图名.函数名')` 必须与之完全一致。

**检查清单：**
- [ ] 每个 `@蓝图.route()` 的函数名都对应模板中的 `url_for('蓝图名.函数名')`
- [ ] 不要加 `_view`、`_handler`、`_action` 等后缀（除非模板也用了这个后缀）
- [ ] 当路由函数名与 service 导入的函数名冲突时，用 `import ... as svc_xxx` 解决
- [ ] 已运行 `python scripts/tests/run_all.py`，其中 `test_routes.py` 会自动校验模板中所有 `url_for` 端点均已注册，并验证登录后关键页面渲染返回 200（可捕获此类 500）

### 2. 模板渲染必须端到端验证

修改模板或路由后，必须用 `curl` 或浏览器访问一次，确认不报 500：

```bash
# 匿名访问
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/discussion
# 应返回 200
```

**检查清单：**
- [ ] 匿名用户访问（无 cookie）
- [ ] 普通用户访问（有 session cookie）
- [ ] 管理员访问
- [ ] 有数据时访问 vs 无数据时访问

### 3. 数据库迁移兼容

修改表结构时，必须使用 `add_column_if_not_exists` 模式，确保老数据库兼容：

```python
# 在 core/db/schema.py 的 migrate 部分添加：
add_column_if_not_exists('表名', '列名', '类型 DEFAULT 默认值')
```

不要在 `CREATE TABLE IF NOT EXISTS` 中修改已有表的列定义——那对已存在的表无效。

### 4. 页面入场动画不得依赖 JS 显示（避免白屏）

**背景**：曾用 `opacity:0` 常驻隐藏内容、再由外部脚本在 `DOMContentLoaded` 时添加类显示。
问题：`base.js` 是 body 末尾的**同步脚本**，它不加载完就不会触发 `DOMContentLoaded`；
一旦脚本加载慢/失败，页面会长时间保持 `opacity:0`（黑底），表现为"打开首页白屏一下"。

**正确做法**：用**纯 CSS animation 自动入场**，不依赖 JS 添加类：

```css
.js .page-content {
    animation: page-in 0.45s cubic-bezier(0.4, 0, 0.2, 1) both;
}
@keyframes page-in {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
}
body.page-leaving .page-content {
    animation: none;   /* 离开动画时取消入场动画 */
    opacity: 0;
    transform: translateY(-8px);
    transition: opacity 0.3s ease, transform 0.3s ease;
}
```

**检查清单：**
- [ ] 内容显示不依赖外部 JS 添加类（`opacity:0` 隐藏 + 类切换显示的方式慎用）
- [ ] 入场动画用 CSS `animation` 自动播放，元素首次渲染即生效
- [ ] 若 JS 禁用（`html` 无 `.js` 类），内容应默认可见，无动画
- [ ] `body.page-leaving` 时用 `animation: none` 取消入场动画，避免与离场过渡冲突
- [ ] 修改 `base.css` 后必须同步 bump `templates/base.html` 中的版本号（`v='15'`）

### 5. 弹窗与模态框的放置位置

全屏弹窗/模态框应放置在 `{% block page_modals %}` 中（在 `</main>` 之后渲染），**而非** `{% block content %}` 内，避免 `page-content` 的 `transform` 影响 `position: fixed` 定位。

**检查清单：**
- [ ] 模态框位于 `page_modals` block，不在 `content` block 内

### 6. 图形验证码必须走统一模块

全局验证码弹窗 HTML 位于 `base.html`，JS 逻辑位于 `base.js` 的 `CaptchaModal` 对象。页面通过 `CaptchaModal.show(hint, callback)` 或 `window.__showCaptchaModal(hint, callback)` 调用。

**指南提交示例**：`guides/form.html` 不在模板内联渲染验证码，而是点击「提交审核」后再弹 `CaptchaModal`，验证通过才提交表单；验证码出错时弹窗内刷新验证码、不刷新页面，避免重置已填内容（表单保留隐藏的 `captcha`/`captcha_id` 字段）。

**检查清单：**
- [ ] 使用了全局 `CaptchaModal`，而非自行内联渲染验证码图片/输入框
- [ ] 注入 `CaptchaModal.show` 时，若脚本位于页面中间（`base.js` 加载前），需用 `DOMContentLoaded` 包裹，确保 `CaptchaModal` 已定义
- [ ] 验证码出错不应刷新整个页面（避免丢表单内容）

## 路由检测配置

### 1. 新增路由时必须同步更新检测脚本

所有路由必须注册到 `scripts/tests/test_routes.py` 的 `ROUTES` 列表中，否则路由检测将无法覆盖新增路由。

**每次新增路由流程：**
1. 在 `routes/` 中注册新路由
2. 在 `scripts/tests/test_routes.py` 的 `ROUTES` 列表中添加对应条目
3. 运行 `python scripts/tests/test_routes.py` 验证新路由可达
4. 提交代码

### 2. ROUTES 条目格式

```python
# (路径, HTTP方法, 预期状态码列表, 认证要求, 备注)
# 认证要求: False=公开, True=需登录, 'admin'=需管理员权限

# 公开页面
('/discussion', 'GET', [200], False, '讨论区'),

# 需登录（未登录预期 302 跳转）
('/settings', 'GET', [302, 401], True, '设置页'),

# 需管理员（未登录预期 302/403）
('/admin', 'GET', [302, 401, 403], 'admin', '管理后台'),

# 静态文件
('/static/css/style.css', 'GET', [200, 304], False, 'CSS文件'),
```

### 3. 规则

- **新增路由后必须添加检测条目** — 这是硬性要求，否则路由检测覆盖不全
- 公开页面预期 `200`，认证页面预期 `302/401/403`（未登录）
- POST 路由只需测试不返回 500（空表单请求应返回 400/302 等合理状态码）
- 如果有特殊参数或 Header 需求，在 `test_post_routes()` 函数中添加自定义测试逻辑
- 静态文件预期 `200` 或 `304`

### 4. 检查清单

- [ ] 新路由已在 `ROUTES` 列表中添加
- [ ] 预期状态码正确（公开页面 200，认证页面 302/401/403）
- [ ] 已运行 `python test_routes.py` 验证通过

### 6. Markdown 渲染与代码复制

所有 Markdown 渲染页面必须遵循以下规则：

**渲染流程：**
1. 使用 `marked.js` 解析 Markdown 为 HTML
2. 渲染完成后调用 `CodeBlocks.enhance(element)` 注入代码块一键复制按钮

> 说明：已移除 highlight.js 语法高亮以减小静态资源体积、提升性能。代码块使用原生 `<pre><code>`
> 渲染，仅保留一键复制功能。

**已集成的 Markdown 渲染页面：**
| 页面 | 渲染方式 | 复制触发 |
|------|----------|----------|
| `guides/detail.html` | 直接 `marked.parse()` | `CodeBlocks.enhance()` |
| `discussion/detail.html` | 初始内容 + 动态回复 | `CodeBlocks.enhance()` + MutationObserver |
| `docs.html` | 动态加载 | `CodeBlocks.enhance()` |

**新增 Markdown 渲染页面的步骤：**
1. 在页面中加载 `marked.js`
2. 使用 `marked.parse()` 渲染 Markdown 内容
3. 渲染后立即调用 `CodeBlocks.enhance(containerElement)` 注入复制按钮

**代码复制按钮说明：**
- 复制按钮在 `base.js` 的 `CodeBlocks` 模块中实现
- 鼠标悬停代码块时显示复制按钮，点击复制按钮复制代码内容
- 复制成功后按钮显示"已复制"和绿色反馈，2秒后恢复
- 支持 `navigator.clipboard` 和 `document.execCommand('copy')` 双保险
- 动态加载的内容通过 MutationObserver 自动检测并增强

**检查清单：**
- [ ] 页面加载了 `marked.js`
- [ ] Markdown 渲染后调用了 `CodeBlocks.enhance()`
- [ ] 动态加载的内容会被 MutationObserver 自动捕获

### 7. 路由层使用 Flask 对象必须导入（NameError 事故）

路由层使用 `request`、`flash`、`redirect`、`url_for`、`abort`、`render_template`、
`jsonify`、`session` 等 Flask 对象时，**必须**在文件顶部 `from flask import ...` 中显式导入。
漏导入会在运行时抛 `NameError`，导致整个请求 500。

```python
# ❌ 错误：用了 request 但没导入
from flask import render_template, redirect, url_for, flash, abort

@admin_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    _svc_delete_user(user, user_id, request.remote_addr)  # NameError → 500

# ✅ 正确
from flask import render_template, redirect, url_for, flash, abort, request
```

> 真实事故：`routes/admin/users.py` 漏导入 `request`，导致「删除用户」接口对任何用户都返回 500。
> 这类错误与具体数据无关，漏一行 import 就会全接口失效。

**预防措施：** 静态检查脚本已集成进测试套件，会自动扫描"使用但未定义/未导入"的名字：
`python scripts/tests/run_all.py`（内置 `check_undefined_names` 静态检查）。

**检查清单：**
- [ ] 路由层用到的每个 Flask 对象都已在 `from flask import ...` 中导入
- [ ] 已运行 `python scripts/tests/run_all.py`（含静态检查）确认通过

## 构建与发布

### 1. 安装与启动

```bash
pip install -r requirements.txt
python app.py          # 默认监听 0.0.0.0:5000
```

生产环境监听端口、HTTPS、登录保护等在 `config.py` 中配置。

### 2. 直接部署（CherryPy 内置）

默认使用内置 Cheroot WSGI 服务器，无需反向代理即可独立运行：

```bash
python app.py                    # HTTP
export ENABLE_SSL=1 && python app.py  # HTTPS
```

#### Nginx 反向代理（可选）

生产环境推荐前置 Nginx，代理到内置服务器：

```nginx
server {
    listen 80;
    server_name your-domain.com;
    client_max_body_size 50m;   # 允许大文件上传

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # 关键：SSE 长连接，保证实时日志/进度/终端不中断
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_chunked_transfer_encoding off;
    }
}
```

> **SSE 依赖**：实时进度条、定时任务日志、交互终端均依赖 SSE 长连接，Nginx 必须
> 关闭缓冲（`proxy_buffering off`）并调大读超时，否则连接会中断。

#### 开启 HTTPS（内置服务器）

1. 将证书文件放到 `ssl/` 目录：`ssl/server.crt`、`ssl/server.key`
2. Nginx 上启用 HTTPS，将 HTTP 转 HTTPS

未找到证书或未设置 `ENABLE_SSL` 时，自动回退 HTTP 模式。

### 3. 构建静态资源

前端使用本地化的第三方库（Lucide、marked、Monaco Editor 等），需要通过构建脚本下载：

```bash
python scripts/build/build_static.py
```

- 下载 Lucide、marked、字体及 Monaco Editor（约 12MB）到 `static/lib/`
- 结果写入 `static/lib/lib-version.json`
- `static/lib/monaco/`（~12MB）被 `.gitignore` 排除，**不提交到 Git**
- 用户通过一键更新或从 GitHub 下载 ZIP 后，都需要运行此命令以补齐 Monaco

### 4. 打包 ZIP 发布

每次代码变更后，打包为 ZIP 压缩包供用户通过一键更新下载：

```bash
# 1. 构建静态资源（下载所有 CDN 资源到本地，包括 Monaco）
python scripts/build/build_static.py

# 2. 打包发布 zip（自动排除敏感文件与大型目录）
python scripts/build/package.py

# 3. 确认所有文件已提交并推送（触发一键更新）
git status
git push
```

打包脚本自动排除：数据库、上传文件、备份、日志、SSL 证书、`.env`、Monaco、`node_modules`、`.git` 等。

### 5. 完整发布流程（示例命令）

```bash
cd /workspace
python scripts/tests/run_all.py        # 1. 测试套件通过
python scripts/build/build_static.py   # 2. 构建静态资源
python scripts/build/package.py        # 3. 打包 zip
git add -A                             # 4. 暂存（确认 .gitignore 生效）
git commit -m "..."                    # 5. 提交
git push origin main                   # 6. 推送，触发一键更新（见 README.md 一键更新机制）
```

## 更新规则

- 每次代码变更后必须运行 `python scripts/build/build_static.py` 验证构建通过
- 提交前检查 `.gitignore` 确保敏感文件不被提交
- 推送到 GitHub 后，一键更新即可生效
- 修改 `base.css`/`base.js` 后必须同步 bump 模板中的版本号，避免浏览器缓存
- 一键更新的**机制原理**见 [README.md 一键更新机制](../README.md#一键更新机制)

### 更新脚本机制

每次一键更新完成（文件同步完成后、服务器重启前），会自动尝试运行 `scripts/uploads.py`：

- 如果 `scripts/uploads.py` 存在，则执行它，用于清理旧数据、迁移文件等
- 如果 `scripts/uploads.py` 不存在，则静默跳过，不影响更新流程
- 执行超时 120 秒，超时后自动跳过并继续重启

**`scripts/uploads.py` 职责：**

1. **清理旧数据**：删除已废弃功能的数据（如投票、征集等）及其关联的附件文件
2. **迁移文件**：将 `uploads/` 根目录中散乱的文件按功能分类迁移到子目录
3. 在更新完成后自动运行，无需手动调用

**`scripts/migrate_uploads.py` 职责：**

1. 委托 `scripts/uploads.py` 执行清理与迁移
2. 可选构建静态资源（`--build` 参数触发 `scripts/build/build_static.py`）
3. 用于需要手动迁移的场景，或作为一键更新的补充

**开发准则：**

- 新增需要更新后自动清理的数据时，在 `scripts/uploads.py` 的 `_clean_polls_data()` 类似函数中添加对应逻辑
- 新增文件分类目录时，在 `scripts/uploads.py` 的文件迁移部分添加对应规则
- 确保 `scripts/uploads.py` 可独立运行且幂等（多次运行不影响结果）
- 不需要自动运行脚本时，删除 `scripts/uploads.py` 即可（更新器自动跳过）