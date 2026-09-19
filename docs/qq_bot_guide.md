# QQ 官方机器人 Python 简易实现指南

> 借鉴 AstrBot 架构思路，使用官方 `botpy` SDK + WebSocket 模式，**无需公网 IP / 域名 / 云服务器**。

## 一、核心原理

### WebSocket 模式 vs Webhook 模式

| 模式                | 需要公网 IP | 需要域名  | 需要 HTTPS | 适合本地运行 |
| ----------------- | ------- | ----- | -------- | ------ |
| **WebSocket（推荐）** | ❌ 不需要   | ❌ 不需要 | ❌ 不需要    | ✅      |
| Webhook           | ✅ 必须    | ✅ 必须  | ✅ 必须     | ❌      |

WebSocket 模式由机器人**主动发起出站连接**到 QQ 服务器，所以不需要公网 IP，在家用宽带 / NAT 环境下即可运行 [$TRAE\_REF](https://docs.astrbot.app/platform/qqofficial/websockets.html)。

### AstrBot 架构借鉴

AstrBot 的核心设计是**平台适配层与业务逻辑层分离** [$TRAE\_REF](https://docs.astrbot.app/what-is-astrbot.html)：

```
消息入口（QQ/Telegram/...）  →  消息处理（Agent/插件）  →  结果发回原平台
       ↑ 平台适配层                    ↑ 业务逻辑层              ↑ 平台适配层
```

本实现简化为：

```
botpy WebSocket 收消息  →  on_message 回调处理  →  api 调用发消息/禁言
```

## 二、前置准备

### 1. 注册机器人

1. 打开 [QQ 开放平台](https://q.qq.com/) 登录
2. 点击「创建机器人」，填写名称、简介、头像
3. 等待安全校验通过（通常很快）
4. 进入机器人管理页 →「开发」→「开发设置」获取 `AppID` 和 `AppSecret` [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/)

### 2. 配置沙箱

在「沙箱配置」中设置测试用的 QQ 群 / 私聊，用于开发调试。

### 3. 开启群聊能力

在手机 QQ 的群聊设置中：

- 将「机器人可获取的群聊消息范围」设为「获取群内全部消息」
- 开启「机器人主动在群聊内发言」

### 4. 安装依赖

```bash
pip install qq-botpy
```

兼容 Python 3.8+ [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/pythonsdk/)

## 三、API 接口总览

### 鉴权

获取 `access_token`（有效期 7200 秒，需定时刷新）[$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html)：

```
POST https://api.bot.qq.com/app/getAppAccessToken
Body: {"appId": "APPID", "clientSecret": "CLIENTSECRET"}
返回: {"access_token": "xxx", "expires_in": "7200"}
```

调用其他 API 时在 Header 中携带：`Authorization: QQBot {ACCESS_TOKEN}` [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html)

### WebSocket 事件订阅

| Intent 名称               | 值         | 事件                                                                                                   |
| ----------------------- | --------- | ---------------------------------------------------------------------------------------------------- |
| `GROUP_AND_C2C_EVENT`   | `1 << 25` | 群@机器人消息、私聊消息、机器人加入/退出群、群主动消息开关                                                                       |
| `PUBLIC_GUILD_MESSAGES` | `1 << 30` | 频道@机器人消息                                                                                             |
| `GUILD_MEMBERS`         | `1 << 1`  | 群成员加入/退出 [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/group/manage/event.html) |

### 核心接口

| 功能      | 方法   | URL                                               | 说明                                                                                                                                       |
| ------- | ---- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 发送群消息   | POST | `/v2/groups/{group_openid}/messages`              | 被动回复 5 分钟内有效 [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/send.html)                          |
| 发送私聊消息  | POST | `/v2/users/{openid}/messages`                     | 被动回复 60 分钟内有效                                                                                                                            |
| 设置群成员禁言 | POST | `/v2/groups/{group_openid}/restrict_chat_setting` | 最大 30 天，需管理员权限 [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_restrict_chat_setting.post.html) |
| 查询群禁言状态 | GET  | `/v2/groups/{group_openid}/restrict_chat_setting` | 含全员禁言 + 成员禁言列表 [$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_restrict_chat_setting.get.html)  |

### 关于踢人

QQ 官方机器人 **群聊 API 不支持踢出群成员**。频道（Guild）场景有 `DELETE /guilds/{guild_id}/members/{user_id}` 接口可移除频道成员，但群聊场景无此能力。如需踢人，只能通过禁言间接管理。

### 消息频控

| 场景 | 主动消息     | 被动回复       |
| -- | -------- | ---------- |
| 群聊 | 每月 4 条/群 | 5 分钟内 5 次  |
| 私聊 | 每月 4 条/人 | 60 分钟内 4 次 |

群主开启「机器人主动在群聊内发言」后，主动消息频控为 20 QPM（每群每分钟）[$TRAE\_REF](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/send.html)

## 四、代码实现

核心结构：

```python
import botpy
from botpy.message import Message

class MyBot(botpy.Client):
    async def on_group_at_message_create(self, message):
        # 收到群@消息 → 回复
        await self.api.post_group_message(
            group_openid=message.group_openid,
            msg_type=0,
            content="收到: " + message.content,
            msg_id=message.id
        )

intents = botpy.Intents(public_guild_messages=False)
intents.public_messages = True  # 群@消息 + 私聊消息
intents.guild_member = True     # 群成员进退
client = MyBot(intents=intents)
client.run(appid="你的AppID", token="你的AppSecret")
```

## 五、功能清单

| 功能     | 方法                             | 说明                   |
| ------ | ------------------------------ | -------------------- |
| 收到群@消息 | `on_group_at_message_create()` | 自动触发回调               |
| 收到私聊消息 | `on_c2c_message_create()`      | 自动触发回调               |
| 发送群消息  | `post_group_message()`         | 被动回复（需 msg\_id）或主动推送 |
| 发送私聊消息 | `post_c2c_message()`           | 同上                   |
| 禁言群成员  | `mute_member()`                | 设置到期时间               |
| 解除禁言   | `unmute_member()`              | 清除禁言                 |
| 查询禁言列表 | `get_mute_list()`              | 返回当前禁言中的成员           |
| 撤回消息   | `delete_message()`             | 仅限机器人自己发的消息          |

