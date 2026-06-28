# AutoDL 部署与启停指南

更新时间：2026-06-21

## 1. 当前实例

- GPU：NVIDIA RTX 4090D
- HeyGem：`/root/HeyGem-Linux-Python-Hack`
- HeyGem API：远端 `127.0.0.1:6008`
- CosyVoice 工作目录：`/root/autodl-tmp/cosyvoice`
- CosyVoice 模型：`/root/autodl-tmp/cosyvoice/models/CosyVoice-300M-25Hz`
- CosyVoice API：远端 `127.0.0.1:6010`

Windows 只运行业务后端、客户端、ASR 和最终 FFmpeg 合成；GPU 推理放在 AutoDL。

## 2. CUDA 兼容处理

该实例宿主驱动为 580 系列，启动 GPU 服务时需要：

```bash
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libcuda.so.580.76.05${LD_PRELOAD:+:$LD_PRELOAD}
```

HeyGem 的 `start_api.sh` 已加入该设置。CosyVoice 使用：

```bash
/root/autodl-tmp/cosyvoice/start_voice_api.sh
```

## 3. 启动服务

### HeyGem

```bash
cd /root/HeyGem-Linux-Python-Hack
./start_api.sh
```

确认：

```bash
curl http://127.0.0.1:6008/api/health
```

预期至少包含：

```json
{"status":"ok","gpu_available":true}
```

### CosyVoice

```bash
nohup /root/autodl-tmp/cosyvoice/start_voice_api.sh \
  >/root/autodl-tmp/cosyvoice/voice_api.log 2>&1 </dev/null &
```

确认：

```bash
curl http://127.0.0.1:6010/api/health
```

## 4. 停止服务

```bash
pkill -TERM -f 'uvicorn api_server:app'
pkill -TERM -f 'uvicorn voice_api:app'
```

确认没有残留：

```bash
pgrep -af 'uvicorn (api_server|voice_api):app'
```

## 5. Windows SSH 隧道

脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_autodl_heygem_tunnel.ps1
```

建立：

```text
127.0.0.1:16008 → AutoDL 127.0.0.1:6008
127.0.0.1:16010 → AutoDL 127.0.0.1:6010
```

脚本使用：

```text
%USERPROFILE%\.ssh\oral_video_autodl
```

## 6. HeyGem 文件传输

不要使用大文件 multipart 上传作为主链路。AutoDL 网关可能在约 120 秒后重置长时间无响应的连接。

当前实现：

1. FastAPI 使用 SCP 上传 WAV 和 MP4。
2. 远端文件放到 `/root/autodl-tmp/oral-video-agent-inputs/{uuid}`。
3. 调用 `POST /api/jobs/local`，传入远端文件路径。
4. 轮询 `GET /api/jobs/{job_id}`。
5. 下载 `GET /api/jobs/{job_id}/result`。

环境变量：

```env
HEYGEM_SSH_HOST=AutoDL SSH 主机
HEYGEM_SSH_PORT=AutoDL SSH 端口
HEYGEM_SSH_USER=root
HEYGEM_SSH_KEY_PATH=<user-home>\.ssh\oral_video_autodl
HEYGEM_REMOTE_UPLOAD_DIR=/root/autodl-tmp/oral-video-agent-inputs
```

## 7. CosyVoice 依赖

当前环境基于 Python 3.10、PyTorch 2.3.1 + CUDA 12.1，额外安装：

- `openai-whisper==20231117`
- `lightning==2.2.4`
- `gdown==5.1.0`
- `matplotlib==3.7.5`
- `x-transformers==2.11.24`
- `pyworld==0.3.4`
- CUDA 12 构建的 `onnxruntime-gpu==1.18.0`

## 8. 已验证结果

- HeyGem 官方示例：约 30.6 秒。
- 真实任务音频：约 13.76 秒。
- HeyGem 口型处理：约 60.66 秒。
- 包含声音、口型、字幕和 BGM 的端到端重试：约 69.9 秒。

## 9. 故障排查

### 本地显示服务离线

依次检查：

```powershell
Test-NetConnection 127.0.0.1 -Port 16008
Test-NetConnection 127.0.0.1 -Port 16010
```

然后在 AutoDL 检查：

```bash
curl http://127.0.0.1:6008/api/health
curl http://127.0.0.1:6010/api/health
```

### HTTP 上传被重置

确认已填写 `HEYGEM_SSH_*` 配置。未配置 SSH 时 Provider 会退回 multipart HTTP 上传，不适合大文件。

### CosyVoice 无法识别 CUDA

检查 `LD_PRELOAD` 和 CUDA 12 版 ONNX Runtime，不要安装默认 CUDA 11 构建。

### 云端磁盘持续增长

检查并清理：

```text
/root/autodl-tmp/oral-video-agent-inputs
/root/HeyGem-Linux-Python-Hack/api_uploads
/root/HeyGem-Linux-Python-Hack/result
```

正式版本应由任务完成回调自动清理。
