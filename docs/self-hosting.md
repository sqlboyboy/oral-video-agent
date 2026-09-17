# 自托管部署

本指南说明开源用户需要部署哪些服务，以及客户端如何连接。示例域名均为占位符，请替换为自己的地址；仓库不提供作者的服务账号和模型凭据。

## 组件与连接

| 组件 | 运行位置 | 主要职责 |
|---|---|---|
| Flutter Windows | 用户电脑 | 创作工作台、本地素材、预览与发布 |
| Flutter Android | 用户手机 | 移动创作、预览和保存相册 |
| 本地 API `services/api` | Windows / 生成环境 | 本地素材、媒体处理与 Provider 接口 |
| 控制中心 `services/cloud` | 自己的服务器 | 账号、权限、任务、文件地址与 Worker 管理 |
| Worker | GPU 服务器，例如 AutoDL | 领取任务、下载素材、执行生成并回报 |
| CosyVoice / HeyGem | GPU 环境 | 声音与数字人模型服务 |

## 1. 先验证控制中心

从所选产品分支的仓库根目录执行 PowerShell 命令：

```powershell
cd services/cloud
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync
```

为管理员密码、管理令牌、Worker 令牌和存储签名密钥分别生成随机值，并写入 `.env`，不要复用示例值：

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

配置变量包括 `ADMIN_PASSWORD`、`ADMIN_TOKEN`、`WORKER_TOKEN`、`COS_MOCK_SECRET`。本机开发时，请在 `.env` 保持 `DATABASE_URL=`、`REDIS_URL=` 为空（开发模板默认如此），然后设置文件存储：

```powershell
$env:OBJECT_STORAGE_BACKEND = "local"
$env:OBJECT_STORAGE_ROOT = "./data/object_storage"
$env:CLOUD_PUBLIC_BASE_URL = "http://127.0.0.1:18080"
$env:EMAIL_PROVIDER = "console"
uv run uvicorn app.main:app --host 127.0.0.1 --port 18080
```

打开 `http://127.0.0.1:18080/api/health` 检查服务，管理页面位于 `/admin`，API 文档位于 `/docs`。此地址只适合本机调试；手机和远程 Worker 无法通过自己的 `127.0.0.1` 访问这台机器。

`EMAIL_PROVIDER=console` 用于本地验证，验证码从服务日志中获取。正式部署应配置邮件服务；示例中的发件地址与模板 ID 必须自行填写。

## 2. 部署供客户端访问的云端 API

Linux 服务器中，从所选产品分支进入：

```bash
cd services/cloud/deploy
cp .env.example .env
# 编辑 .env，填入自己的密码、令牌、数据库连接和外部 HTTPS 地址。
docker compose up -d --build
```

部署配置包含 PostgreSQL、Redis、cloud-api、scheduler 和 Nginx。内置 Nginx 配置提供 HTTP 入口，外部 HTTPS 需在服务器反向代理层配置证书。

关键配置：

- `DATABASE_URL`：指向部署中的 PostgreSQL，密码与 `POSTGRES_PASSWORD` 一致。
- `REDIS_URL`：指向部署中的 Redis。
- `CLOUD_PUBLIC_BASE_URL`：手机和 Worker 都能访问的 HTTPS 地址。
- `ADMIN_COOKIE_SECURE=true`：在 HTTPS 部署中启用。
- `ADMIN_PASSWORD`、`ADMIN_TOKEN`、`WORKER_TOKEN`：使用独立随机值。
- `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`：配置自己的文案服务。

`.env.example` 是模板，直接复制模板并不等于已经完成安全配置。不要把本地 `services/api` 不带用户鉴权的桌面接口直接暴露到公网。

## 3. 配置账号与使用权限

登录自己部署的 `/admin`：

1. 创建或管理云端账号。
2. PC 端使用后台提供的软件激活流程；安卓用户通过移动端注册或登录入口进入。
3. 按所选分支的后台功能配置使用期限、点数及相关权限。
4. 在客户端登录并检查账号状态，再提交生成任务。

软件激活、账号登录和生成权限分别管理。仅有登录账号并不代表自动具备全部生成权限。后台详情见 [云端管理后台](cloud-admin-web.md)。

## 4. 选择素材存储

### 本地对象存储

```dotenv
OBJECT_STORAGE_BACKEND=local
OBJECT_STORAGE_ROOT=/data/object_storage
CLOUD_PUBLIC_BASE_URL=https://api.example.com
```

文件保存在控制中心磁盘，通过签名文件接口上传和下载。为部署卷配置容量与备份策略。

### 腾讯云 COS

```dotenv
OBJECT_STORAGE_BACKEND=cos
COS_BUCKET=your-bucket
COS_REGION=your-region
COS_SECRET_ID=
COS_SECRET_KEY=
```

在本地 `.env` 填入自己的 COS 凭据。此模式下，客户端和 Worker 使用签名 URL 与 COS 传输文件。

## 5. 配置 GPU 生成环境

分别准备 CosyVoice 和 HeyGem 的运行环境、模型权重及 API 服务。仓库中的集成代码不能代替上游模型安装；所需显存和驱动取决于模型及生成配置。

- CosyVoice API 配置入口：`VOICE_BASE_URL`。
- HeyGem API 配置入口：`HEYGEM_BASE_URL`。
- Worker 入口：`services/cloud/worker/autodl_worker.py`。
- 生成流程入口：`services/cloud/worker/run_render.py`。

复制 Worker 的 `.env.example` 为 `.env`，设置：

```dotenv
CLOUD_API_BASE=https://api.example.com
WORKER_TOKEN=
WORKER_ID=my-gpu-worker
ENABLE_AUTODL_SHUTDOWN=false
RENDER_COMMAND='/root/oral-video-agent-cloud-worker/run_render.sh {job_json} {output_path}'
```

`WORKER_TOKEN` 必须与控制中心一致，命令路径必须匹配自己的部署目录。为生成流程安装 Python 依赖和 FFmpeg，并确认模型 API 可访问后，再启动 Worker：

```bash
python autodl_worker.py
```

不要将模拟任务完成当作真实生成成功；启用正式生成命令后，用自己的短素材验证下载、推理、上传与回报链路。

## 6. PC 通过 SSH 访问 GPU 服务（可选）

如采用 PC 本地后端调用远端模型的模式，在仓库根目录运行：

```powershell
./scripts/start_autodl_heygem_tunnel.ps1 -SshHost gpu.example.com -SshPort 22 -KeyPath "$env:USERPROFILE/.ssh/my_gpu_key"
```

将主机、端口和私钥路径换成自己的配置。脚本映射本地 `16008` 到远端 HeyGem `6008`，本地 `16010` 到 CosyVoice `6010`。也支持 `HEYGEM_SSH_HOST`、`HEYGEM_SSH_PORT`、`HEYGEM_SSH_KEY_PATH` 环境变量。

## 7. 配置与构建客户端

客户端使用编译参数 `CLOUD_API_BASE` 指向自己的控制中心。PC 本地 API 地址使用 `API_BASE`，默认 `http://127.0.0.1:8000`。

手机应连接有效的 HTTPS 地址。修改编译参数后需要重新运行或构建客户端；已有客户端保存的云端地址也需要检查。

验证顺序：控制中心健康检查 → 账号权限 → Worker 心跳 → 模型 API → 小文件上传 → 短任务生成 → 下载预览。这样可以把网络、权限和模型问题分别定位。
