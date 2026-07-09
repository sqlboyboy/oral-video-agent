# 云端队列与 AutoDL Worker MVP

第一版采用半自动调度：

```text
用户提交任务 -> 腾讯云队列入库 -> 通知管理员开 AutoDL
AutoDL 开机 -> worker 自动领取任务 -> 生成/上传/回报
队列清空且空闲一段时间 -> worker 自动关机或提醒关机
```

## 组件

- `services/cloud/app`：腾讯云控制中心 API，负责队列、worker 心跳、领取任务、进度和通知。
- `services/cloud/worker/autodl_worker.py`：AutoDL 机器上的 worker。
- `services/cloud/worker/oral-video-autodl-worker.service`：AutoDL 开机自启动模板。
- `services/cloud/deploy/docker-compose.yml`：腾讯云轻量服务器上的 API 部署模板。

## 用户提交前置条件

云端生成任务只能由已激活且已绑定邮箱账号的客户端提交：

```text
激活码激活软件 -> 邮箱验证码绑定账号 -> 后台按邮箱手动加点 -> 云端任务冻结/扣点
```

激活码只控制软件能不能使用，不赠送点数；点数余额属于邮箱账号。后台仍保留任务/充值码等内部兼容接口，但用户端不展示充值码兑换。

## 本地运行控制中心

```powershell
cd services/cloud
Copy-Item .env.example .env
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 18080
```

创建测试任务：

```powershell
curl.exe -X POST http://127.0.0.1:18080/api/admin/jobs `
  -H "X-Admin-Token: change-admin-token" `
  -H "Content-Type: application/json" `
  -d "{\"payload\":{\"duration_seconds\":600},\"priority\":0}"
```

## 腾讯云部署

```bash
cd /opt/oral-video-agent
git clone <repo-url> repo
cd repo/services/cloud/deploy
cp .env.example .env
nano .env
docker compose up -d --build
```

Nginx 反代到 `127.0.0.1:18080`，后续域名备案/解析完成后再签发 HTTPS 证书。

## AutoDL Worker 部署

把以下文件复制到 AutoDL：

```text
services/cloud/worker/autodl_worker.py
services/cloud/worker/.env.example -> /root/oral-video-agent-cloud-worker/.env
services/cloud/worker/oral-video-autodl-worker.service
```

也可以直接使用安装脚本：

```bash
mkdir -p /root/oral-video-agent-cloud-worker
cp autodl_worker.py /root/oral-video-agent-cloud-worker/
sudo bash install_autodl_worker.sh
```

如果从腾讯云服务器通过 SSH 密码部署到 AutoDL，可以使用：

```bash
cd /opt/oral-video-agent/cloud/worker
AUTODL_HOST=gpu.example.com \
AUTODL_PORT=22 \
AUTODL_USER=root \
AUTODL_PASSWORD='AutoDL密码' \
CLOUD_API_BASE=https://api.example.com \
WORKER_TOKEN='腾讯云deploy/.env里的WORKER_TOKEN' \
ENABLE_AUTODL_SHUTDOWN=false \
bash deploy_autodl_worker_via_ssh.sh
```

配置 `/root/oral-video-agent-cloud-worker/.env`：

```env
CLOUD_API_BASE=https://api.example.com
WORKER_TOKEN=你的worker token
WORKER_ID=autodl-4090-1
ENABLE_AUTODL_SHUTDOWN=false
IDLE_SHUTDOWN_MINUTES=15
```

先保持 `ENABLE_AUTODL_SHUTDOWN=false` 做联调。确认任务完成后再改成：

```env
ENABLE_AUTODL_SHUTDOWN=true
SHUTDOWN_COMMAND='sudo shutdown -h now'
```

启用开机自启动：

```bash
sudo cp oral-video-autodl-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oral-video-autodl-worker
```

AutoDL 容器环境可能没有 systemd。没有 systemd 时使用：

```bash
cd /root/oral-video-agent-cloud-worker
bash start_worker_nohup.sh
tail -f worker.log
```

停止：

```bash
bash stop_worker_nohup.sh
```

## 自动关机原理

worker 连续空闲达到 `IDLE_SHUTDOWN_MINUTES` 后执行：

```bash
sudo shutdown -h now
```

第一版必须满足这些条件再打开自动关机：

- worker 已能稳定领取任务。
- 成品上传和任务回报都成功。
- 空闲阈值不低于 15 分钟。
- AutoDL 任务目录里没有未上传的结果文件。

## 真实生成入口

worker 默认部署 `run_render.sh`，它会读取 worker 写入的本地 `job.json`，把已下载到本机的源视频上传到 AutoDL 上的本地 FastAPI 生成后端，调用 `/api/tasks/{id}/render`，再把生成的 MP4 写到 `ORAL_VIDEO_OUTPUT_PATH`，交回 worker 上传 COS。

```env
RENDER_COMMAND='/root/oral-video-agent-cloud-worker/run_render.sh {job_json} {output_path}'
LOCAL_RENDER_API_BASE=http://127.0.0.1:8000
LOCAL_RENDER_API_TIMEOUT_SECONDS=7200
```

运行前需要先在 AutoDL 上启动本地生成 API，并确认 `LOCAL_RENDER_API_BASE/api/health` 可访问。命令成功后，worker 会把该成品上传到云端下发的 COS 临时上传 URL，并回报完成。
