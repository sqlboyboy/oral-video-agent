# 智能口播智能体

一个全新的 Windows + Android 智能口播软件项目。用户粘贴抖音链接或上传本地视频后，系统解析口播内容，一键仿写文案，选择/上传角色声音和 BGM，自动生成配音、字幕并合成视频。

## 当前状态

这是 MVP 骨架，已经包含：

- FastAPI 后端任务 API
- 视频链接/上传任务入口
- ASR、文案仿写、TTS、字幕、渲染的可替换 provider/pipeline 结构
- Flutter 客户端源码骨架，面向 Windows + Android
- 本地存储目录结构

当前 AI/视频能力是占位实现，后续把 provider 替换成真实能力：Whisper/faster-whisper、Claude/OpenAI/国产模型、CosyVoice/其他 TTS、FFmpeg。

Python 后端依赖由 `services/api/pyproject.toml` 和 `uv.lock` 管理，不再优先使用手动 `pip install` 流程。

## 目录结构

```text
apps/client          Flutter 客户端源码
services/api         FastAPI 后端
services/worker      后台任务 worker 预留目录
storage              本地素材和成品存储
docs                 产品和技术文档
```

## 启动后端

后端使用 `uv` 管理依赖和虚拟环境。

```bash
cd <repo>/services/api
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

常用 provider 配置：

```bash
# 文案仿写：placeholder 或 anthropic
REWRITE_PROVIDER=anthropic
ANTHROPIC_API_KEY=你的密钥
ANTHROPIC_MODEL=claude-opus-4-6

# 语音识别：placeholder 或 faster-whisper
ASR_PROVIDER=faster-whisper
WHISPER_MODEL=small

# 配音合成：placeholder 或后续接入的 TTS provider 名称，例如 cosyvoice
VOICE_PROVIDER=placeholder
TTS_API_KEY=

# 数字人：Wav2Lip ONNX + 局部嘴部融合
DIGITAL_HUMAN_PROVIDER=wav2lip-onnx
WAV2LIP_ONNX_MODEL=storage/models/wav2lip/wav2lip.onnx
WAV2LIP_BLEND_ENABLED=true
WAV2LIP_BLEND_PRESET=balanced
WAV2LIP_APERTURE_ATLAS_SOURCE=
WAV2LIP_APERTURE_ATLAS_STRENGTH=0.5
WAV2LIP_APERTURE_ENERGY_THRESHOLD=0.24
WAV2LIP_APERTURE_MIN_RATIO=0.07
WAV2LIP_APERTURE_MAX_RATIO=0.36
WAV2LIP_APERTURE_ATTACK=1.0
WAV2LIP_APERTURE_RELEASE=1.0
WAV2LIP_QUALITY_DIAGNOSTICS_ENABLED=true
WAV2LIP_QUALITY_DIAGNOSTICS_SAMPLE_STRIDE=2
WAV2LIP_QUALITY_DIAGNOSTICS_MAX_FRAMES=240
```

不设置时默认使用本地 placeholder，便于离线开发和测试。

### 数字人口型自然度

`wav2lip-onnx` 会先生成原始对口型视频，再通过 `tools/blend_wav2lip_result.py` 做局部嘴部融合：只把 Wav2Lip 的嘴型区域融合回原视频，尽量保留脸颊、眼睛、头发和背景不变，接近“只改嘴巴”的商业软件观感。

`WAV2LIP_BLEND_PRESET` 可选：

- `balanced`：默认，优先保留开口幅度，适合当前最佳实验分支。
- `natural`：额外柔化嘴部边缘，适合更重视边界自然的素材。
- `detail`：增加局部纹理恢复，适合高清素材调参验证。
- `soft-cavity` / `upper-cavity`：实验性减少口腔黑洞感，当前不建议默认使用。

默认会自动复用当前选择的数字人参考视频建立同身份闭口/微开口基准，稳定口型开合；如需固定一条内部基准视频，可设置 `WAV2LIP_APERTURE_ATLAS_SOURCE`。当前默认强度 `0.5`、闭口阈值 `0.24`、开合范围 `0.07/0.36` 是已验证的自动补偿起点。`ATTACK/RELEASE` 控制张口响应和闭口回落速度；默认 `1.0/1.0` 不额外平滑，若长视频出现抖动再降低。

渲染后默认会写内部 QA 侧车文件：`*.mouth_state.json` 记录音频口型状态，`*.mouth_diagnosis.json` 对齐视频、音频和状态判断闭口漂移、元音开合与抖动。诊断失败不会阻断成片输出，也不会变成让用户补素材的提示。

任务完成后会把这些内部质量信号汇总到 `mouth_quality` 字段，包括诊断路径、总体 verdict、状态对齐 verdict、低能量可见开缝、强能量开口和元音释放指标。这个字段用于工程批量 QA 和后续自动调参，不作为用户侧素材要求。

批量巡检入口：

- API：`GET /api/tasks/mouth-quality?include_missing=false`
- CLI：`uv run python tools/summarize_mouth_quality.py --quality-only --output ../../storage/experiments/lip_sync_0601/mouth_quality_task_report.json`

评分是内部排序信号，主要惩罚低能量可见开缝、强能量开口 muted、元音释放 muted 和诊断 verdict 异常，用于比较算法分支和样例回归。

报告里的 `issues` / `hint_counts` 是内部自动诊断标签，例如 `closed_state_visible_gap -> strengthen_closed_state_control`、`expected_vowel_muted -> increase_vowel_release_floor`。这些标签用于后续自动调参和回归定位，不会转成用户侧“补素材”提示。

打开接口文档：

```text
http://127.0.0.1:8000/docs
```

## 启动客户端

需要先安装 Flutter SDK，并启用 Windows/Android 支持。

```bash
cd <repo>/apps/client
flutter pub get
flutter run -d windows --dart-define=API_BASE=http://127.0.0.1:8000
```

Android：

```bash
flutter run -d android --dart-define=API_BASE=http://10.0.2.2:8000
```

## 上传限制

- 源视频：`.mp4`, `.mov`, `.mkv`, `.webm`，最大 500MB
- 声音参考：`.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`，最大 50MB
- BGM：`.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`，最大 100MB

## MVP API

- `GET /api/health` 健康检查
- `GET /api/providers` 当前 ASR/文案/TTS provider 配置状态
- `GET /api/voices` 内置声音和自定义声音列表
- `POST /api/voices/upload` 上传授权声音参考
- `GET /api/bgm` 内置 BGM 和自定义 BGM 列表
- `POST /api/bgm/upload` 上传自定义 BGM
- `GET /api/assets/{asset_id}/download` 下载素材文件
- `DELETE /api/assets/{asset_id}` 删除素材文件
- `POST /api/subtitles/preview` 预览字幕分行
- `GET /api/tasks` 任务列表
- `POST /api/tasks` 用链接创建任务
- `POST /api/tasks/upload` 上传本地视频创建任务
- `GET /api/tasks/{task_id}` 查询任务
- `DELETE /api/tasks/{task_id}` 删除任务并清理本地文件
- `POST /api/tasks/{task_id}/rewrite` 仿写文案
- `POST /api/tasks/{task_id}/render` 合成视频
- `GET /api/tasks/{task_id}/output` 查询成品 readiness/路径/大小
- `GET /api/tasks/{task_id}/download` 下载成品

## 合规说明

- 用户应只处理自己有权使用的视频、声音和音乐素材。
- 自定义声音上传必须获得本人或权利人授权。
- 默认做口播结构和风格改写，不鼓励逐字复制他人文案。
- 第三方平台链接下载模块应遵守平台规则；下载失败时使用本地上传兜底。
