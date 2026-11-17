# 在 MCSManager（MCSM）面板中部署本 Flask 应用

本文说明如何把「滨海小镇」社区网站作为一个 **MCSM 通用应用实例** 运行起来。

> MCSM 本身没有「导入 Flask 项目」的专用入口，它的作用相当于一个带网页文件管理、终端和进程守护的启动器。因此思路是：
> **新建通用应用实例 → 上传代码 → 在实例终端装依赖 → 用启动命令拉起 `app.py` → 由 MCSM 负责守护和自动重启。**

## 目录

1. [部署前准备](#1-部署前准备)
2. [新建通用应用实例](#2-新建通用应用实例)
3. [上传代码](#3-上传代码)
4. [安装依赖（创建虚拟环境）](#4-安装依赖创建虚拟环境)
5. [配置启动命令](#5-配置启动命令)
6. [首次启动与初始化](#6-首次启动与初始化)
7. [数据目录与备份](#7-数据目录与备份)
8. [升级应用](#8-升级应用)
9. [可选：Nginx 反向代理 + HTTPS](#9-可选nginx-反向代理--https)
10. [可选：MCSM Docker 实例](#10-可选mcsm-docker-实例)
11. [常见问题](#11-常见问题)
12. [上线检查清单](#12-上线检查清单)
13. [Windows 服务器部署与编码](#13-windows-服务器部署与编码)

## 1. 部署前准备

| 项目 | 要求 |
| --- | --- |
| 面板 | MCSM v10.x（菜单名称可能略有差异，选择「通用应用 / 应用实例」即可） |
| 系统 | Linux（推荐 Debian 12 / Ubuntu 22.04 及以上，**不建议 Alpine**，`duckdb` / `bcrypt` 的预编译轮子依赖 glibc）或 Windows（见第 13 节） |
| Python | 3.10 ~ 3.12（应用要求 3.8+，但新版依赖在 3.10+ 上最省事） |
| 可选组件 | `ffmpeg`（音频直播必需）、`git`（想直接从 GitHub 拉代码时需要） |
| 端口 | 应用固定监听 **5000**（`0.0.0.0:5000`），需在云服务器安全组和系统防火墙中放行 |

在宿主机安装系统组件（需要 root；面板本身以 root 运行时可直接执行）：

```bash
apt update
apt install -y python3 python3-venv python3-pip ffmpeg git unzip
```

> 只需安装一次。若服务器上已有 Python 3.10+ 与 ffmpeg，可跳过。

## 2. 新建通用应用实例

1. 打开 MCSM 面板 → 左侧 **应用实例** → **新建实例**。
2. 实例类型选择 **通用应用**（部分版本叫「自定义应用」「Application」），不要选 Minecraft 开服模板。
3. 填写实例名称（如 `bhxz-web`），工作目录保持面板默认的实例目录即可。
4. 创建后进入实例详情页，确认右上角能看到 **文件管理** 和 **终端**。

> 通用应用实例不会替应用分配端口，端口由 `app.py` 自己监听，面板只负责进程守护。

## 3. 上传代码

两种方式任选其一。

### 方式 A：上传发布包（推荐）

1. 在你自己的电脑上（项目根目录）执行：

   ```bash
   python scripts/build/package.py
   ```

   会在 `release/` 生成 `bhxz-YYYYMMDD-HHMMSS.zip`。该压缩包已排除数据库、上传文件、日志、`.venv` 等运行期数据。

2. MCSM 实例详情 → **文件管理** → 进入实例根目录 → **上传** 该 zip。
3. 右键 zip 文件 → **解压**，把内容解压到**当前目录**（压缩包内没有额外的一级文件夹，解压后应直接看到 `app.py`、`config.py`、`requirements.txt`、`static/`、`services/` 等）。

### 方式 B：终端内 git clone

在实例详情 → **终端** 中执行（要求实例目录为空）：

```bash
git clone https://github.com/kute0213/bhxz.git .
```

> 若提示目录非空，先确认没有上传过其他文件，或清空实例目录后再执行。
> 无论哪种方式，**不要**把本地开发时的 `uploads/`、`logs/`、`.venv/` 一起上传。

## 4. 安装依赖（创建虚拟环境）

在实例 **终端** 中执行（终端的工作目录就是实例根目录）：

> Windows 的虚拟环境路径与命令不同，请直接看第 13 节；本节为 Linux 命令。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/pip install -r requirements.txt
```

国内服务器可以加清华镜像加速：

```bash
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

安装完成后检查关键依赖：

```bash
.venv/bin/python -c "import flask, waitress, duckdb, bcrypt; print('deps ok')"
ffmpeg -version | head -n 1
```

> `requirements.txt` 中的 `pywinpty` 带 Windows 平台标记，在 Linux 上会自动跳过，无需处理。

## 5. 配置启动命令

在 MCSM 实例详情 → **实例设置**（或「配置」）中设置：

| 配置项 | 值 |
| --- | --- |
| 启动命令 | `bash start.sh` |
| 工作目录 | 实例根目录（默认值，保持不动） |
| 停止命令（若面板提供） | 留空，使用面板默认停止方式（会向进程发送终止信号） |
| 自动重启 | 建议开启 |

然后在实例根目录通过 **文件管理** 新建 `start.sh`：

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec .venv/bin/python app.py
```

并赋予执行权限（终端中执行一次）：

```bash
chmod +x start.sh
```

> 不想新建脚本时，也可以把启动命令直接写成 `.venv/bin/python app.py`。
> Windows 使用 `start.bat` + `cmd /c start.bat`，并必须配置 UTF-8 环境变量，见第 13 节。
> 二选一即可，**不要**在面板终端里手动 `python app.py` 之后又点实例「启动」，否则会因 5000 端口被占用而启动失败。

启动命令说明：

* 应用使用 Waitress 作为生产 WSGI 服务器（`core/server.py`），无需 gunicorn / uWSGI。
* 进程监听 `0.0.0.0:5000`，不要用 `flask run` 启动（会绕过 Waitress 与防火墙包装）。
* 应用已注册 `SIGTERM` / `SIGINT` 优雅退出，面板「停止」时会关闭数据库连接并清理后台线程。

## 6. 首次启动与初始化

1. 回到实例详情，点击 **启动**。
2. 查看实例 **输出 / 控制台**，正常时应看到类似：

   ```
   工作目录: /opt/mcsm/data/InstanceData/xxxxxxxx
   APP_ROOT:  /opt/mcsm/data/InstanceData/xxxxxxxx
   使用 Waitress 服务器，HTTP 模式运行 (端口 5000)
   ```

3. 首次启动会自动创建数据库、目录结构和默认管理员：

   | 用户名 | 密码 |
   | --- | --- |
   | `admin` | `admin1324` |

4. 浏览器访问 `http://服务器IP:5000`，登录后进入 **管理后台** `http://服务器IP:5000/admin`，**第一时间修改默认密码**。

> 如果实例显示「运行中」但外网打不开，优先检查：云服务器安全组是否放行 5000、系统防火墙（`ufw` / `firewalld`）是否放行、端口是否被其他程序占用。

## 7. 数据目录与备份

运行期数据全部在项目目录内，升级代码时**必须保留**：

| 路径 | 内容 |
| --- | --- |
| `uploads/db/site.db` | 站点数据库（用户、配置、内容等） |
| `uploads/` | 上传的音频、背景图、附件、直播临时目录等 |
| `logs/` | 运行日志（可选保留） |

备份目录默认是项目**上一级**的 `bhxz_backups`（即实例目录的兄弟目录）。在 MCSM 多实例环境下建议改成实例内的绝对路径：

**管理后台 → 系统设置 → 自动维护 → 备份目录**，例如：

```text
/opt/mcsm/data/InstanceData/你的实例ID/bhxz_backups
```

> 修改后新备份会写入新目录，旧备份不会自动迁移。

## 8. 升级应用

1. 在面板中先 **停止实例**。
2. 上传新的发布 zip，解压并**覆盖代码文件**；不要删除 `uploads/`、`logs/` 和 `.venv/`。
3. 若 `requirements.txt` 有变化，在终端重新执行：

   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

4. 点击 **启动**。

也可以直接使用后台的「一键更新」功能（`update.py`）：更新完成后按页面提示重启实例即可。

**面板托管建议**：一键更新会在终端打印进度条与日志。如果面板控制台不方便显示，或希望更新过程完全静默，可使用：

```bash
python update.py --quiet
```

或设置环境变量 `BHXZ_UPDATE_QUIET=1`，或把 `update.py` 顶部的 `PRINT_LOGS` 改为 `False`。静默模式不输出任何内容，只保留退出码（`0` 成功、非 `0` 失败）。

> Windows 中文控制台默认 GBK，直接运行旧版更新脚本可能报 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2591'`。当前版本已在启动时把输出流的编码错误策略改为 `replace`，并会把进度条字符自动降级为 ASCII，无需再手动 `chcp`。

## 9. 可选：Nginx 反向代理 + HTTPS

应用自身只提供 HTTP，HTTPS 建议在 Nginx / 内网穿透层终结。Nginx 与 MCSM 在同一台机器时，反向代理到 `127.0.0.1:5000`：

```nginx
server {
    listen 80;
    server_name example.com;

    # 音频等大文件上传
    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 音频直播实时流：必须关闭缓冲，否则会人为增加数秒延迟
    location /live/stream/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

说明：

* 应用只采信回环 / 内网 / `TRUSTED_PROXIES` 转发的 `X-Forwarded-*` 头（见 `core.shared.ip`），同机 Nginx 可直接传递真实 IP。
* 若使用 CDN 或内网穿透，请确认它们不会缓冲 `/live/stream/` 的响应。
* 上线 HTTPS 后，Session Cookie 会自动带上 `Secure` 标记。

## 10. 可选：MCSM Docker 实例

如果面板启用了 Docker 实例，也可以使用镜像方式：

1. 新建实例时选择 Docker，镜像填 `python:3.11-bookworm`。
2. 端口映射填写 `5000:5000`。
3. 把代码上传到实例挂载目录，并在容器终端中按第 4 节创建 `.venv`、安装依赖（`.venv` 位于挂载目录，容器重建后仍保留）。
4. 启动命令仍为 `bash start.sh`。

注意：容器内默认没有 ffmpeg，需要在容器内 `apt install ffmpeg`，而容器重建后会丢失；长期使用建议自行构建包含 ffmpeg 的镜像。**新手优先使用第 2~6 节的通用应用方式。**

## 11. 常见问题

| 现象 | 排查方向 |
| --- | --- |
| 实例启动后立即退出 | 看实例输出：多为依赖未装（漏了第 4 节）、Python 版本过低，或 5000 端口被占用（`ss -lntp \| grep 5000`） |
| 输出提示「端口已被占用，服务器退出」 | 已有另一个进程占用 5000。停掉重复的实例 / 手动启动的 `python app.py`；本应用端口固定在 `app.py` 入口，如需更换可修改 `run_server(app, port=5000)` 后重启 |
| 页面能打开但样式全丢 | 代码上传不完整，缺少 `static/`；重新上传完整发布包，不要只传 `.py` 文件 |
| 打不开管理后台 | 默认地址 `/admin`；确认已登录且账号为管理员 |
| 音频直播开播失败 | 服务器缺 ffmpeg：执行 `ffmpeg -version` 检查并安装；Linux 使用系统 ffmpeg，不需要 `uploads/ffmpeg/` |
| 直播播放延迟异常高 | 反向代理缓冲了流：按第 9 节对 `/live/stream/` 关闭 `proxy_buffering` |
| 上传大音频报 413 / 失败 | 检查 Nginx `client_max_body_size`，或在后台调整上传大小限制 |
| 面板重启后站点没起来 | 开启实例「自动重启」；确认不是面板版本限制 |
| `pip install` 编译 `duckdb` 很慢或失败 | 确认系统为 glibc（非 Alpine）、Python 为 3.10+；必要时安装 `build-essential python3-dev` 并升级 pip |
| Windows 控制台中文乱码 / `UnicodeEncodeError: 'gbk' codec can't encode character` | 没有开启 UTF-8 模式：按第 13 节创建 `start.bat`（`chcp 65001` + `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`），启动命令改为 `cmd /c start.bat` |
| Windows 实例启动后控制台长时间空白 | 标准输出被缓冲：在 `start.bat` 中加 `set PYTHONUNBUFFERED=1` |

## 12. 上线检查清单

* [ ] 默认管理员密码已修改
* [ ] 云安全组 / 系统防火墙已放行访问端口
* [ ] `uploads/` 与数据库位于持久化目录，且已配置独立备份路径
* [ ] `ffmpeg -version` 正常（需要音频直播时）
* [ ] 如需外网 HTTPS，已在反向代理层配置证书并关闭直播流缓冲
* [ ] 实例已开启自动重启
* [ ] Windows：已按第 13 节创建 `start.bat`，并确认控制台中文日志正常、无 `UnicodeEncodeError`

## 13. Windows 服务器部署与编码

MCSM 面板可以运行在 Windows，本项目也支持 Windows（`requirements.txt` 中的 `pywinpty` 会在 Windows 上自动安装，Linux 上自动跳过）。

但中文 Windows 的控制台默认代码页是 **GBK（cp936）**，而 MCSM 控制台按 UTF-8 读取实例输出。直接 `python app.py` 的典型症状是：

* 控制台中文日志乱码（「工作目录」「使用 Waitress 服务器」变成乱码）；
* 报错 `UnicodeEncodeError: 'gbk' codec can't encode character ...`；
* 输出长时间空白（标准输出被缓冲）。

因此 Windows 下**必须显式开启 UTF-8 模式**。其余步骤（新建实例、上传代码、备份、升级）与 Linux 完全相同。

### 13.1 目录与依赖

* 实例目录尽量使用**全英文、无空格**的路径，例如 `D:\MCSM\data\InstanceData\bhxz`。中文或含空格的路径在解压工具、ffmpeg 参数传递、虚拟环境脚本中容易出问题。
* 不要把项目放在 `C:\Program Files` 等需要管理员权限的目录，确保面板运行账号对 `uploads\`、`logs\` 有写权限。
* 在 MCSM 终端中创建虚拟环境并安装依赖：

  ```bat
  py -3.11 -m venv .venv
  .venv\Scripts\python.exe -m pip install -U pip
  .venv\Scripts\pip.exe install -r requirements.txt
  ```

  若系统没有 `py` 启动器，改用 `python -m venv .venv`。国内网络可追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

* ffmpeg：Windows 下把 `ffmpeg.exe` 放进 `uploads\ffmpeg\`（应用会优先使用该目录），或把 ffmpeg 加入系统 `PATH`。

### 13.2 启动脚本（关键）

在实例根目录新建 `start.bat`。**脚本内容只用 ASCII**，不要写中文注释（`.bat` 本身也有编码问题，中文注释在 GBK 下可能被执行成乱码命令）：

```bat
@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
cd /d "%~dp0"
".venv\Scripts\python.exe" app.py
```

MCSM 实例设置中的**启动命令**填写：

```bat
cmd /c start.bat
```

每个设置项的作用：

| 设置 | 作用 |
| --- | --- |
| `chcp 65001` | 把控制台代码页切到 UTF-8，避免中文日志在 MCSM 控制台显示为乱码 / 方块 |
| `PYTHONUTF8=1` | Python UTF-8 模式（3.7+），统一标准流与默认文件编码为 UTF-8 |
| `PYTHONIOENCODING=utf-8` | 兜底强制标准输入 / 输出 / 错误流使用 UTF-8 |
| `PYTHONUNBUFFERED=1` | 禁用输出缓冲，MCSM 控制台才能实时看到日志，而不是长时间空白 |
| `cd /d "%~dp0"` | 切到脚本所在目录（实例根目录），保证相对路径正确 |

注意事项：

* **不要**在脚本里使用 `start` 命令或另开窗口。那会让 Python 进程脱离 MCSM 的进程树，面板会认为实例已退出，也无法正确「停止」。
* 脚本最后一行直接运行 Python，不要加 `exit` 之类会吞掉退出码的命令。
* 如果环境变量因面板服务继承原因没有生效，可以把启动命令改为带解释器参数的形式：`".venv\Scripts\python.exe" -X utf8 app.py`。
* 用 PowerShell 手动排查时，环境变量写法不同：

  ```powershell
  $env:PYTHONUTF8 = "1"
  $env:PYTHONIOENCODING = "utf-8"
  .\.venv\Scripts\python.exe app.py
  ```

### 13.3 其他编码与平台注意事项

* **`.env` 必须是 UTF-8 无 BOM**。带 BOM 时，第一个配置项名前面会多出一个不可见字符，导致该项读取不到。建议用 VS Code / Notepad++ 确认编码为 `UTF-8`（不是 `UTF-8 with BOM`）。
* **解压发布包**优先使用 MCSM 文件管理自带解压或 7-Zip。Windows 资源管理器对 zip 内 UTF-8 中文文件名的支持不一致，可能出现文件名乱码。
* **MCSM 终端显示乱码**只影响显示，不影响程序运行。cmd 下先执行 `chcp 65001`；PowerShell 下执行 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`。
* **不要只依赖 `setx`**：`setx PYTHONUTF8 1` 只对之后新开的进程生效，MCSM 服务未必继承。写入 `start.bat` 才是可靠做法。
* **放行端口**（管理员 cmd）：

  ```bat
  netsh advfirewall firewall add rule name="bhxz-web 5000" dir=in action=allow protocol=TCP localport=5000
  ```

  云服务器还需要在控制台安全组放行 TCP 5000。
* **浏览器**：Windows 上建议用 Edge / Chrome 收听直播（支持 WebCodecs，Opus 低延迟通道可用）。
* **日志文件**本身由程序以 UTF-8 写入（`logs\`），用 UTF-8 编码打开即可；不要用记事本「另存为 ANSI」，否则中文会永久损坏。

### 13.4 验证是否生效

1. 启动实例后查看 MCSM 控制台，应正常显示：

   ```text
   工作目录: D:\MCSM\data\InstanceData\bhxz
   使用 Waitress 服务器，HTTP 模式运行 (端口 5000)
   ```

2. 若仍是乱码，依次检查：
   * 实例启动命令是否为 `cmd /c start.bat`（而不是直接 `python app.py`）；
   * `start.bat` 是否保存在**实例根目录**；
   * 终端执行 `chcp` 是否显示 `65001`；
   * 虚拟环境路径是否为 `.venv\Scripts\python.exe`（不是 Linux 的 `.venv/bin/python`）。
