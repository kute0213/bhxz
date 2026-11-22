# API 指南

> 本文档逐一说明本站所有 HTTP 接口：方法、路径、鉴权、请求字段、响应字段、错误码、限流与 CSRF 规则，并给出所属路由文件，便于定位实现。
>
> 相关文档：[README](../README.md) · [开发准则](DEVELOPMENT.md) · [更新日志](CHANGELOG.md)

## 目录

- [1. 通用约定](#1-通用约定)
  - [1.1 地址与数据格式](#11-地址与数据格式)
  - [1.2 认证与权限](#12-认证与权限)
  - [1.3 CSRF 防护](#13-csrf-防护)
  - [1.4 接口限流](#14-接口限流)
  - [1.5 统一响应与错误码](#15-统一响应与错误码)
  - [1.6 分页约定](#16-分页约定)
- [2. 公开与认证接口](#2-公开与认证接口)
- [3. 用户设置接口](#3-用户设置接口)
- [4. 大喇叭音频接口](#4-大喇叭音频接口)
- [5. 服务器指南接口](#5-服务器指南接口)
- [6. 公共建筑接口](#6-公共建筑接口)
- [7. 背景图片接口](#7-背景图片接口)
- [8. 游戏账号与封禁接口](#8-游戏账号与封禁接口)
- [9. 假人申请接口](#9-假人申请接口)
- [10. 音频直播接口](#10-音频直播接口)
- [11. 文档与 SEO 接口](#11-文档与-seo-接口)
- [12. 管理后台接口](#12-管理后台接口)
- [13. 附录：路由文件索引](#13-附录路由文件索引)

---

## 1. 通用约定

### 1.1 地址与数据格式

| 项目 | 说明 |
| --- | --- |
| 基础地址 | 与站点同源，无独立 API 域名。下文路径均相对于站点根路径 |
| 请求格式 | JSON 接口使用 `application/json`；文件上传使用 `multipart/form-data`；部分兼容接口同时接受表单 |
| 响应格式 | 除文件流、SSE、XML、纯文本外，一律返回 `application/json; charset=utf-8` |
| 字符编码 | UTF-8 |
| ID 类型 | 业务主键为雪花 ID（19 位整数），前端按字符串处理以避免精度丢失 |
| 时间格式 | `YYYY-MM-DD HH:MM:SS`（本地时间，Asia/Shanghai） |

### 1.2 认证与权限

本站使用 **Flask Session Cookie** 认证，登录成功后服务端写入 `user_id / username / is_admin`。

| 装饰器 | 行为 |
| --- | --- |
| `@login_required` | 未登录：普通 GET 302 跳转 `/login?next=...`；JSON/AJAX 请求返回 `401 {"success": false, "message": "请先登录"}` |
| `@admin_required` | 未登录同上；已登录但非管理员：普通 GET 403 页面；JSON/AJAX 返回 `403 {"success": false, "message": "权限不足"}` |
| 无装饰器 | 公开接口，任何人可访问 |

判定「JSON/AJAX 请求」的条件（满足任一）：

- 请求头 `Content-Type: application/json`
- 请求头 `Accept` 包含 `application/json`
- 请求头 `X-Requested-With: XMLHttpRequest`

> 前端 `fetch` 调用建议显式带上 `X-Requested-With: XMLHttpRequest`，以保证未登录/无权限时拿到 JSON 而不是 HTML。

### 1.3 CSRF 防护

- 所有 **非 `/api/*`** 的写请求（`POST/PUT/PATCH/DELETE`）必须携带 CSRF Token：
  - 表单字段 `csrf_token`，或
  - 请求头 `X-CSRF-Token`
- Token 来源：页面 `<meta name="csrf-token">` 或任意表单隐藏域。
- **`/api/*` 路径豁免 CSRF**（JSON API 依赖同源 Cookie + 限流 + 业务校验）。
- `/admin/api/*` **不豁免**：仍按普通路径校验 CSRF。

校验失败返回 `400`（HTML 错误页或 JSON，取决于请求类型）。

### 1.4 接口限流

由 `services/firewall/api_guard.py` 的 `guard_api_request()` 统一执行：

| 计数桶 | 适用路径 | 上限 | 窗口 |
| --- | --- | --- | --- |
| 默认 | `/api/*`、任意 AJAX 请求（含 `/admin/api/*`） | 每 IP 60 次 | 60 秒（可配置） |
| `live_pcm` | `POST /api/live/<id>/pcm` | 每 IP 2400 次 | 60 秒 |
| `live_opus` | `POST /api/live/<id>/opus` | 每 IP 3000 次 | 60 秒 |

- 阈值与开关在「系统设置 → 防火墙」中热更新（`API_RATE_LIMIT_ENABLED`、`API_RATE_LIMIT_PER_MINUTE`、`API_RATE_LIMIT_WINDOW_SECONDS`）。
- 超限返回 `429 {"success": false, "message": "请求过于频繁，请稍后再试"}`，并带 `Retry-After`。
- 用户刷新页面（发起一次普通页面请求）会清空该 IP 的全部计数与封禁。
- 白名单 IP、回环地址不受限制。

### 1.5 统一响应与错误码

业务接口统一返回：

```json
{ "success": true, "message": "操作成功" }
```

失败：

```json
{ "success": false, "message": "错误原因" }
```

| 状态码 | 含义 |
| --- | --- |
| `200` | 成功 |
| `400` | 参数缺失、格式错误、业务校验不通过 |
| `401` | 未登录或会话失效 |
| `403` | 无权限（非管理员、非本人、路径穿越） |
| `404` | 资源不存在 |
| `409` | 资源状态冲突（如直播管道已关闭） |
| `429` | 触发限流或邮箱验证码发送过于频繁 |
| `500` | 服务端异常 |
| `502` | RCON 执行失败 |
| `503` | 临时不可用（如 sitemap 无法生成） |

### 1.6 分页约定

列表接口统一使用 `page`（从 1 开始）与 `has_more`：

```json
{
  "success": true,
  "items": [],
  "page": 1,
  "has_more": false,
  "next_page": 2
}
```

部分接口按业务返回 `total`、`page_size`。分页大小大多由系统设置决定，**前端传入的 page_size 一律忽略**。

---

## 2. 公开与认证接口

### 2.1 站点统计

#### GET `/api/stats`

- **鉴权**：公开
- **参数**：无
- **响应**：

```json
{ "total_users": 128 }
```

- **说明**：仅返回注册用户总数。
- **实现**：[routes/api/public/__init__.py](../routes/api/public/__init__.py)

#### GET `/api/server-status`

- **鉴权**：公开
- **参数**：无
- **响应**：

```json
{
  "online": 3,
  "max_players": 20,
  "players": ["Steve", "Alex"],
  "error": "",
  "cpu_percent": 12.5,
  "memory_percent": 43.1,
  "memory_used": 2048,
  "memory_total": 8192,
  "net_sent": 102400,
  "net_recv": 204800,
  "net_up": 12.3,
  "net_down": 45.6
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `online` | int | 当前在线玩家数 |
| `max_players` | int | 服务器最大人数 |
| `players` | string[] | 在线玩家名列表 |
| `error` | string | RCON 错误信息，空串表示正常 |
| `cpu_percent` / `memory_percent` | float | CPU / 内存占用百分比 |
| `memory_used` / `memory_total` | int | 已用 / 总内存（MB） |
| `net_sent` / `net_recv` | int | 累计发送 / 接收字节 |
| `net_up` / `net_down` | float | 当前上行 / 下行速率（KB/s） |

- **说明**：玩家数据由 RCON 追踪器每 5 秒刷新；系统资源由后台任务每 5 秒采样。
- **实现**：[routes/api/public/__init__.py](../routes/api/public/__init__.py)

### 2.2 图形验证码

#### GET `/api/captcha/generate`

- **鉴权**：公开
- **查询参数**：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `previous_id` | 否 | 上一张验证码 ID；传入时会立即作废，避免重放 |

- **响应**：

```json
{
  "success": true,
  "image": "data:image/png;base64,...",
  "captcha_id": "8f14e45f...",
  "code_length": 4,
  "expires_in": 300
}
```

- **错误**：`500 {"success": false, "message": "生成验证码失败: ..."}`
- **响应头**：`Cache-Control: no-store`
- **说明**：答案存于服务端内存，5 分钟过期；`captcha_id` 必须随表单回传。
- **实现**：[routes/api/captcha/__init__.py](../routes/api/captcha/__init__.py)

#### POST `/api/captcha/verify`

- **鉴权**：公开
- **请求体**：

```json
{ "captcha_id": "8f14e45f...", "captcha": "a1b2" }
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `captcha_id` | 是 | 验证码 ID |
| `captcha` | 是 | 用户输入的 4 位验证码 |

- **响应**：
  - 成功：`{"success": true, "message": "验证成功"}`
  - 失败：`{"success": false, "message": "验证码错误或已过期"}`
- **错误**：`400`（参数不完整或长度不足 4 位）
- **说明**：仅校验、不消耗，供「先验证再提交表单」的场景使用。
- **实现**：[routes/api/captcha/__init__.py](../routes/api/captcha/__init__.py)

### 2.3 邮箱验证码

#### GET `/api/email/check-enabled`

- **鉴权**：公开
- **响应**：

```json
{ "enabled": true, "register_verify": true }
```

| 字段 | 说明 |
| --- | --- |
| `enabled` | SMTP 邮件功能是否启用 |
| `register_verify` | 注册是否强制邮箱验证 |

- **实现**：[routes/api/email_code/__init__.py](../routes/api/email_code/__init__.py)

#### POST `/api/email/send-code`

- **鉴权**：公开（`purpose=修改邮箱` 需登录）
- **请求体**：

```json
{
  "email": "user@example.com",
  "purpose": "注册",
  "captcha": "a1b2",
  "captcha_id": "8f14e45f..."
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `email` | 是 | 收件邮箱 |
| `purpose` | 否 | `注册`（默认）/ `找回密码` / `修改邮箱` |
| `captcha` | 是 | 图形验证码 |
| `captcha_id` | 是 | 图形验证码 ID |

- **前置条件**：
  - `purpose=注册`：当前会话必须已通过群内验证码，且系统开启注册邮箱验证。
  - `purpose=修改邮箱`：必须已登录。
  - 邮件功能必须已启用。
- **响应**：`{"success": true, "message": "验证码已发送"}`
- **错误**：

| 状态码 | message |
| --- | --- |
| `400` | 不支持的验证码用途 / 请输入邮箱地址 / 邮箱格式不正确 / 群内验证码错误 / 图形验证码错误或已过期（附 `need_captcha: true`）/ 邮件功能未启用 / 注册邮箱验证未开启 |
| `401` | 请先登录 |
| `429` | 发送过于频繁，请稍后再试 |

- **说明**：同一 IP 发送过于频繁会触发防火墙自动封禁；成功后图形验证码作废。
- **实现**：[routes/api/email_code/__init__.py](../routes/api/email_code/__init__.py)

### 2.4 用户名与群内验证码

#### GET `/api/username/check`

- **鉴权**：公开
- **查询参数**：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `username` | 是 | 待检查用户名 |
| `exclude_self` | 否 | 传 `1` 时排除当前登录用户自身（修改用户名场景） |

- **响应**：`{"available": true, "message": "用户名可用"}`
- **实现**：[routes/main/auth/__init__.py](../routes/main/auth/__init__.py)

#### POST `/api/verify-group-code`

- **鉴权**：公开
- **请求体**：`{"code": "群公告中的验证码"}`
- **响应**：`{"success": true, "message": "验证成功"}`
- **错误**：`400`（为空或错误）
- **说明**：验证通过后写入会话 `group_code_verified`，注册发邮箱验证码时依赖它。
- **实现**：[routes/main/auth/__init__.py](../routes/main/auth/__init__.py)

#### GET `/api/verify-group-code/check`

- **鉴权**：公开
- **响应**：`{"verified": true}`
- **实现**：[routes/main/auth/__init__.py](../routes/main/auth/__init__.py)

### 2.5 页面表单（非 JSON）

以下为整页表单提交，不是 JSON API：

| 方法 | 路径 | 说明 | 实现 |
| --- | --- | --- | --- |
| GET/POST | `/register` | 注册（用户名、密码、确认密码、群内验证码、图形验证码、邮箱、邮箱验证码） | [routes/main/auth/__init__.py](../routes/main/auth/__init__.py) |
| GET/POST | `/login` | 登录；连续失败达到阈值后要求图形验证码 | 同上 |
| GET | `/logout` | 退出并清除 Cookie | 同上 |
| GET/POST | `/forgot-password` | 找回密码（用户名、邮箱、图形验证码、邮箱验证码、新密码、确认密码） | 同上 |

---

## 3. 用户设置接口

页面：`GET /settings?tab=username|password|email|avatar|delete`

#### POST `/api/settings/username`

- **鉴权**：登录
- **请求体**（JSON 或表单）：

```json
{ "new_username": "new_name", "current_password": "******" }
```

- **响应**：`{"success": true, "message": "...", "username": "new_name"}`
- **错误**：业务失败时 `success=false` 并附原因（用户名占用、密码错误等），HTTP 仍为 200。
- **说明**：成功后同步更新 Session 中的 `username`。
- **实现**：[routes/main/settings/__init__.py](../routes/main/settings/__init__.py)

#### POST `/api/settings/password`

- **鉴权**：登录
- **请求体**：

```json
{
  "current_password": "old",
  "new_password": "new",
  "confirm_password": "new"
}
```

- **响应**：`{"success": true, "message": "密码修改成功"}`
- **实现**：[routes/main/settings/__init__.py](../routes/main/settings/__init__.py)

#### POST `/api/settings/email`

- **鉴权**：登录
- **请求体**：

```json
{
  "new_email": "new@example.com",
  "email_code": "123456",
  "current_password": "******"
}
```

- **响应**：`{"success": true, "message": "...", "email": "new@example.com"}`
- **实现**：[routes/main/settings/__init__.py](../routes/main/settings/__init__.py)

#### POST `/api/settings/delete`

- **鉴权**：登录
- **请求体**：`{"confirm_username": "当前用户名"}`
- **响应**：`{"success": true, "message": "...", "redirect": "/"}`
- **说明**：成功后会清空会话并注销。
- **实现**：[routes/main/settings/__init__.py](../routes/main/settings/__init__.py)

#### POST `/api/settings/avatar`

- **鉴权**：登录
- **请求格式**：`multipart/form-data`，字段 `avatar`
- **限制**：≤ 10MB，像素 ≤ 4000 万，统一裁切为 512×512 WebP
- **响应**：`{"success": true, "message": "头像更新成功！", "avatar_url": "/media/avatar/<id>"}`
- **实现**：[routes/main/media/__init__.py](../routes/main/media/__init__.py)

#### POST `/api/settings/avatar/delete`

- **鉴权**：登录
- **响应**：`{"success": true, "message": "头像已恢复为默认样式", "avatar_url": null}`
- **实现**：[routes/main/media/__init__.py](../routes/main/media/__init__.py)

#### GET `/media/avatar/<user_id>`

- **鉴权**：公开
- **响应**：`image/webp`；未设置头像返回 404
- **响应头**：`Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff`
- **实现**：[routes/main/media/__init__.py](../routes/main/media/__init__.py)

#### 兼容表单接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/settings/username` | 整页提交，flash 后跳回 `/settings` |
| POST | `/settings/password` | 同上 |
| POST | `/settings/email` | 同上 |
| POST | `/settings/delete` | 同上 |
| POST | `/settings/avatar` | 上传头像后跳回 `/settings?tab=avatar` |
| POST | `/settings/avatar/delete` | 删除头像后跳回 |

> 这些路径不在 `/api/` 下，**必须携带 CSRF Token**。

---

## 4. 大喇叭音频接口

#### GET `/api/music/list`

- **鉴权**：公开（登录时附带收藏状态）
- **查询参数**：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `q` | 否 | 关键词，匹配标题或标签，最长 60 字符 |
| `page` | 否 | 页码，默认 1 |

- **响应**：

```json
{
  "success": true,
  "musics": [
    {
      "id": "1234567890123456789",
      "user_id": "42",
      "username": "Steve",
      "title": "背景音乐",
      "tags": "轻音乐,夜晚",
      "status": 2,
      "created_at": "2026-11-01 12:00:00",
      "duration": "03:12",
      "is_favorited": false,
      "tags_list": ["轻音乐", "夜晚"]
    }
  ],
  "has_more": false,
  "page": 1,
  "next_page": 2
}
```

- **说明**：只返回 `status=2`（已公开）的音频；`duration` 由服务端附加。
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### POST `/music/upload`

- **鉴权**：登录
- **CSRF**：需要
- **请求格式**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 音频标题，参与内容注入检测 |
| `tags` | string | 否 | 逗号分隔标签 |
| `is_public` | string | 否 | `1/on/true` 表示申请公开，进入待审核 |
| `audio_file` | file | 是 | 音频文件 |

- **响应**：
  - 成功：`{"task_id": "..."}`（异步任务）
  - 失败：`{"error": "原因"}`
- **错误**：`400`（内容违规、待审核数量超限、文件校验失败）
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### GET `/music/upload/progress/<task_id>`

- **鉴权**：登录
- **响应**：上传任务进度 JSON，形如 `{"status": "processing", "percent": 42, "message": "..."}`
- **错误**：`404 {"status": "error", "message": "任务不存在或已过期"}`
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### POST `/music/<music_id>/favorite`

- **鉴权**：登录
- **CSRF**：需要
- **响应**：`{"success": true, "message": "已收藏", "is_favorited": true}`
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### POST `/music/<music_id>/tags`

- **鉴权**：登录（作者本人或管理员）
- **CSRF**：需要
- **请求体**（表单）：`tags=标签1,标签2`
- **响应**：`{"success": true, "message": "标签已更新"}`
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### POST `/api/music/<music_id>/toggle`

- **鉴权**：登录（作者本人或管理员）
- **请求体**：无
- **响应**：

```json
{ "success": true, "message": "...", "music_id": 123, "status": 2 }
```

- **状态值**：`0` 私有、`1` 待审核、`2` 已公开
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### POST `/api/music/<music_id>/delete`

- **鉴权**：登录（作者本人或管理员）
- **响应**：`{"success": true, "message": "音频已删除", "music_id": 123}`
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

#### 播放与文件

| 方法 | 路径 | 说明 | 缓存 |
| --- | --- | --- | --- |
| GET | `/music/<music_id>.m3u8` | HLS 播放列表，所有音频凭链接可访问 | `max-age=3600` |
| GET | `/music/<music_id>.mp3` | MP3 唱片文件 | `max-age=3600` |
| GET | `/music/<music_id>/<filename>` | HLS `.ts` 分片，含路径穿越校验 | `max-age=86400` |

- **鉴权**：公开
- **错误**：`404`（音频不存在、文件缺失、非法路径）
- **实现**：[routes/main/music/__init__.py](../routes/main/music/__init__.py)

---

## 5. 服务器指南接口

#### GET `/api/guides/list`

- **鉴权**：公开（登录时附带收藏状态）
- **查询参数**：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `page` | 否 | 页码，默认 1 |
| `q` | 否 | 关键词，匹配标题与摘要，最长 60 字符 |

- **响应**：

```json
{
  "success": true,
  "guides": [
    {
      "id": "1234567890123456789",
      "title": "新手指南",
      "summary": "摘要",
      "status": "approved",
      "is_pinned": 0,
      "created_at": "...",
      "updated_at": "...",
      "published_at": "...",
      "rejected_reason": "",
      "author_name": "Steve",
      "is_favorited": false,
      "favorite_count": 3
    }
  ],
  "page": 1,
  "page_size": 5,
  "total": 1,
  "has_more": false,
  "my_mode": false,
  "keyword": ""
}
```

- **排序**：置顶优先 → 收藏数倒序 → 标题升序
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### GET `/api/guides/my`

- **鉴权**：登录
- **参数**：`page`、`q`
- **响应**：结构同 `/api/guides/list`，`my_mode=true`，并额外返回 `slug`、`replace_of`；包含草稿 / 待审核 / 已拒绝。
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### POST `/api/guides/<guide_id>/publish`

- **鉴权**：登录（作者本人或管理员）
- **请求体**：无
- **行为**：草稿 → 待审核；正文为空时拒绝
- **响应**：

```json
{ "success": true, "message": "指南已发布，等待管理员审核", "status": "pending", "redirect": "/guides/my" }
```

- **错误**：`400`（非草稿 / 正文为空）、`403`（无权）、`404`（不存在）
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### POST `/api/guides/<guide_id>/delete`

- **鉴权**：登录（作者本人或管理员）
- **行为**：只允许删除 `draft` / `rejected`，同步删除指南目录
- **响应**：`{"success": true, "message": "指南已删除"}`
- **错误**：`400`（状态不允许）、`403`、`404`
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### POST `/api/guides/<guide_id>/draft`

- **鉴权**：登录（作者本人或管理员）
- **请求体**：

```json
{ "title": "标题", "summary": "摘要", "content": "Markdown 正文" }
```

- **行为**：仅 `draft` 状态可用；保存 `guide.md` 并更新标题 / 别名 / 摘要
- **响应**：`{"success": true, "message": "草稿已保存"}`
- **错误**：`400`（非草稿 / 标题为空 / 内容违规）、`403`、`404`
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### POST `/api/guides/verify-captcha`

- **鉴权**：公开
- **请求体**：`{"captcha": "a1b2", "captcha_id": "..."}`
- **响应**：`{"success": true}` / `{"success": false, "message": "验证码错误或已过期"}`
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### POST `/api/guides/<guide_id>/favorite`

- **鉴权**：登录
- **响应**：`{"success": true, "is_favorited": true, "favorite_count": 4}`
- **错误**：`404`
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### 指南资源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/guides/<id>/resources` | 列出图片与视频资源，附配额 |
| POST | `/api/guides/<id>/images` | 上传正文图片（字段 `image` 或 `file`） |
| POST | `/api/guides/<id>/videos` | 上传视频并异步转码（字段 `video` 或 `file`，可选 `title`） |
| GET | `/api/guides/<id>/videos/progress/<task_id>` | 查询视频转码进度 |
| POST | `/api/guides/<id>/resources/<filename>/rename` | 修改视频显示名（`title`） |
| POST | `/api/guides/<id>/resources/<filename>/delete` | 删除资源 |
| POST | `/api/guides/<id>/resources/<filename>/compress` | 有损压缩资源 |

资源接口通用要求：

- **鉴权**：登录，且为作者本人或管理员
- **配额响应字段**：

```json
{
  "used_bytes": 10485760,
  "limit_bytes": 104857600,
  "used_label": "10.0 MB",
  "limit_label": "100.0 MB",
  "percent": 10.0
}
```

- **图片上传响应**：

```json
{
  "success": true,
  "url": "/guides/<id>/assets/<文件>",
  "markdown": "![文件名](/guides/<id>/assets/<文件>)",
  "item": { "name": "...", "type": "image", "size": 12345, "size_label": "12.1 KB", "link": "assets/...", "url": "...", "delete_url": "...", "compress_url": "..." }
}
```

- **视频上传响应**：

```json
{
  "success": true,
  "message": "视频已上传，正在转码",
  "task_id": "...",
  "progress_url": "/api/guides/<id>/videos/progress/<task_id>"
}
```

- **转码进度响应**：

```json
{ "success": true, "status": "processing", "percent": 55, "message": "转码中" }
```

`status` 为 `processing / done / error`；`done` 时附 `item` 与配额字段。

- **错误**：`400`（类型 / 大小 / 配额不符）、`403`、`404`
- **实现**：[routes/guides/api/__init__.py](../routes/guides/api/__init__.py)

#### 指南页面与资产

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/guides` | 指南列表页 |
| GET | `/guides/my` | 我的指南页 |
| GET | `/guides/favorites` | 我的收藏页 |
| GET | `/guides/<id>` | 指南详情页 |
| GET | `/guides/<id>/assets/<filename>` | 指南图片 / 视频静态资源（含路径校验） |
| POST | `/guides/create` | 创建「未命名指南」草稿并跳转 |
| GET/POST | `/guides/<id>/edit` | 编辑指南；已发布指南首次编辑会复制为替换草稿 |

- **实现**：[routes/guides/pages/__init__.py](../routes/guides/pages/__init__.py)

---

## 6. 公共建筑接口

#### GET `/api/buildings/list`

- **鉴权**：公开
- **参数**：`q`（匹配标题与标签，最长 100）、`tag`（精确标签，最长 32）、`page`
- **响应**：

```json
{
  "success": true,
  "buildings": [
    {
      "id": "1234567890123456789",
      "title": "出生点大厅",
      "warp_name": "spawn",
      "description": "...",
      "tags": "大厅,出生点",
      "author_name": "Steve",
      "status": "approved",
      "created_at": "...",
      "is_favorited": false
    }
  ],
  "has_more": false,
  "page": 1,
  "next_page": 2
}
```

- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### GET `/api/buildings/my`

- **鉴权**：登录
- **参数**：同列表
- **说明**：包含本人发布的全部状态，按更新时间排序。
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### GET `/api/buildings/favorites`

- **鉴权**：登录
- **参数**：`q`、`page`
- **说明**：按收藏时间倒序。
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### GET `/api/buildings/<building_id>/comments`

- **鉴权**：公开；未审核建筑仅作者与管理员可看
- **参数**：`page`
- **响应**：

```json
{
  "success": true,
  "comments": [
    {
      "id": "123",
      "user_id": "42",
      "username": "Alex",
      "content": "很棒",
      "created_at": "..."
    }
  ],
  "has_more": false,
  "page": 1,
  "next_page": 2,
  "total": 1
}
```

- **错误**：`404`（建筑不存在或尚未审核通过）
- **说明**：分页大小由 `BUILDING_COMMENTS_PER_PAGE` 控制，前端传参忽略。
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### POST `/buildings/<building_id>/favorite`

- **鉴权**：登录
- **CSRF**：需要
- **响应**：`{"success": true, "message": "已收藏", "is_favorited": true, "favorite_count": 5}`
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### POST `/buildings/<building_id>/tags`

- **鉴权**：登录（作者本人或管理员）
- **CSRF**：需要
- **请求体**（表单）：`tags=标签1,标签2`
- **响应**：`{"success": true, "message": "标签已更新", "tags": "标签1,标签2"}`
- **错误**：内容注入被拦截时 `success=false`
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### POST `/buildings/<building_id>/comment`

- **鉴权**：登录
- **CSRF**：需要
- **请求体**（表单）：`content=评论内容`
- **响应**：

```json
{
  "success": true,
  "message": "评论已发布",
  "comment": {
    "id": "123",
    "user_id": "42",
    "username": "Alex",
    "content": "很棒",
    "created_at": "..."
  }
}
```

- **说明**：未审核建筑仅作者本人可评论；内容经过注入检测。
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### POST `/buildings/comment/<comment_id>/delete`

- **鉴权**：登录（评论作者 / 建筑作者 / 管理员）
- **CSRF**：需要
- **响应**：`{"success": true, "message": "评论已删除"}`
- **错误**：无权时 `success=false`
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### POST `/buildings/<building_id>/report`

- **鉴权**：登录
- **CSRF**：需要
- **请求体**（表单）：`reason=举报原因`
- **限制**：不能举报自己的建筑；同一建筑不能重复待处理举报
- **响应**：`{"success": true, "message": "举报已提交，管理员会尽快处理"}`
- **实现**：[routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py)

#### GET/POST `/buildings/create`

- **鉴权**：登录
- **CSRF**：需要
- **POST 字段**：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `title` | 是 | 建筑标题 |
| `warp_name` | 是 | 领地名 |
| `description` | 是 | 建筑介绍 |
| `usage_info` | 否 | 使用说明 |
| `notes` | 否 | 注意事项 |
| `tags` | 否 | 标签 |
| `captcha` | 是 | 图形验证码 |
| `captcha_id` | 是 | 图形验证码 ID |

- **响应**：AJAX 返回 JSON；普通表单 flash 后跳转。提交后进入 `pending` 待审核。
- **实现**：[routes/buildings/pages/__init__.py](../routes/buildings/pages/__init__.py)

---

## 7. 背景图片接口

#### GET `/api/backgrounds/list`

- **鉴权**：公开（登录时附带 `my`）
- **参数**：`page`
- **响应**：

```json
{
  "success": true,
  "logged_in": true,
  "approved": [
    { "id": 1, "filename": "bg.webp", "username": "Steve", "status": 1, "created_at": "..." }
  ],
  "my": [],
  "page": 1,
  "page_size": 5,
  "total": 1,
  "has_more": false
}
```

- **说明**：`approved` 为已通过审核的背景池；`my` 为当前用户全部上传记录（不分页）。
- **实现**：[routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py)

#### POST `/backgrounds/upload`

- **鉴权**：登录
- **CSRF**：需要
- **请求格式**：`multipart/form-data`，字段 `background_image`（可多文件）
- **响应**：`{"task_ids": ["...", "..."]}`
- **错误**：`400 {"error": "请选择图片" / 待审核超限 / 全部失败}`
- **实现**：[routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py)

#### GET `/backgrounds/upload/progress/<task_id>`

- **鉴权**：登录
- **响应**：任务进度 JSON；不存在返回 `404`
- **实现**：[routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py)

#### POST `/backgrounds/<bg_id>/delete`

- **鉴权**：登录（上传者本人或管理员）
- **CSRF**：需要
- **响应**：`{"success": true, "message": "背景已删除"}`
- **实现**：[routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py)

#### GET `/backgrounds/serve`

- **鉴权**：公开
- **参数**：`ratio`（屏幕宽高比，宽/高，自动收敛到允许区间）
- **响应**：`image/webp`，内容为最接近该比例的一张已通过背景；无背景返回 404
- **缓存**：`no-cache, must-revalidate` + ETag，支持 304
- **说明**：服务端只挑选不裁剪，铺满由浏览器 CSS 完成。
- **实现**：[routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py)

#### GET `/backgrounds/serve/<bg_id>`

- **鉴权**：公开；未通过审核的图片仅管理员与上传者可见
- **响应**：`image/webp`；`Cache-Control: public, max-age=86400` + ETag
- **实现**：[routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py)

---

## 8. 游戏账号与封禁接口

#### POST `/api/game-accounts/apply-register`

- **鉴权**：登录
- **请求体**：

```json
{ "mc_username": "Steve", "captcha_id": "...", "captcha": "a1b2" }
```

- **校验**：MC 用户名 3~16 字符；图形验证码一次性消耗
- **响应**：`{"success": true, "message": "申请已提交，等待管理员审核"}`
- **错误**：`400`（为空 / 长度不符 / 验证码错误）
- **实现**：[routes/game_accounts/__init__.py](../routes/game_accounts/__init__.py)

#### POST `/api/game-accounts/ban-apply`

- **鉴权**：登录
- **请求体**：

```json
{
  "player_name": "Griefer",
  "qq_name": "某玩家QQ名",
  "reason": "破坏建筑",
  "captcha_id": "...",
  "captcha": "a1b2"
}
```

- **响应**：`{"success": true, "message": "封禁申请已提交"}`
- **错误**：`400`（字段缺失 / 验证码错误）
- **实现**：[routes/game_accounts/__init__.py](../routes/game_accounts/__init__.py)

---

## 9. 假人申请接口

#### GET `/api/bots/players`

- **鉴权**：登录
- **参数**：`q`（可选，玩家名模糊搜索）
- **响应**：`{"success": true, "players": ["Steve", "Alex"]}`
- **实现**：[routes/bots/__init__.py](../routes/bots/__init__.py)

#### POST `/api/bots/player-position`

- **鉴权**：登录
- **请求体**：`{"player_name": "Steve"}`
- **行为**：通过 RCON 执行 `/data get entity <玩家> Pos` 并解析坐标
- **响应**：`{"success": true, "player_name": "Steve", "x": 1.0, "y": 64.0, "z": 2.0}`
- **错误**：

| 状态码 | 场景 |
| --- | --- |
| `400` | 玩家名非法 |
| `404` | 玩家不在线 / 无法解析坐标 |
| `502` | RCON 执行失败 |

- **实现**：[routes/bots/__init__.py](../routes/bots/__init__.py)

#### POST `/api/bots/apply`

- **鉴权**：登录
- **请求体**：

```json
{
  "bot_name": "Steve_bot",
  "x": 100,
  "y": 64,
  "z": -200,
  "offline_at": "2026-11-23T18:00"
}
```

- **校验**：字段完整；待审核数量上限（总量 + 假人单独上限，管理员豁免）
- **响应**：`{"success": true, "message": "申请已提交"}`
- **错误**：`400`
- **实现**：[routes/bots/__init__.py](../routes/bots/__init__.py)

---

## 10. 音频直播接口

#### GET `/api/live/list`

- **鉴权**：公开
- **响应**：

```json
{
  "success": true,
  "channels": [
    {
      "id": 1234567890123456789,
      "user_id": 42,
      "username": "Steve",
      "title": "深夜电台",
      "mode": "loop",
      "mode_label": "循环播放",
      "music_id": 99,
      "volume": 1.0,
      "speed": 1.0,
      "created_at": "...",
      "alive": true,
      "listeners": 5,
      "last_error": "",
      "links": {
        "m3u8": "https://example.com/live/stream/123.m3u8",
        "mp3": "https://example.com/live/stream/123.mp3",
        "page": "https://example.com/live/play.html?id=123"
      }
    }
  ]
}
```

- **说明**：只列出运行中且状态为 `live` 的频道。
- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### GET `/api/live/<channel_id>`

- **鉴权**：公开
- **响应**：`{"success": true, "channel": { ... }}`；频道不存在时 `404`
- **说明**：运行中返回实时状态；已结束但记录存在返回 `alive=false`。
- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### GET `/api/live/me`

- **鉴权**：登录
- **响应**：

```json
{
  "success": true,
  "banned": false,
  "ban": null,
  "channels": [],
  "channel": null,
  "limits": { "loop_max": 5, "loop_used": 0, "rec_max": 1, "rec_used": 0 }
}
```

- **说明**：`channel` 为兼容旧前端的「最新一个直播」；`ban` 为封禁记录。
- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### GET `/api/live/musics`

- **鉴权**：登录
- **参数**：`q`（最长 60）、`page`
- **响应**：

```json
{
  "success": true,
  "musics": [
    {
      "id": 99,
      "title": "背景音乐",
      "tags": "轻音乐",
      "tags_list": ["轻音乐"],
      "status": 2,
      "status_label": "已公开"
    }
  ],
  "has_more": false,
  "page": 1,
  "next_page": 2
}
```

- **说明**：包含当前用户的私有音频，每页 20 条。
- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### POST `/api/live/start`

- **鉴权**：登录
- **请求体**：

```json
{ "title": "深夜电台", "mode": "loop", "music_id": 99 }
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `title` | 是 | 直播标题，最长 60，经过内容注入检测 |
| `mode` | 否 | `loop`（默认）或 `rec` |
| `music_id` | loop 模式必填 | 音源音频 ID |

- **响应**：`{"success": true, "channel": { ... }}`
- **错误**：

| 状态码 | 场景 |
| --- | --- |
| `400` | 标题为空 / 模式非法 / 标题违规 / 超出开播上限 / 音源不可用 |
| `403` | 已被禁止开播 |

- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### POST `/api/live/<channel_id>/stop`

- **鉴权**：登录（本人或管理员）
- **请求体**：`{"reason": "可选原因"}`
- **响应**：`{"success": true, "message": "直播已停止"}`
- **错误**：`400`
- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### POST `/api/live/<channel_id>/pcm`

- **鉴权**：登录（频道本人或管理员）
- **请求格式**：原始二进制 `application/octet-stream`，48kHz 双声道 s16le PCM
- **限流**：独立桶 2400 次/60 秒
- **响应**：`{"success": true}`
- **错误**：

| 状态码 | 场景 |
| --- | --- |
| `400` | 非实时录音频道 / 分片长度或大小非法 |
| `403` | 无权推送 |
| `404` | 直播不存在或已结束 |
| `409` | 音频管道已关闭 |

- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### POST `/api/live/<channel_id>/opus`

- **鉴权**：登录（频道本人或管理员）
- **请求格式**：原始二进制，多个 `[2 字节大端长度][Opus 包]` 串联
- **限流**：独立桶 3000 次/60 秒
- **响应**：`{"success": true}`
- **错误**：同 PCM（校验逻辑见 `validate_opus_batch`）
- **说明**：服务端只校验与转发，不解码、不落盘。
- **实现**：[routes/live/api/__init__.py](../routes/live/api/__init__.py)

#### 流媒体

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/live/stream/<channel_id>.m3u8` | HLS 播放列表（分片路径已改写为绝对站内路径） |
| GET | `/live/stream/<channel_id>.mp3` | MP3 实时流（有界队列分发） |
| GET | `/live/stream/<channel_id>.opus` | Opus 包流（每包带 2 字节长度前缀） |
| GET | `/live/stream/<channel_id>/<filename>` | HLS 分片，含路径穿越校验 |

- **鉴权**：公开
- **错误**：`404`
- **实现**：[routes/live/stream/__init__.py](../routes/live/stream/__init__.py)

---

## 11. 文档与 SEO 接口

#### GET `/api/docs/list`

- **鉴权**：公开
- **响应**：

```json
{ "docs": [ { "filename": "API.md", "title": "API 指南" } ] }
```

- **说明**：读取 `docs/*.md`，标题取首行 `# ` 后的文本。
- **实现**：[routes/docs/pages/__init__.py](../routes/docs/pages/__init__.py)

#### GET `/api/docs/content/<filename>`

- **鉴权**：公开
- **限制**：只允许 `docs/` 下的 `.md` 文件，路径中不得含 `..`、`/`、`\`
- **响应**：`{"content": "# ...", "filename": "API.md"}`
- **错误**：`403`（非法文件名）、`404`（不存在）、`500`
- **实现**：[routes/docs/pages/__init__.py](../routes/docs/pages/__init__.py)

#### GET `/sitemap.xml`

- **鉴权**：公开
- **响应**：`application/xml`，含 ETag，支持 `If-None-Match` → 304
- **错误**：`503`（数据库不可用、无法生成时）
- **说明**：只收录公开规范 URL，自动排除私有页与静态资源。
- **实现**：[routes/sitemap/__init__.py](../routes/sitemap/__init__.py)

#### GET `/robots.txt`

- **鉴权**：公开
- **响应**：`text/plain`，含 `Crawl-delay`、敏感路径 `Disallow` 与 `Sitemap` 行
- **缓存**：`max-age=3600`
- **实现**：[routes/sitemap/__init__.py](../routes/sitemap/__init__.py)

#### GET `/<key>.txt`

- **鉴权**：公开
- **说明**：IndexNow 站点所有权校验文件；`key` 必须与当前配置一致，否则 404
- **缓存**：`max-age=86400`
- **实现**：[routes/indexnow/__init__.py](../routes/indexnow/__init__.py)

---

## 12. 管理后台接口

> 以下接口均要求 `@admin_required`。`/admin/api/*` 属于 AJAX 请求，会占用默认 API 限流额度；写操作仍需 CSRF Token。

### 12.1 系统设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/settings` | 获取全部设置（按分类分组，含默认值、当前值、是否自定义、更新时间、select 选项） |
| POST | `/admin/api/settings/save` | 批量保存设置 |
| POST | `/admin/api/settings/<key>/reset` | 重置单个设置 |
| POST | `/admin/api/settings/reset-all` | 重置全部可配置设置 |

**保存请求体**：

```json
{ "items": [ { "key": "SITE_NAME", "value": "滨海小镇" } ] }
```

- 服务端按 `SETTINGS_REGISTRY` 声明的类型转换（`bool / int / float / time / password / select`）；`password` 为空表示保留原值。
- **响应**：`{"success": true, "saved": ["..."], "errors": [], "message": "成功保存 N 项设置"}`
- **说明**：保存 `WAITRESS_THREADS` 会即时调整工作线程；日志相关设置会热重载。
- **实现**：[routes/admin/settings/__init__.py](../routes/admin/settings/__init__.py)

### 12.2 用户管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/users/list?page=N` | 用户分页列表（每页 10 条） |
| POST | `/admin/users/<user_id>/toggle-admin` | 切换管理员权限 |
| POST | `/admin/users/<user_id>/delete` | 删除用户 |

- **列表响应**：`{"success": true, "users": [...], "page": 1, "page_size": 10, "total": 1, "has_more": false}`
- **操作响应**：`{"success": true, "message": "..."}`
- **实现**：[routes/admin/users/__init__.py](../routes/admin/users/__init__.py)

### 12.3 游戏账号与封禁

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/game-accounts/applications` | 全部注册申请（`pending` + `all`） |
| GET | `/admin/api/game-accounts/applications/list?status=pending\|approved\|rejected\|all&page=N` | 注册申请分页列表 |
| POST | `/admin/api/game-accounts/applications/<app_id>/approve` | 通过注册申请 |
| POST | `/admin/api/game-accounts/applications/<app_id>/reject` | 驳回，body `{"reason": "..."}` |
| GET | `/admin/api/game-accounts/bans` | 封禁名单 |
| POST | `/admin/api/game-accounts/bans` | 封禁账号，body `{"mc_username": "...", "reason": "..."}` |
| DELETE | `/admin/api/game-accounts/bans/<mc_username>` | 解除封禁 |
| GET | `/admin/api/game-bans` | 封禁申请：`pending` / `active` / `all` |
| POST | `/admin/api/game-bans/<app_id>/approve` | 同意封禁，body 可含 `{"duration_minutes": 1440}` |
| POST | `/admin/api/game-bans/<app_id>/reject` | 驳回，body `{"reason": "..."}` |
| POST | `/admin/api/game-bans/<app_id>/pardon` | 提前解封 |

- **错误**：`400`（MC 名 / 理由非法）、`404`
- **实现**：[routes/admin/account_applications/__init__.py](../routes/admin/account_applications/__init__.py)

### 12.4 假人管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/bots` | `pending` + `all` 假人申请 |
| POST | `/admin/api/bots/<app_id>/approve` | 通过并执行 RCON 生成 |
| POST | `/admin/api/bots/<app_id>/reject` | 驳回，body `{"reason": "..."}` |
| POST | `/admin/api/bots/<app_id>/kill` | 手动下线（RCON 杀死） |

- **响应**：`{"success": true, "message": "..."}`
- **实现**：[routes/admin/bots/__init__.py](../routes/admin/bots/__init__.py)

### 12.5 音频管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/music/list?type=all\|pending&page=N` | 音频分页列表 |
| POST | `/admin/music/<music_id>/review` | 审核，body `{"action": "approve"\|"reject"}` |
| POST | `/admin/music/<music_id>/delete` | 下架（删除） |

- **列表响应**：`{"success": true, "type": "all", "musics": [...], "page": 1, "page_size": 5, "total": 0, "has_more": false}`
- **实现**：[routes/admin/music/__init__.py](../routes/admin/music/__init__.py)

### 12.6 指南管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/guides/list?page=N` | 指南分页列表（每页 10 条） |
| POST | `/admin/guides/<guide_id>/approve` | 通过审核（替换草稿时自动接管原 ID） |
| POST | `/admin/guides/<guide_id>/reject` | 驳回，body `{"reason": "..."}` |
| POST | `/admin/guides/<guide_id>/delete` | 删除指南及目录 |
| GET/POST | `/admin/guides/create` | 直接创建指南（可指定 `status`，默认 `approved`） |
| GET/POST | `/admin/guides/<guide_id>/edit` | 编辑任意指南 |

**创建 / 编辑字段**：

```json
{
  "title": "标题",
  "summary": "摘要",
  "content": "Markdown 正文",
  "cover_image": "封面 URL",
  "is_pinned": "1",
  "status": "approved"
}
```

- **响应**：`{"success": true, "message": "...", "guide_id": 123, "redirect": "/admin/guides"}`
- **实现**：[routes/admin/guides/__init__.py](../routes/admin/guides/__init__.py)

### 12.7 公共建筑管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/buildings/<building_id>/approve` | 通过审核 |
| POST | `/admin/buildings/<building_id>/reject` | 拒绝，body `{"reason": "..."}` |
| POST | `/admin/buildings/<building_id>/delete` | 删除建筑及评论 / 举报 |
| POST | `/admin/buildings/report/<report_id>/dismiss` | 驳回举报 |

- **响应**：`{"success": true, "message": "...", "status": "approved"\|"rejected"}`
- **错误**：`404`（不存在或已处理）、`500`
- **实现**：[routes/admin/buildings/__init__.py](../routes/admin/buildings/__init__.py)

### 12.8 背景图片管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/backgrounds?status=0\|1\|2&page=N` | 背景分页列表（每页 10 条） |
| POST | `/admin/backgrounds/<bg_id>/approve` | 通过审核 |
| POST | `/admin/backgrounds/<bg_id>/reject` | 驳回 |
| POST | `/admin/backgrounds/<bg_id>/delete` | 删除 |

- **状态**：`0` 待审核、`1` 已通过、`2` 已驳回
- **实现**：[routes/admin/backgrounds/__init__.py](../routes/admin/backgrounds/__init__.py)

### 12.9 直播管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/live/list` | `active` 正在直播、`recent` 最近记录、`bans` 封禁名单 |
| POST | `/admin/api/live/<channel_id>/stop` | 强制停止，body `{"reason": "..."}` |
| POST | `/admin/api/live/ban` | 永久禁止开播，body `{"username": "...", "reason": "..."}` |
| POST | `/admin/api/live/unban` | 解封，body `{"user_id": 42}` |

- **错误**：`400`（封禁自己 / 无效 ID）、`404`（用户或直播不存在）
- **实现**：[routes/admin/live/__init__.py](../routes/admin/live/__init__.py)

### 12.10 指南编辑封禁

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/guide-bans/create` | 创建封禁 |
| POST | `/admin/guide-bans/<ban_id>/delete` | 解除封禁 |

**创建请求体**：

```json
{ "target_type": "user", "target_value": "Steve", "reason": "恶意编辑", "duration_days": "7" }
```

- `target_type`：`user` 或 `ip`；`duration_days` 为空或 `0` 表示永久。
- **响应**：`{"success": true, "message": "封禁已创建", "ban": { ... }}`
- **实现**：[routes/admin/guide_bans/__init__.py](../routes/admin/guide_bans/__init__.py)

### 12.11 防火墙

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/firewall/bans?page=N` | 合并封禁列表（IP + 账号，每页 10 条） |
| GET | `/admin/firewall/<ban_id>/detail` | 封禁详情 |
| POST | `/admin/firewall/settings/save` | 保存防火墙配置，body `{"items": [{"key": "...", "value": ...}]}` |
| POST | `/admin/firewall/ban-ip` | 封禁 IP，body `{"ip_address": "...", "reason": "...", "duration_days": "7"}` |
| POST | `/admin/firewall/<ban_id>/delete` | 解除 IP 封禁 |
| POST | `/admin/firewall/ban-account` | 封禁账号，body `{"user_id": 42, "reason": "...", "duration_minutes": 1440}` |
| POST | `/admin/firewall/unban-account/<ban_id>` | 解除账号封禁 |
| POST | `/admin/firewall/whitelist/add` | 添加 IP 白名单 |
| POST | `/admin/firewall/whitelist/remove` | 移除 IP 白名单 |
| POST | `/admin/firewall/whitelist/account/add` | 添加账号白名单 |
| POST | `/admin/firewall/whitelist/account/remove` | 移除账号白名单 |

- **合并列表项字段**：`id / ban_type / identifier / identifier_label / user_id / username / reason / created_at / expires_at / is_permanent / expires_date`
- **错误**：`400`（参数非法）、`404`
- **实现**：[routes/admin/firewall/__init__.py](../routes/admin/firewall/__init__.py)

### 12.12 日志

#### GET `/admin/api/logs`（SSE）

- **鉴权**：管理员
- **查询参数**：`source`（`global` / `fatal` / `module:<name>`）、`level`（最低等级）、`tail`（历史条数，默认 500，最大 2000）
- **响应**：`text/event-stream`
  - 首帧 `event: history`，`data: {"entries": [...], "total": N}`
  - 后续 `data: {...}` 实时日志
  - 空闲发送 `: heartbeat`
- **响应头**：`Cache-Control: no-cache`、`X-Accel-Buffering: no`
- **实现**：[routes/admin/logs/__init__.py](../routes/admin/logs/__init__.py)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/api/logs/clear` | 按 `source` 清空对应日志缓冲 |
| GET | `/admin/api/logs/modules` | 已注册模块日志配置 |
| POST | `/admin/api/logs/modules` | 更新模块日志选项，body `{"name": "firewall", "store": true, "global_enabled": false}` |

### 12.13 访问日志抓取

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/access-log/status` | 当前抓取状态 |
| POST | `/admin/api/access-log/start` | 开启抓取（创建独立 DuckDB） |
| POST | `/admin/api/access-log/stop` | 停止抓取并删除数据库 |
| GET | `/admin/api/access-log/stream?tail=N` | SSE：`history` → `data` → `stopped` |

- **说明**：页面关闭不会停止抓取，只有显式停止才结束。
- **实现**：[routes/admin/access_log/__init__.py](../routes/admin/access_log/__init__.py)

### 12.14 自动维护

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/api/maintenance/start` | 启动异步备份（同时清理日志） |
| GET | `/admin/api/maintenance/progress` | 当前进度与上次备份 |
| GET | `/admin/api/maintenance/list` | 最近 20 条备份记录 |
| GET | `/admin/api/maintenance/dir` | 当前生效的备份目录 |
| GET | `/admin/api/maintenance/<backup_id>/download` | 下载备份 zip |
| POST/DELETE | `/admin/api/maintenance/<backup_id>/delete` | 删除备份文件与记录 |

- **启动响应**：`{"success": true, "backup_id": 1, "message": "维护任务已启动"}`
- **错误**：`404`（记录 / 文件不存在）、`500`
- **实现**：[routes/admin/maintenance/__init__.py](../routes/admin/maintenance/__init__.py)

### 12.15 IndexNow

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/api/indexnow` | 当前配置与最近提交结果 |
| POST | `/admin/api/indexnow/save` | 保存，body `{"enabled": true, "auto_submit": true, "submit_time": "03:30"}` |
| POST | `/admin/api/indexnow/regenerate-key` | 重新生成 Key |
| POST | `/admin/api/indexnow/submit` | 立即提交全部公开 URL |

- **提交响应**：由 `indexnow.submit_all()` 返回，含 `success` 与各域名结果；失败时 HTTP 400。
- **实现**：[routes/admin/indexnow/__init__.py](../routes/admin/indexnow/__init__.py)

### 12.16 广播邮件

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/broadcast/send` | 发送全体广播 |
| GET | `/admin/broadcast/logs` | 最近 20 条广播日志 |

**发送请求体**：

```json
{ "subject": "标题", "html": "<p>内容</p>", "confirm": "CONFIRM" }
```

- **校验**：邮件功能已启用；`confirm` 必须为 `CONFIRM`；标题 ≤ 200 字；内容 ≤ 50000 字符。
- **响应**：`{"success": true, "message": "广播已入队，共 N 位用户将收到邮件", "count": N}`
- **实现**：[routes/admin/broadcast/__init__.py](../routes/admin/broadcast/__init__.py)

### 12.17 模组介绍

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/mod-intros/add` | 新增 |
| POST | `/admin/mod-intros/<intro_id>/edit` | 更新 |
| POST | `/admin/mod-intros/<intro_id>/delete` | 删除 |

**请求体**：`{"icon": "box", "title": "标题", "content": "内容", "link": "example.com"}`

- `link` 无协议时自动补 `https://`。
- **响应**：`{"success": true, "message": "...", "intro": { ... }}`
- **错误**：`400`（标题 / 内容为空）、`404`
- **实现**：[routes/admin/mod_intros/__init__.py](../routes/admin/mod_intros/__init__.py)

### 12.18 公开路径

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/public-files/add` | 添加公开路径 |
| POST | `/admin/public-files/toggle/<pid>` | 启用 / 停用 |
| POST | `/admin/public-files/delete/<pid>` | 删除 |

**添加请求体**：

```json
{ "url_path": "/files", "local_path": "D:/share", "is_directory": true }
```

- 路径会做安全校验（拒绝危险系统路径）；本地路径不存在时仍保存，但返回 `warning`。
- **响应**：`{"success": true, "message": "...", "path": { ... }}`
- **错误**：`400`（路径为空 / 不安全）、`404`、`500`
- **实现**：[routes/public/files/__init__.py](../routes/public/files/__init__.py)

---

## 13. 附录：路由文件索引

| 模块 | 文件 | 主要接口 |
| --- | --- | --- |
| 公开统计 | [routes/api/public/__init__.py](../routes/api/public/__init__.py) | `/api/stats`、`/api/server-status` |
| 图形验证码 | [routes/api/captcha/__init__.py](../routes/api/captcha/__init__.py) | `/api/captcha/*` |
| 邮箱验证码 | [routes/api/email_code/__init__.py](../routes/api/email_code/__init__.py) | `/api/email/*` |
| 认证 | [routes/main/auth/__init__.py](../routes/main/auth/__init__.py) | `/register`、`/login`、`/api/username/check`、`/api/verify-group-code*` |
| 用户设置 | [routes/main/settings/__init__.py](../routes/main/settings/__init__.py) | `/api/settings/*` |
| 头像 | [routes/main/media/__init__.py](../routes/main/media/__init__.py) | `/api/settings/avatar*`、`/media/avatar/<id>` |
| 大喇叭音频 | [routes/main/music/__init__.py](../routes/main/music/__init__.py) | `/api/music/*`、`/music/*` |
| 服务器指南 | [routes/guides/api/__init__.py](../routes/guides/api/__init__.py) | `/api/guides/*` |
| 指南页面 | [routes/guides/pages/__init__.py](../routes/guides/pages/__init__.py) | `/guides/*` |
| 公共建筑 | [routes/buildings/api/__init__.py](../routes/buildings/api/__init__.py) | `/api/buildings/*`、`/buildings/*` |
| 背景图片 | [routes/backgrounds/pages/__init__.py](../routes/backgrounds/pages/__init__.py) | `/api/backgrounds/list`、`/backgrounds/*` |
| 游戏账号 | [routes/game_accounts/__init__.py](../routes/game_accounts/__init__.py) | `/api/game-accounts/*` |
| 假人 | [routes/bots/__init__.py](../routes/bots/__init__.py) | `/api/bots/*` |
| 音频直播 | [routes/live/api/__init__.py](../routes/live/api/__init__.py) | `/api/live/*` |
| 直播流 | [routes/live/stream/__init__.py](../routes/live/stream/__init__.py) | `/live/stream/*` |
| 文档 | [routes/docs/pages/__init__.py](../routes/docs/pages/__init__.py) | `/api/docs/*` |
| SEO | [routes/sitemap/__init__.py](../routes/sitemap/__init__.py) | `/sitemap.xml`、`/robots.txt` |
| IndexNow Key | [routes/indexnow/__init__.py](../routes/indexnow/__init__.py) | `/<key>.txt` |
| 管理设置 | [routes/admin/settings/__init__.py](../routes/admin/settings/__init__.py) | `/admin/api/settings/*` |
| 管理用户 | [routes/admin/users/__init__.py](../routes/admin/users/__init__.py) | `/admin/api/users/*` |
| 游戏账号管理 | [routes/admin/account_applications/__init__.py](../routes/admin/account_applications/__init__.py) | `/admin/api/game-accounts/*`、`/admin/api/game-bans/*` |
| 假人管理 | [routes/admin/bots/__init__.py](../routes/admin/bots/__init__.py) | `/admin/api/bots/*` |
| 音频管理 | [routes/admin/music/__init__.py](../routes/admin/music/__init__.py) | `/admin/api/music/*` |
| 指南管理 | [routes/admin/guides/__init__.py](../routes/admin/guides/__init__.py) | `/admin/api/guides/*` |
| 建筑管理 | [routes/admin/buildings/__init__.py](../routes/admin/buildings/__init__.py) | `/admin/buildings/*` |
| 背景管理 | [routes/admin/backgrounds/__init__.py](../routes/admin/backgrounds/__init__.py) | `/admin/api/backgrounds`、`/admin/backgrounds/*` |
| 直播管理 | [routes/admin/live/__init__.py](../routes/admin/live/__init__.py) | `/admin/api/live/*` |
| 指南封禁 | [routes/admin/guide_bans/__init__.py](../routes/admin/guide_bans/__init__.py) | `/admin/guide-bans/*` |
| 防火墙 | [routes/admin/firewall/__init__.py](../routes/admin/firewall/__init__.py) | `/admin/api/firewall/*`、`/admin/firewall/*` |
| 日志 | [routes/admin/logs/__init__.py](../routes/admin/logs/__init__.py) | `/admin/api/logs*` |
| 访问日志 | [routes/admin/access_log/__init__.py](../routes/admin/access_log/__init__.py) | `/admin/api/access-log/*` |
| 自动维护 | [routes/admin/maintenance/__init__.py](../routes/admin/maintenance/__init__.py) | `/admin/api/maintenance/*` |
| IndexNow 管理 | [routes/admin/indexnow/__init__.py](../routes/admin/indexnow/__init__.py) | `/admin/api/indexnow/*` |
| 广播 | [routes/admin/broadcast/__init__.py](../routes/admin/broadcast/__init__.py) | `/admin/broadcast/*` |
| 模组介绍 | [routes/admin/mod_intros/__init__.py](../routes/admin/mod_intros/__init__.py) | `/admin/mod-intros/*` |
| 公开路径 | [routes/public/files/__init__.py](../routes/public/files/__init__.py) | `/admin/public-files/*` |
