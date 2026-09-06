# EasyAuth 绑定账号功能实现文档

> 适用版本：Minecraft Java 1.20.1 Fabric · EasyAuth 模组
> 存储方式：SQLite（EasyAuth 默认数据库）
> 操作系统：全平台兼容（Windows / Linux / macOS）

***

## 一、功能概述

绑定账号功能允许用户通过输入**游戏根目录**、**用户名**和**密码**来验证身份，将游戏账号与外部系统（如网站、管理后台、机器人等）绑定。

### 核心流程

```
用户输入
  ├─ 游戏根目录路径（绝对路径）
  ├─ 游戏用户名
  └─ 密码
      ↓
读取 EasyAuth 数据库 → 验证 BCrypt 哈希 → 返回绑定结果
```

***

## 二、EasyAuth 数据库结构

### 2.1 数据库位置

数据库文件位于游戏根目录下的固定路径：

```
{游戏根目录}/EasyAuth/easyauth.db
```

示例：

| 操作系统    | 路径示例                                         |
| ------- | -------------------------------------------- |
| Windows | `D:\minecraft-server\EasyAuth\easyauth.db`   |
| Linux   | `/opt/minecraft/server/EasyAuth/easyauth.db` |
| macOS   | `~/minecraft/server/EasyAuth/easyauth.db`    |

### 2.2 表结构

**表名：`easyauth`**

| 列名               | 类型           | 说明                  |
| ---------------- | ------------ | ------------------- |
| `id`             | INTEGER      | 自增主键                |
| `username`       | VARCHAR(255) | 用户名（原始大小写）          |
| `username_lower` | VARCHAR(255) | 小写用户名（查询键）          |
| `uuid`           | VARCHAR(255) | 玩家 UUID             |
| `last_ip`        | VARCHAR(45)  | 最后登录 IP             |
| `data`           | TEXT         | **JSON 文本**，存储密码哈希等 |

### 2.3 data 字段格式

`data` 列是一个 JSON 字符串，结构示例如下：

```json
{
    "password": "$2a$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJ",
    "last_ip": "192.168.1.100",
    "totp_secret": null,
    "registration_date": 1693567890,
    "last_login": 1693654321
}
```

关键字段：

| 字段                  | 类型            | 说明                                 |
| ------------------- | ------------- | ---------------------------------- |
| `password`          | string        | **BCrypt 哈希**（`$2a$12$...`，12 轮加密） |
| `last_ip`           | string / null | 最后登录 IP                            |
| `totp_secret`       | string / null | 双因素认证密钥                            |
| `registration_date` | number        | 注册时间戳（秒）                           |
| `last_login`        | number        | 最后登录时间戳（秒）                         |

### 2.4 密码哈希算法

EasyAuth 1.20.1 默认使用 **BCrypt**，参数如下：

* 算法标识：`$2a$`（BCrypt）

* 加密轮数：`12`（cost factor）

* 哈希长度：60 字符

* 示例：`$2a$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36PQm4sEPhM6hJ6Gme7yG.K`

***

## 三、依赖安装

### 3.1 所需依赖

```bash
# 核心依赖
pip install bcrypt
```

### 3.2 各平台注意事项

**Windows**：`bcrypt` 需要 C 编译器，推荐直接安装预编译 wheel：

```bash
pip install bcrypt
```

如遇编译错误，可安装 Microsoft C++ Build Tools，或使用 `pip install bcrypt --only-binary :all:`。

**Linux/macOS**：直接安装即可，系统自带编译器。

***

## 四、绑定账号实现

### 4.1 核心函数：`bind_account()`

```python
import os
import json
import sqlite3
import bcrypt
from pathlib import Path
from typing import Optional


def bind_account(server_path: str, username: str, password: str) -> dict:
    """
    绑定账号：验证用户名和密码是否匹配
    
    参数:
        server_path: 游戏根目录的绝对路径（跨平台，支持 / 和 \\）
        username:    游戏用户名（不区分大小写）
        password:    明文密码
    
    返回:
        {
            "success": bool,         # 是否绑定成功
            "message": str,          # 提示信息（中文）
            "username": str,         # 实际用户名（保持原始大小写）
            "uuid": str | None,      # 玩家 UUID（成功时返回）
            "error_code": str | None # 错误码（失败时返回）
        }
    
    错误码说明:
        DB_NOT_FOUND    - 数据库文件不存在
        PLAYER_NOT_FOUND - 玩家未注册
        WRONG_PASSWORD  - 密码错误
        DB_ERROR        - 数据库读取异常
        HASH_ERROR      - 密码哈希格式异常
    """
    # ── 第 1 步：构建数据库路径（跨平台兼容） ──
    db_path = os.path.join(server_path, "EasyAuth", "easyauth.db")
    
    # 统一使用 Path 再检查一次（兼容 os.path.join 的各种情况）
    db_path = str(Path(db_path).resolve())
    
    # ── 第 2 步：检查数据库文件是否存在 ──
    if not os.path.isfile(db_path):
        return {
            "success": False,
            "message": "未找到 EasyAuth 数据库文件，请确认游戏根目录路径正确",
            "username": username,
            "uuid": None,
            "error_code": "DB_NOT_FOUND",
        }
    
    # ── 第 3 步：读取数据库 ──
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 查询玩家（使用小写用户名作为查询键）
        cursor.execute(
            "SELECT * FROM easyauth WHERE username_lower = ?",
            (username.strip().lower(),)
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        return {
            "success": False,
            "message": f"数据库读取失败: {str(e)}",
            "username": username,
            "uuid": None,
            "error_code": "DB_ERROR",
        }
    
    # ── 第 4 步：检查玩家是否存在 ──
    if not rows:
        return {
            "success": False,
            "message": f"玩家 '{username}' 未在服务器注册",
            "username": username,
            "uuid": None,
            "error_code": "PLAYER_NOT_FOUND",
        }
    
    # 优先精确匹配原始大小写
    player = None
    for row in rows:
        if row["username"] == username:
            player = dict(row)
            break
    if player is None:
        player = dict(rows[0])
    
    # ── 第 5 步：解析并验证密码 ──
    try:
        data = json.loads(player["data"])
        stored_hash = data.get("password", "")
    except (json.JSONDecodeError, KeyError) as e:
        return {
            "success": False,
            "message": "玩家数据解析失败",
            "username": username,
            "uuid": player.get("uuid"),
            "error_code": "HASH_ERROR",
        }
    
    if not stored_hash:
        return {
            "success": False,
            "message": "该玩家未设置密码，无法绑定",
            "username": username,
            "uuid": player.get("uuid"),
            "error_code": "HASH_ERROR",
        }
    
    # ── 第 6 步：BCrypt 密码比对 ──
    try:
        password_bytes = password.encode("utf-8")
        hash_bytes = stored_hash.encode("utf-8")
        
        if bcrypt.checkpw(password_bytes, hash_bytes):
            return {
                "success": True,
                "message": f"账号 '{player['username']}' 绑定成功",
                "username": player["username"],
                "uuid": player.get("uuid"),
                "error_code": None,
            }
        else:
            return {
                "success": False,
                "message": "密码错误，请重试",
                "username": username,
                "uuid": player.get("uuid"),
                "error_code": "WRONG_PASSWORD",
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"密码验证异常: {str(e)}",
            "username": username,
            "uuid": player.get("uuid"),
            "error_code": "HASH_ERROR",
        }
```

### 4.2 辅助函数：`get_server_db_path()`

```python
def get_server_db_path(server_path: str) -> Optional[str]:
    """
    获取 EasyAuth 数据库的完整路径
    
    跨平台兼容处理：
      - Windows: 自动处理反斜杠和正斜杠混用
      - Linux/macOS: 保持正斜杠路径
      - 自动解析相对路径为绝对路径
      - 自动处理符号链接
    """
    try:
        # 跨平台路径拼接
        db_path = os.path.join(server_path, "EasyAuth", "easyauth.db")
        # 解析为绝对路径（处理相对路径、符号链接、.. 等）
        resolved = Path(db_path).resolve()
        # 检查文件是否存在
        if resolved.is_file():
            return str(resolved)
        return None
    except Exception:
        return None
```

### 4.3 辅助函数：`get_all_players()`

```python
def get_all_players(server_path: str) -> list:
    """
    获取服务器所有注册玩家列表
    
    返回: [{"username": str, "uuid": str}, ...]
    """
    db_path = get_server_db_path(server_path)
    if not db_path:
        return []
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT username, uuid FROM easyauth")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []
```

***

## 五、完整使用示例

### 5.1 命令行示例

```python
#!/usr/bin/env python3
"""绑定账号命令行演示"""

import sys
from easyauth_bind import bind_account

def main():
    server_path = input("请输入游戏根目录绝对路径: ").strip()
    username = input("请输入游戏用户名: ").strip()
    password = input("请输入密码: ").strip()
    
    result = bind_account(server_path, username, password)
    
    print("\n" + "=" * 40)
    print(f"状态: {'✓ 绑定成功' if result['success'] else '✗ 绑定失败'}")
    print(f"提示: {result['message']}")
    if result['success']:
        print(f"用户名: {result['username']}")
        print(f"UUID:   {result['uuid']}")
    else:
        print(f"错误码: {result['error_code']}")
    print("=" * 40)

if __name__ == "__main__":
    main()
```

### 5.2 批量验证示例

```python
def batch_verify(server_path: str, accounts: list) -> list:
    """
    批量验证多个账号
    
    参数:
        server_path: 游戏根目录
        accounts: [{"username": "Steve", "password": "123"}, ...]
    
    返回: [{"username": str, "success": bool, "message": str}, ...]
    """
    results = []
    for acc in accounts:
        result = bind_account(server_path, acc["username"], acc["password"])
        results.append({
            "username": acc["username"],
            "success": result["success"],
            "message": result["message"],
        })
    return results
```

### 5.3 Flask Web API 示例

```python
from flask import Flask, request, jsonify
from easyauth_bind import bind_account

app = Flask(__name__)

@app.route("/api/bind", methods=["POST"])
def api_bind():
    """绑定账号 API"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请提供 JSON 数据"}), 400
    
    server_path = data.get("server_path", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not all([server_path, username, password]):
        return jsonify({"success": False, "message": "参数不完整"}), 400
    
    result = bind_account(server_path, username, password)
    status = 200 if result["success"] else 401
    return jsonify(result), status

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

***

## 六、各平台路径处理说明

### 6.1 路径处理策略

函数内部使用 `os.path.join` + `pathlib.Path.resolve()` 双重处理，确保全平台兼容：

```python
# 用户输入 → 跨平台拼接 → 解析为绝对路径
# Windows: "D:\mc\server" + "EasyAuth" + "easyauth.db" = "D:\mc\server\EasyAuth\easyauth.db"
# Linux:   "/opt/mc/server" + "EasyAuth" + "easyauth.db" = "/opt/mc/server/EasyAuth/easyauth.db"
```

### 6.2 常见问题处理

| 问题                       | 处理方式                    |
| ------------------------ | ----------------------- |
| 用户输入末尾带/不带斜杠             | `os.path.join` 自动处理     |
| 相对路径（如 `./server`）       | `Path.resolve()` 转为绝对路径 |
| Windows 反斜杠 vs Linux 正斜杠 | `os.path.join` 自动适配     |
| 路径包含空格或中文                | `os.path.isfile()` 原生支持 |
| 路径符号链接                   | `Path.resolve()` 自动追踪   |

***

## 七、安全注意事项

### 7.1 密码安全

* **不要记录明文密码日志**：函数内部只在内存中比对，不存储明文

* **不要传输明文密码**：生产环境务必使用 HTTPS

* **限制验证频率**：建议对同一 IP 的验证请求做限流（如每分钟最多 10 次）

### 7.2 数据库安全

* **不要将数据库文件暴露在 Web 可访问目录下**

* **生产环境建议将数据库路径配置为环境变量**，而非硬编码

* **数据库文件权限**：建议设置为 `600`（仅 owner 可读写）

### 7.3 输入校验

```python
# 建议在调用 bind_account 前做基础校验
def validate_input(server_path: str, username: str, password: str) -> str:
    """校验输入合法性，返回错误信息，None 表示通过"""
    if not server_path or not server_path.strip():
        return "游戏根目录不能为空"
    if not username or not username.strip():
        return "用户名不能为空"
    if len(username) > 16:
        return "用户名过长（MC 限制 16 字符）"
    if not password:
        return "密码不能为空"
    # 检查路径是否包含非法字符（Windows 限制）
    illegal = '<>:"|?*'
    if any(c in server_path for c in illegal):
        return "路径包含非法字符"
    return None
```

***

## 八、错误码速查表

| 错误码                | 触发条件       | 建议处理                  |
| ------------------ | ---------- | --------------------- |
| `DB_NOT_FOUND`     | 数据库文件不存在   | 提示用户检查路径              |
| `PLAYER_NOT_FOUND` | 用户名未注册     | 提示用户先在游戏内注册           |
| `WRONG_PASSWORD`   | 密码错误       | 提示用户重试                |
| `DB_ERROR`         | 数据库损坏或权限不足 | 检查文件权限或完整性            |
| `HASH_ERROR`       | 密码哈希格式异常   | 可能是旧版数据，建议升级 EasyAuth |

***

## 九、完整代码文件

完整代码见同级文件 [easyauth\_bind\_account.py](computer:///workspace/easyauth_bind_account.py)。

***

## 十、版本更新记录

| 版本  | 日期         | 变更说明            |
| --- | ---------- | --------------- |
| 1.0 | 2026-09-06 | 初始版本，实现绑定账号核心功能 |

