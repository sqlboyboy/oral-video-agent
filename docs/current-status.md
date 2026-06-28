# 项目当前进度

更新时间：2026-06-21

## 已完成

- Flutter Windows 客户端和 FastAPI 本地后端已联通。
- 抖音链接解析、本地视频上传和 faster-whisper ASR 可用。
- DeepSeek API 已接入，模型配置为 `deepseek-v4-flash`。
- 仿写文案会去除中英文标点，仅保留文本和换行。
- CosyVoice-300M-25Hz 已部署到 AutoDL，GPU 健康检查正常。
- CosyVoice 长文本会收集并拼接所有输出音频块。
- HeyGem `heygem_server v1.1` 已部署并完成 GPU 推理验证。
- HeyGem 使用静默真人视频和克隆 WAV 生成口型。
- HeyGem 大文件改用 SCP 上传，再调用 `/api/jobs/local` 入队。
- 本地通过 `/api/jobs/{id}` 轮询并下载最终结果。
- 字幕、BGM、标题、封面和最终 MP4 本地合成可用。
- 真实任务 `8f3aa3cc-7cff-41ff-850e-453d93e248ac` 已成功完成。
- 后端完整测试通过 `126` 项。

## 已解决的关键问题

### CUDA 驱动不兼容

AutoDL 宿主驱动为 580 系列，而镜像默认加载旧版 `libcuda.so.1`。HeyGem 和 CosyVoice 启动时通过 `LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libcuda.so.580.76.05` 使用正确驱动。

### CosyVoice 安装缺失依赖

补装了 `openai-whisper`、`lightning`、`gdown`、`matplotlib`、`x-transformers`、`pyworld`，并使用 CUDA 12 版本的 `onnxruntime-gpu 1.18.0`。

### 文字与声音不对应

原实现只读取 `inference_cross_lingual()` 的第一个输出块。现在遍历并拼接所有 `tts_speech`，避免长文本尾部丢失。

### HeyGem 上传约 120 秒断线

HTTP multipart 上传通过 AutoDL 网关时会被重置。现在改为：

```text
本地 FastAPI
  → SCP 上传 WAV/MP4
  → POST /api/jobs/local
  → GET /api/jobs/{id}
  → GET /api/jobs/{id}/result
```

## 当前运行状态

根据用户要求，以下服务已全部停止：

- 本地 FastAPI `8000`
- 本地 Flutter Windows 客户端
- SSH 隧道 `16008`、`16010`
- AutoDL HeyGem `6008`
- AutoDL CosyVoice `6010`

重新测试前需要按 README 的启动顺序恢复。

## 下一阶段优先级

P0：

1. 将同步 render 接口改为后台任务。
2. 修复前端窄窗口 `Row` 溢出。
3. 增加云端临时上传目录自动清理。
4. 增加 HeyGem 云端任务取消。

P1：

1. 使用 ASR/TTS 时间戳生成精确字幕。
2. 增加生成阶段耗时、队列和百分比进度。
3. 为 SCP 上传增加断点续传或文件哈希复用。
4. 增加 30 秒、60 秒长视频稳定性测试。

P2：

1. 将本地 JSON 任务存储升级为 SQLite。
2. 增加失败任务自动恢复和幂等机制。
3. 增加 AutoDL 服务守护和一键启停脚本。
