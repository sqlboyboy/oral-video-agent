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

## MVP API

- `GET /api/health` 健康检查
- `GET /api/voices` 内置声音
- `GET /api/bgm` 内置 BGM
- `GET /api/tasks` 任务列表
- `POST /api/tasks` 用链接创建任务
- `POST /api/tasks/upload` 上传本地视频创建任务
- `GET /api/tasks/{task_id}` 查询任务
- `POST /api/tasks/{task_id}/rewrite` 仿写文案
- `POST /api/tasks/{task_id}/render` 合成视频
- `GET /api/tasks/{task_id}/download` 下载成品

## 合规说明

- 用户应只处理自己有权使用的视频、声音和音乐素材。
- 自定义声音上传必须获得本人或权利人授权。
- 默认做口播结构和风格改写，不鼓励逐字复制他人文案。
- 第三方平台链接下载模块应遵守平台规则；下载失败时使用本地上传兜底。
