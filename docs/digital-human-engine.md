# HeyGem 数字人引擎接入说明

更新时间：2026-06-21

## 产品边界

本项目不做图生数字人。用户必须上传一段真人静默视频，HeyGem 只根据克隆音频生成嘴部开合和口型。

```text
静默真人视频 + 克隆声音 WAV → HeyGem → 口型视频
```

人物、身体、服装、背景和镜头来自原视频，不重新生成。

## Provider 配置

```env
DIGITAL_HUMAN_PROVIDER=heygem-local
HEYGEM_BASE_URL=http://127.0.0.1:16008
HEYGEM_TIMEOUT_SECONDS=3600

HEYGEM_SSH_HOST=
HEYGEM_SSH_PORT=22
HEYGEM_SSH_USER=root
HEYGEM_SSH_KEY_PATH=
HEYGEM_REMOTE_UPLOAD_DIR=/root/autodl-tmp/oral-video-agent-inputs
```

## 当前接口

```text
POST   /api/jobs/local
GET    /api/jobs/{job_id}
GET    /api/jobs/{job_id}/result
DELETE /api/jobs/{job_id}
GET    /api/health
```

主链路先通过 SCP 上传文件，因此 `/api/jobs/local` 接收的是 AutoDL 本机路径。没有 SSH 配置时才回退到 `POST /api/jobs` multipart 上传。

## 生成流程

1. 本地将真人视频处理到与克隆音频时长一致。
2. SCP 上传处理后视频和 WAV。
3. `/api/jobs/local` 创建队列任务。
4. 每两秒查询任务状态。
5. 成功后下载口型视频。
6. 本地 FFmpeg 混入主音频、字幕和 BGM。
7. 删除 HeyGem 任务记录；云端 SCP 输入目录后续还需补充清理。

## 不做自动回退

HeyGem 不在线或生成失败时，任务明确失败，不自动使用 Wav2Lip、MuseTalk、LivePortrait 或其他引擎，避免用户得到来源不一致的结果。

## 素材要求

推荐：

- 单人正脸或轻微侧脸
- 嘴部无遮挡
- 人物不说话，嘴部自然闭合
- 1080p、25/30 FPS、H.264 MP4
- 无快速切镜
- 视频时长接近最终配音时长

避免：

- 多人画面
- 口罩、麦克风或手遮挡嘴部
- 大幅转头
- 严重模糊、过曝或低照度
- 数秒素材循环生成很长视频

## 健康检查

项目接口：

```text
GET /api/providers
GET /api/digital-human/health
```

正常状态：

```text
digital_human_provider = heygem-local
heygem_online = true
digital_human_configured = true
```

## 当前待改进

- render API 后台化
- 云端任务取消
- SCP 临时文件自动清理
- 生成百分比进度
- 30 秒和 60 秒稳定性测试
- 更完整的音画同步质量检测
