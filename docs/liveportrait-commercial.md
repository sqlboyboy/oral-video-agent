# LivePortrait 商业版接入方案

## 目标

把 LivePortrait 作为“高清模式”的人脸动画引擎接入。产品默认不配置 InsightFace / buffalo / antelope 这类模型。

## 合规边界

默认：

- LivePortrait 主体代码和权重按其 MIT 条款使用。
- 人脸检测/对齐使用 MediaPipe、OpenCV YuNet 或 dlib。
- 商业版默认不打包、不下载、不引导用户下载 InsightFace 模型。

用户自定义：

- 软件允许配置自定义检测器或自定义适配命令。
- 用户自行配置第三方模型时，需要自行确认其商业授权。
- 后端不对用户自定义检测器做强拦截。

## 当前实现

后端新增 `liveportrait-commercial` 数字人引擎，前端显示为“高清模式”：

- `DIGITAL_HUMAN_PROVIDER=liveportrait-commercial`
- `LIVEPORTRAIT_REPO=<workspace>/engines\LivePortrait`
- `LIVEPORTRAIT_PYTHON=python`
- `LIVEPORTRAIT_DETECTOR=mediapipe`
- 可选 `LIVEPORTRAIT_COMMAND` 挂接完成版商业适配器。

健康检查接口 `/api/digital-human/health` 会返回：

- LivePortrait 仓库是否存在
- 是否配置自定义命令
- YuNet 模型路径是否存在

## 产品提醒

LivePortrait 不是音频驱动口型模型。它适合做人脸表情、眨眼、头动迁移。若要做“文本/音频驱动的真人口播”，还需要额外的音频口型模块，或者改成 MuseTalk / 合规局部换嘴路线。

当前适配脚本 `services/api/tools/liveportrait_commercial.py` 是高清模式入口占位：默认不配置 InsightFace，后续可实现 MediaPipe/YuNet/dlib 裁剪对齐逻辑，或通过 `LIVEPORTRAIT_COMMAND` 挂接自定义适配器。
