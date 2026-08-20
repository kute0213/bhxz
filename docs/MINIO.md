# MinIO 用户图片配置

网站将用户头像和主页个性背景存入私有 MinIO Bucket，数据库仅保存对象键。

## 本地配置

复制 `.env.example` 为项目根目录的 `.env`，填写实际连接信息后直接启动网站。
`.env` 已加入 `.gitignore`，不会随代码提交。系统环境变量的优先级高于 `.env`。

## 环境变量

网站直接运行在服务器宿主机时：

```bash
export MINIO_ENDPOINT=127.0.0.1:9000
export MINIO_ACCESS_KEY=root
export MINIO_SECRET_KEY='请替换为实际密码'
export MINIO_BUCKET=binhai
export MINIO_SECURE=0
```

网站运行在 Docker 容器中时，先将网站容器加入 `binhai-internal` 网络，并使用：

```bash
docker network connect binhai-internal 网站容器名
```

```text
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=root
MINIO_SECRET_KEY=请替换为实际密码
MINIO_BUCKET=binhai
MINIO_SECURE=0
```

`MINIO_BUCKET` 应改成服务器上实际创建的 Bucket 名称。使用的账号如果拥有创建
Bucket 权限，则目标 Bucket 不存在时网站也会自动创建。

## 安装依赖

```bash
pip install -r requirements.txt
```

修改环境变量后必须重启网站进程或网站容器。MinIO API 无需开放公网，Bucket 也
无需设置公开访问策略；浏览器通过网站的 `/media/` 路由读取图片。
