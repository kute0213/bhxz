# 开发准则

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
├── templates/                # Jinja2 模板
├── docs/                     # 项目文档
└── scripts/tests/          # 自动化测试
```

## 新增功能的流程

1. 在 `services/` 中创建或扩展对应的服务函数
2. 在 `routes/` 中创建薄层路由，调用服务函数
3. 在 `scripts/tests/` 中编写测试覆盖

## 代码复用原则

发现重复代码时，正确做法是**抽取到 services**，而非复制粘贴：

- 附件处理始终使用 `services/attachment_service.py`
- 用户操作始终使用 `services/user_service.py`
- 投票操作始终使用 `services/poll_service.py`
- 征集操作始终使用 `services/board_service.py`
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

```python
# ❌ 错误：函数名带 _view 后缀，模板却用 url_for('community.create_poll')
@community_bp.route('/poll/create', methods=['POST'])
def create_poll_view():          # 端点 → community.create_poll_view
    ...

# ✅ 正确：函数名就是模板要用的名字
@community_bp.route('/poll/create', methods=['POST'])
def create_poll():                # 端点 → community.create_poll
    ...

# 模板中必须一致：
# <form action="{{ url_for('community.create_poll') }}">
```

**检查清单：**
- [ ] 每个 `@蓝图.route()` 的函数名都对应模板中的 `url_for('蓝图名.函数名')`
- [ ] 不要加 `_view`、`_handler`、`_action` 等后缀（除非模板也用了这个后缀）
- [ ] 当路由函数名与 service 导入的函数名冲突时，用 `import ... as svc_xxx` 解决
- [ ] 已运行 `python scripts/tests/run_all.py`，其中 `test_routes.py` 会自动校验模板中所有 `url_for` 端点均已注册，并验证登录后关键页面渲染返回 200（可捕获此类 500）

### 2. 模板渲染必须端到端验证

修改模板或路由后，必须用 `curl` 或浏览器访问一次，确认不报 500：

```bash
# 匿名访问
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/community
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
('/community', 'GET', [200], False, '社区首页'),

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

### 5. 路由函数名避免与 service 导入名冲突

```python
# ❌ 错误：视图函数 vote_poll 与导入的 vote_poll 同名
from services.poll_service import vote_poll

@community_bp.route('/poll/<int:poll_id>/vote', methods=['POST'])
def vote_poll(poll_id):           # 覆盖了 import 的 vote_poll！
    result = vote_poll(...)       # 递归调用自身，报错

# ✅ 正确：用别名
from services.poll_service import vote_poll as svc_vote_poll

@community_bp.route('/poll/<int:poll_id>/vote', methods=['POST'])
def vote_poll(poll_id):
    result = svc_vote_poll(...)   # 正确调用 service
```

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

## 发布与更新流程

### 1. 打包 ZIP 发布

每次代码变更后，需要打包为 ZIP 压缩包供用户通过一键更新下载：

```bash
# 1. 构建静态资源（下载所有 CDN 资源到本地，包括 Monaco Editor）
python scripts/build/build_static.py

# 2. 确认所有文件都已提交到 Git
git status

# 3. 推送到 GitHub（触发一键更新）
git push
```

> **注意：** `static/lib/monaco/` 目录（~12MB）被 `.gitignore` 排除，不会提交到 Git 仓库。
> 用户通过一键更新或从 GitHub 下载 ZIP 后，需要运行 `python scripts/build/build_static.py` 以获取 Monaco Editor。

### 2. 一键更新机制

用户通过管理后台的「一键更新」功能，从 GitHub 获取最新代码：

1. 系统自动检测最快代理，下载 GitHub 仓库的 ZIP 压缩包
2. 解压后同步到本地（跳过受保护文件：数据库、配置、上传文件等）
3. 自动运行 `scripts/build/build_static.py` 构建静态资源
4. 自动重启服务器

> 更新机制详见 `services/updater.py`。

### 3. 更新规则

- 每次代码变更后必须运行 `python scripts/build/build_static.py` 验证构建通过
- 提交前检查 `.gitignore` 确保敏感文件不被提交
- 推送到 GitHub 后，一键更新即可生效