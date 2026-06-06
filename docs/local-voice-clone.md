# 本地声音克隆方案

项目默认选择轻量路线：`CosyVoice-300M-25Hz`。

选择原因：

- 中文效果中等偏上，适合短视频口播。
- 300M 级别模型，比 0.5B/更大模型更轻。
- 支持 zero-shot / cross-lingual 克隆，参考音色视频不需要逐字稿。
- 普通 RTX 3050/3060/4060 级别独显或较新的 CPU 都能跑；30 秒口播通常可控制在 15 分钟内，具体取决于显卡和首次加载耗时。

## 推荐目录

```powershell
<workspace>\engines\CosyVoice
<workspace>\models\CosyVoice-300M-25Hz
```

如果你放在别的位置，启动 API 前设置：

```powershell
$env:COSYVOICE_REPO="D:\your\CosyVoice"
$env:COSYVOICE_MODEL="D:\your\CosyVoice-300M-25Hz"
```

## 后端配置

`services/api/.env` 已配置：

```env
VOICE_PROVIDER=local-command
VOICE_CLONE_COMMAND=uv run --python <workspace>\engines\CosyVoice\.venv\Scripts\python.exe <repo>\services\api\tools\cosyvoice_clone.py --reference {reference} --script {script} --output {output}
```

## uv 安装

可以直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File <repo>\scripts\setup_cosyvoice_uv.ps1
```

这个脚本会：

- 下载/更新 `<workspace>\engines\CosyVoice`
- 用 `uv` 创建 Python 3.10 虚拟环境
- 用 `uv pip` 安装 CosyVoice 依赖
- 打印 PyTorch 和 CUDA 状态

## 使用方式

1. 在前端“参考音色”点击“上传”。
2. 选择 10-30 秒参考音色视频或音频，建议清晰人声、少背景音乐、少混响。
3. 点击“克隆声音”或“生成视频”。
4. 后端会调用 `services/api/tools/cosyvoice_clone.py` 输出本地 wav。

## 说明

当前脚本会从 `.mp4/.mov/.mkv/.webm` 里自动抽音频，不依赖系统 `ffmpeg` 命令。
