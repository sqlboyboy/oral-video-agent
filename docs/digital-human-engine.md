# 本地数字人引擎接入方案

## 最终路线

产品只维护一套主程序，通过数字人 Provider 和模型资源包分档：

- 高质量推荐模式：MuseTalk 真人静默视频局部换嘴。
- 低配兜底模式：SadTalker 经典头像/照片口播。
- 研究模式：Wav2Lip 仅保留适配器，不进入商业默认链路。
- 高配客户自带模式：HeyGem/Duix 或其他本地引擎通过命令行/API 接入。

## 为什么主推 MuseTalk

用户上传一条真人不说话的视频，视频里已经有真实手势、身体晃动、眼神、眨眼和背景。MuseTalk 只负责根据音频修改嘴部区域，再融合回原视频底板：

- 不生成手部动作，避免手指畸形、身体扭曲。
- 保留原视频真实像素，降低 AI 痕迹。
- 输出仍然可以是原视频的整体清晰度。
- MuseTalk 仓库使用 MIT License，并列出主要依赖许可证。

工程上默认使用 MuseTalk 自带的 jaw/face parsing 融合，不默认 GFPGAN 全脸逐帧修复。后续可以把 GFPGAN 做成可选的“面部高清修复”开关。

## 硬件分档

主程序启动后检测硬件：

- 检测到 NVIDIA CUDA 且显存达到阈值：开放“真人视频口播模式”，使用 MuseTalk。
- 没有 NVIDIA 显卡或显存不足：置灰“真人视频口播模式”，开放“经典头像口播模式”，使用 SadTalker。

默认阈值：

```env
MUSETALK_MIN_VRAM_GB=4
```

MuseTalk 官方 README 提到 RTX 3050 Ti Laptop 4GB 显存可运行 fp16，8 秒视频约 5 分钟；V100 上可达 30fps+。因此普通集显不应强行开放 MuseTalk。

## 交付形态

不做两个独立安装包。推荐：

- 主程序安装包：Flutter 客户端、FastAPI 后端、业务逻辑、Provider 适配器、激活码系统。
- 模型资源包或自动下载器：MuseTalk、SadTalker、GPT-SoVITS 等模型权重。

这样后续标准版/专业版只需要做权限控制，不需要维护两套代码。

## Provider 配置

### 1. 占位模式

```env
DIGITAL_HUMAN_PROVIDER=placeholder
```

### 2. MuseTalk 真人视频局部换嘴

```env
DIGITAL_HUMAN_PROVIDER=musetalk
MUSETALK_REPO=<workspace>\engines\MuseTalk
MUSETALK_PYTHON=python
MUSETALK_MODELS_DIR=<workspace>\engines\MuseTalk\models
MUSETALK_RESULT_DIR=<workspace>\engines\MuseTalk\results
MUSETALK_VERSION=v15
MUSETALK_BATCH_SIZE=4
MUSETALK_USE_FLOAT16=true
MUSETALK_MIN_VRAM_GB=4
DIGITAL_HUMAN_TEMPLATES_DIR=<repo>\storage\digital_humans\templates
```

模板目录里放用户自有或授权的真人静默动作视频。前端数字人下拉框会展示这些模板，生成时 MuseTalk 会保留原视频手势和身体动作，只替换嘴部区域。

MuseTalk 权重下载方式见官方仓库：

```bat
cd /d <workspace>\engines\MuseTalk
download_weights.bat
```

### 3. SadTalker 低配兜底

```env
DIGITAL_HUMAN_PROVIDER=sadtalker
SADTALKER_REPO=<workspace>\engines\SadTalker
SADTALKER_PYTHON=python
SADTALKER_CHECKPOINT_DIR=<workspace>\engines\SadTalker\checkpoints
SADTALKER_CPU=true
```

定位为“经典头像/照片口播模式”。它支持 CPU，但速度慢，效果也不是 MuseTalk 这种真人视频换嘴。

### 4. Wav2Lip 研究模式

Wav2Lip 官方开源模型限制为个人/研究/非商业用途，不能作为商业默认方案。

```env
DIGITAL_HUMAN_PROVIDER=wav2lip-template
WAV2LIP_REPO=<workspace>\engines\Wav2Lip
```

### 5. 自定义高配引擎

```env
DIGITAL_HUMAN_PROVIDER=local-command
DIGITAL_HUMAN_COMMAND=python <workspace>\engines\SomeEngine\infer.py --source {reference} --audio {audio} --out {output}
```

可用占位符：

- `{reference}`：用户选择的动作模板或真人参考视频
- `{audio}`：合成后的驱动音频
- `{script}`：口播文案文本文件
- `{output}`：数字人引擎应输出的 mp4 路径
- `{motion}`：动作模式
- `{expression}`：表情模式

## 健康检查

```text
GET http://127.0.0.1:8000/api/digital-human/health
```

返回内容包括当前 provider、MuseTalk/SadTalker/Wav2Lip 配置、缺失模型文件、模板目录、ffmpeg、GPU/显存状态。

## 合规边界

- 不能通过改名、本地部署、让用户自行下载等方式规避非商业许可证。
- 商业版默认只启用 MIT、Apache-2.0 或明确可商用授权的模型和权重。
- 用户上传的真人视频、肖像、声音样本必须由用户确认拥有合法授权。
- 声音克隆入口必须加入授权确认，不勾选则不能开始生成。
