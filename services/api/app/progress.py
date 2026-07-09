from .models import OralVideoTask, ProgressStep


PROGRESS_LABELS = {
    "extract": "1. 对标文案提取",
    "resolve_link": "解析分享链接",
    "download_video": "下载源视频",
    "transcribe": "识别视频文案",
    "rewrite": "2. 文案仿写",
    "voice": "3. 声音克隆/合成",
    "subtitle": "4. 添加字幕/画中画",
    "bgm": "5. 添加背景音乐",
    "digital_human": "6. 数字人口播与成片合成",
    "title": "7. 生成标题",
    "cover": "8. 生成封面",
    "publish": "9. 多平台发布",
}


def mark_progress(task: OralVideoTask, key: str, status: str) -> None:
    for step in task.progress_steps:
        if step.key == key:
            step.status = status
            return
    task.progress_steps.append(
        ProgressStep(key=key, label=PROGRESS_LABELS.get(key, key), status=status)
    )


def complete_progress(task: OralVideoTask, *keys: str) -> None:
    for key in keys:
        mark_progress(task, key, "completed")


def start_progress(task: OralVideoTask, key: str) -> None:
    mark_progress(task, key, "running")


def fail_progress(task: OralVideoTask, key: str) -> None:
    mark_progress(task, key, "failed")
