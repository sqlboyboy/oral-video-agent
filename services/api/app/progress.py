from .models import OralVideoTask


def mark_progress(task: OralVideoTask, key: str, status: str) -> None:
    for step in task.progress_steps:
        if step.key == key:
            step.status = status
            return
    raise ValueError(f"Unknown progress step: {key}")


def complete_progress(task: OralVideoTask, *keys: str) -> None:
    for key in keys:
        mark_progress(task, key, "completed")


def start_progress(task: OralVideoTask, key: str) -> None:
    mark_progress(task, key, "running")


def fail_progress(task: OralVideoTask, key: str) -> None:
    mark_progress(task, key, "failed")
