from .models import OralVideoTask, ProgressStep


PROGRESS_LABELS = {
    "extract": "1. 对标文案提取",
    "rewrite": "2. 文案仿写",
    "voice": "3. 声音克隆/合成",
    "digital_human": "4. 数字人口播",
    "subtitle": "5. 添加字幕",
    "bgm": "6. 添加背景音乐",
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
