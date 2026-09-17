# 智能口播智能体
<img width="2558" height="1460" alt="image" src="private-screenshot-removed" />

这个智能体主要功能是批量制作抖音的爆款视频，只需要用户做3件事，就能生成爆款视频：1、复制抖音爆款短视频链接（或者复制抖音短视频博主主页链接） 2、上传一段自己的录音 3、上传一段不说话的口播视频。智能体会生成 口播文案、克隆声音、封面、BGM、字幕、标题文案等。

技术架构：Flutter 客户端 + FastAPI 后端 + PostgreSQL 数据库 + Redis 缓存 + 腾讯云 COS 存储 + AutoDL GPU 服务 + DeepSeek API + FFmpeg 视频处理 + Playwright 自动发布
基本功能
1、提取文案：用户通过复制某音爆款链接，AI会去解析，提取短视频文案
2、改写文案：对提取到的文案进行改写，以免雷同，规避平台检测
3、声音克隆：用户提交个人声音，智能体会克隆用户声音，然后按照改写的文案一键生成用户声音
4、数字人形象上传：用户上传不开口，不说话的录制数字人形象的视频
5、成品包装：标题、封面、字幕、BGM、克隆配音、数字人形象一键生成，然后合成成品的口播视频。
6、一键发布到短视频平台：支持某音、某手、某书、蝴蝶号，用户一键发布生成带标题和文案的真人口播视频。

## 维护分支

仓库仅维护 Windows PC 和 Android 两个产品分支：

| 分支 | 用途 |
|---|---|
| `codex/pc` | 默认分支；Windows 桌面客户端、本地 API 和配套云端服务 |
| `codex/android-apk-no-activation` | Android 客户端、签名 APK 构建和配套云端服务 |

构建前请确认分支；安卓构建文件位于安卓分支。维护与验证方式见 [分支管理说明](docs/branch-management.md)。下方早期部署记录保留供参考，实时运行状态需另行确认。

一个面向 Windows 的短视频口播生成工具。用户可以粘贴抖音分享链接或上传视频，系统完成文案提取、DeepSeek 仿写、声音克隆、HeyGem 数字人口型、字幕、背景音乐和最终 MP4 合成。

## 当前状态

截至 2026-06-21，核心端到端链路已跑通：

```text
抖音链接/本地视频
  → faster-whisper 文案提取
  → DeepSeek API 文案仿写
  → AutoDL CosyVoice 声音克隆
  → AutoDL HeyGem 口型生成
  → Windows FFmpeg 添加字幕和 BGM
  → 最终 MP4
```

已验证能力：

- DeepSeek 远程 API 仿写，不加载本地大语言模型。
- 仿写结果自动去除中英文标点，保留换行。
- CosyVoice-300M-25Hz 部署在 AutoDL RTX 4090D。
- 修复 CosyVoice 长文本只读取首个音频块导致的声音截断。
- HeyGem 使用用户上传的静默真人视频生成开口、闭口和口型。
- HeyGem 和 CosyVoice 均通过 SSH 隧道访问，不暴露公网端口。
- 大文件通过 SCP 上传到 AutoDL，再调用 HeyGem 本地路径队列接口，避免约 120 秒的网关连接重置。
- 约 14 秒、1080×1920 的真实任务端到端生成成功，最终生成阶段约 70 秒。
- 后端完整测试通过 `126` 项。

当前所有本地和 AutoDL 服务均已停止。下次使用时按“启动顺序”重新启动。

## 项目结构

```text
apps/client/        Flutter Windows/Android 客户端
services/api/       FastAPI 本地后端
services/api/tools/ CosyVoice 云端 API 等辅助程序
scripts/            AutoDL 服务及 SSH 隧道启动脚本
storage/            素材、任务、音频、字幕和输出
docs/               架构、部署和产品说明
```

## 技术架构

本地 Windows：

- Flutter 客户端
- FastAPI 业务 API
- faster-whisper ASR
- FFmpeg 视频预处理、字幕、BGM 和最终封装
- 任务与素材文件存储

AutoDL RTX 4090D：

- HeyGem API：`127.0.0.1:6008`
- CosyVoice API：`127.0.0.1:6010`
- 模型和推理环境保存在 `/root/autodl-tmp`

本地隧道：

- `127.0.0.1:16008 → AutoDL 127.0.0.1:6008`（HeyGem）
- `127.0.0.1:16010 → AutoDL 127.0.0.1:6010`（CosyVoice）

## 环境配置

复制 `.env.example` 为 `services/api/.env`，填写自己的 DeepSeek API Key 和 AutoDL SSH 信息。

```env
REWRITE_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash

ASR_PROVIDER=faster-whisper
WHISPER_MODEL=small

VOICE_PROVIDER=remote-cosyvoice
VOICE_BASE_URL=http://127.0.0.1:16010
VOICE_TIMEOUT_SECONDS=1800

DIGITAL_HUMAN_PROVIDER=heygem-local
HEYGEM_BASE_URL=http://127.0.0.1:16008
HEYGEM_TIMEOUT_SECONDS=3600

HEYGEM_SSH_HOST=
HEYGEM_SSH_PORT=22
HEYGEM_SSH_USER=root
HEYGEM_SSH_KEY_PATH=
HEYGEM_REMOTE_UPLOAD_DIR=/root/autodl-tmp/oral-video-agent-inputs
```

不要把 API Key、SSH 密码或私钥提交到 Git。

## 启动顺序

### 1. 启动 AutoDL HeyGem

```bash
cd /root/HeyGem-Linux-Python-Hack
./start_api.sh
```

健康检查：

```bash
curl http://127.0.0.1:6008/api/health
```

### 2. 启动 AutoDL CosyVoice

```bash
/root/autodl-tmp/cosyvoice/start_voice_api.sh
```

健康检查：

```bash
curl http://127.0.0.1:6010/api/health
```

### 3. 启动本地双隧道

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_autodl_heygem_tunnel.ps1
```

该脚本同时检查 HeyGem 和 CosyVoice GPU 状态。

### 4. 启动 FastAPI

```powershell
cd services/api
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口文档：<http://127.0.0.1:8000/docs>

### 5. 启动 Flutter Windows 客户端

```powershell
cd apps/client
<workspace>\flutter\bin\flutter.bat pub get
<workspace>\flutter\bin\flutter.bat run -d windows --dart-define=API_BASE=http://127.0.0.1:8000
```

## 测试

```powershell
cd services/api
uv run pytest tests/
```

```powershell
cd apps/client
<workspace>\flutter\bin\flutter.bat analyze lib/main.dart
```

## 当前限制

- `/api/tasks/{id}/render` 仍是同步长请求，应改为后台任务。
- 前端只展示阶段状态，还没有 HeyGem 百分比进度。
- 字幕时间主要按音频总时长分配，尚未使用逐字时间戳。
- 停止本地任务不会可靠取消已经提交到 HeyGem 的云端任务。
- SCP 上传成功后的云端临时输入目录尚未自动清理。
- Flutter 在窄窗口下有一个 `Row` 横向溢出警告，需要后续修复。
- HeyGem 社区许可不是标准 MIT/Apache 许可，商用前必须单独确认授权。

## 相关文档

- [当前进度](docs/current-status.md)
- [AutoDL 部署指南](docs/autodl-deployment-guide.md)
- [数字人技术架构](docs/digital-human-architecture-v2.md)
- [HeyGem 接入说明](docs/digital-human-engine.md)

## 合规要求

- 只处理用户有权使用的视频、声音和音乐。
- 声音克隆必须获得本人或权利人授权。
- 不鼓励逐字复制他人文案，仅进行结构和表达风格改写。
- 商业发布前确认 DeepSeek、CosyVoice、HeyGem 及模型权重的授权范围。
