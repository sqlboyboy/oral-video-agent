<div align="center">

# 智能口播智能体 · Oral Video Agent

**批量完成从文案、字幕、BGM、声音克隆、封面、发布到多平台全流程的开源短视频创作工具。**
<img width="2558" height="1460" alt="image" src="https://github.com/user-attachments/assets/fc8ec478-d7e2-426d-b0cd-9e1c34e7e042" />


[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Client: Flutter](https://img.shields.io/badge/Client-Flutter-02569B?logo=flutter)](apps/client)
[![API: FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi)](services/api)
[![Platforms](https://img.shields.io/badge/Platforms-Windows%20%7C%20Android-555)](#选择分支)

[快速开始](#快速开始) · [自托管部署](docs/self-hosting.md) · [常见问题](#常见问题) · [参与贡献](CONTRIBUTING.md)

</div>

输入自己的文案，或导入有权使用的视频，完成语音转写、文案改写、声音克隆、数字人口型生成，以及字幕、背景音乐和封面合成。

**这是可自行部署的源码项目。** 仓库不附带作者的云端账号、服务器凭据或 GPU 模型权重；完整创作需要配置自己的服务。默认分支面向 Windows，安卓请使用对应分支。

## 能做什么

| 能力 | Windows PC | Android |
|---|---|---|
| 输入文案、导入视频与提取文案 | 支持 | 通过移动端入口与云端服务 |
| DeepSeek 文案改写与风格创作 | 支持 | 支持 |
| CosyVoice 声音克隆与试听 | 支持 | 云端生成 |
| HeyGem 数字人口型生成 | 支持 | 云端生成 |
| 字幕、BGM、封面和 MP4 合成 | 支持 | 云端生成，手机预览 |
| 成品管理 | 本地文件、预览和定位文件夹 | 下载、预览和保存相册 |
| 平台发布 | Playwright 网页自动化 | 当前未接通自动发布 |

发布模块包含抖音、快手、小红书、视频号的网页适配。登录、验证和页面变化可能需要人工处理；官方 API 发布适配尚未完整接通。项目不承诺内容流量或平台审核结果。

## 工作流程

```mermaid
flowchart LR
    A[视频或文案] --> B[转写与文案改写]
    B --> C[克隆声音与试听]
    C --> D[数字人口型生成]
    D --> E[字幕 / BGM / 封面合成]
    E --> F[下载与预览 MP4]
    F --> G[PC 平台发布 / 安卓保存相册]
```

各阶段可以检查中间结果。修改文案后需重新确认配音，避免成片使用旧声音。

## 选择分支

| 分支 | 内容 | 开发入口 |
|---|---|---|
| [`codex/pc`](https://github.com/sqlboyboy/oral-video-agent/tree/codex/pc) | Windows 客户端、本地 API、发布模块和配套云端服务 | Flutter Windows |
| [`codex/android-apk-no-activation`](https://github.com/sqlboyboy/oral-video-agent/tree/codex/android-apk-no-activation) | 安卓客户端、签名 APK 构建和配套云端服务 | Flutter Android |

请从所选分支构建客户端和配套服务。共享修复按需同步，详见 [分支管理](docs/branch-management.md)。

## 快速开始

### 1. 准备环境

- **Python 3.11+** 与 [uv](https://docs.astral.sh/uv/getting-started/installation/)。
- **Flutter SDK** 与对应平台工具链：Windows 需要 Visual Studio 的 C++ 桌面开发组件；Android 需要 Android SDK。运行 `flutter doctor` 检查。
- **FFmpeg**：将 `ffmpeg`、`ffprobe` 放入 PATH，用于完整音视频处理。
- 浏览器相关能力需要安装 Playwright Chromium。

### 2. 获取源码

Windows：

```bash
git clone --branch codex/pc https://github.com/sqlboyboy/oral-video-agent.git
cd oral-video-agent
```

安卓：

```bash
git clone --branch codex/android-apk-no-activation https://github.com/sqlboyboy/oral-video-agent.git oral-video-agent-android
cd oral-video-agent-android
```

### 3. 验证本地 API

以下命令使用 PowerShell，在仓库根目录执行。占位 Provider 用于检查接口，不会生成真实克隆声音或数字人。

```powershell
if (-not (Test-Path services/api/.env)) {
    Copy-Item .env.example services/api/.env
}
cd services/api
uv sync
uv run playwright install chromium

$env:ASR_PROVIDER = "placeholder"
$env:REWRITE_PROVIDER = "placeholder"
$env:VOICE_PROVIDER = "placeholder"
$env:DIGITAL_HUMAN_PROVIDER = "placeholder"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 [API 文档](http://127.0.0.1:8000/docs)，调用 `/api/health` 检查服务。切换真实 Provider 时，在新终端中运行，或移除上面的临时环境变量，再配置 `.env`。

### 4. 启动客户端

先按照 [自托管部署](docs/self-hosting.md) 配置云端 API、账号和模型服务。将以下 `https://api.example.com` **替换为自己的 HTTPS API 地址**。

另开终端，在所选仓库根目录执行 `cd apps/client` 和 `flutter pub get`。

Windows：

```powershell
flutter run -d windows --dart-define=API_BASE=http://127.0.0.1:8000 --dart-define=CLOUD_API_BASE=https://api.example.com
```

Android：

```powershell
flutter devices
$deviceId = "替换为 flutter devices 列出的安卓设备 ID"
flutter run -d $deviceId --dart-define=CLOUD_API_BASE=https://api.example.com
```

PC 端包含软件激活和云端账号流程，由自托管后台管理；安卓无需手动输入激活码，但仍需账号及对应使用权限。仅启动本地 API 不会自动创建这些权限。

## 接入真实生成能力

| 能力 | 实现 | 主要配置 |
|---|---|---|
| 语音识别 | faster-whisper | `ASR_PROVIDER=faster-whisper`、`WHISPER_MODEL` |
| 文案改写 | DeepSeek API | `REWRITE_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` |
| 声音克隆 | CosyVoice API | `VOICE_PROVIDER=remote-cosyvoice`、`VOICE_BASE_URL` |
| 数字人 | HeyGem API | `DIGITAL_HUMAN_PROVIDER=heygem-local`、`HEYGEM_BASE_URL` |
| 云端业务 | FastAPI | `CLOUD_API_BASE`（客户端）、`CLOUD_PUBLIC_BASE_URL`（服务端） |
| 云端存储 | 本地磁盘或腾讯云 COS | `OBJECT_STORAGE_BACKEND=local` 或 `cos` |

本地 API 配置模板：[.env.example](.env.example)。云端配置模板：[services/cloud/.env.example](services/cloud/.env.example)。实际密钥只放本地 `.env` 或部署平台的秘密变量中。

## 系统结构

```text
Flutter Windows / Android
    ├─ PC 本地 FastAPI：素材、媒体处理、浏览器自动化
    └─ 云端 FastAPI：账号、授权、任务与使用额度
          ├─ PostgreSQL：业务记录（开发时可用 SQLite）
          ├─ Redis：限流与辅助队列状态
          ├─ 本地存储 / 腾讯云 COS：素材与成品
          └─ AutoDL Worker：领取任务、模型推理、上传结果
```

生成能力：**faster-whisper + DeepSeek API + CosyVoice + HeyGem + FFmpeg**。使用本地对象存储时，文件经云端文件接口传输；配置 COS 后使用签名地址上传和下载。

```text
apps/client/              Flutter 客户端
services/api/             本地 API 与媒体生成模块
services/cloud/app/       云端业务 API
services/cloud/worker/    AutoDL Worker 与生成入口
services/cloud/deploy/    Docker Compose 与反向代理配置
scripts/                  构建和部署辅助脚本
docs/                     使用与架构文档
storage/                  本地运行数据，不提交 Git
```

## 构建与测试

在 `apps/client` 中执行：

```powershell
flutter analyze lib test
flutter test
```

在 `services/api` 和 `services/cloud` 中分别执行：

```powershell
uv run pytest tests/ -q
```

本地 API 的实验性口型诊断测试需要额外的 PyTorch 环境，详见 [贡献指南](CONTRIBUTING.md)。

- **Windows 安装包**：先运行 `scripts/build_windows_api_release.ps1`，再运行 `scripts/package_windows_client_release.ps1 -CloudApiBase https://api.example.com`。Flutter 需位于 PATH，也可传入 `-FlutterExe`。
- **安卓 APK**：在安卓分支运行 `scripts/build_android_release.ps1 -CloudApiBase https://api.example.com`；正式签名配置见 [安卓发布文档](https://github.com/sqlboyboy/oral-video-agent/blob/codex/android-apk-no-activation/docs/android-release-and-updates.md)。

以上构建地址同样需要替换。仓库不包含签名私钥，也不代表已经提供可直接使用的公共云服务。

## 常见问题

**为什么打开软件后仍要配置账号？**

源码、模型推理服务和账号权限是不同组件。自托管时需要启动云端控制中心，通过后台管理账号与权限。

**没有 GPU 可以做什么？**

可以开发界面、验证占位 API、测试任务和调用已配置的文案 API。完整声音克隆与数字人生成需要连接相应推理服务。

**为什么任务一直排队？**

检查 Worker 是否运行、Worker Token 是否与控制中心一致，以及 Worker 能否访问 API 和素材地址。

**安卓能自动发布到抖音吗？**

当前安卓支持下载和保存相册，平台自动发布位于 PC 的浏览器自动化模块。

**发布按钮已经点击，为什么还显示需要处理？**

平台可能要求验证码、重新登录或补全内容。系统会等待实际页面反馈，不能把点击按钮视为审核通过。

## 文档与贡献

- [自托管部署与账号配置](docs/self-hosting.md)
- [云端管理后台](docs/cloud-admin-web.md)
- [GPU 服务与连接](docs/autodl-deployment-guide.md)
- [数字人引擎说明](docs/digital-human-engine.md)
- [参与贡献](CONTRIBUTING.md) · [安全与隐私](SECURITY.md)

欢迎提交可复现的 Issue 和范围明确的 PR。提交日志、截图或示例素材前，请移除账号、密钥、Cookie 和个人信息。

## 许可证与致谢

项目原创代码使用 [MIT License](LICENSE)。第三方依赖、模型权重、服务和素材仍遵循各自许可；本项目的 MIT 许可不会改变 HeyGem 等上游项目的授权范围。

感谢 [Flutter](https://github.com/flutter/flutter)、[FastAPI](https://github.com/fastapi/fastapi)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[CosyVoice](https://github.com/FunAudioLLM/CosyVoice)、FFmpeg 和 Playwright 等项目。

请仅使用有权处理的视频、音乐、形象与声音，声音克隆需获得相关权利人的授权。
