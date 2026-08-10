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
└── .trae/server-test/        # 自动化测试
```

## 新增功能的流程

1. 在 `services/` 中创建或扩展对应的服务函数
2. 在 `routes/` 中创建薄层路由，调用服务函数
3. 在 `.trae/server-test/` 中编写测试覆盖

## 代码复用原则

发现重复代码时，正确做法是**抽取到 services**，而非复制粘贴：

- 附件处理始终使用 `services/attachment_service.py`
- 用户操作始终使用 `services/user_service.py`
- 投票操作始终使用 `services/poll_service.py`
- 征集操作始终使用 `services/board_service.py`
- 讨论区操作始终使用 `services/discussion_service.py`

## 测试规范

测试文件位于 `.trae/server-test/`，使用 `pytest` 运行：

```bash
cd .trae/server-test && python run_all.py
```

每个测试函数应：
- 测试成功路径
- 测试失败路径（边界条件、权限不足、参数错误）
- 使用 `app.test_client()` 模拟 HTTP 请求
- 使用 `db` 事务隔离避免测试间相互影响