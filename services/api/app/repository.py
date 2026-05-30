import json
from pathlib import Path
from typing import Dict, List

from .models import OralVideoTask, storage_dir


class TaskRepository:
    def __init__(self) -> None:
        self._db_path = storage_dir("tasks") / "tasks.json"
        self._items: Dict[str, OralVideoTask] = {}
        self._load()

    def _load(self) -> None:
        if not self._db_path.exists():
            return
        data = json.loads(self._db_path.read_text(encoding="utf-8"))
        self._items = {item["task_id"]: OralVideoTask.model_validate(item) for item in data}

    def _save(self) -> None:
        data = [item.model_dump(mode="json") for item in self._items.values()]
        self._db_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self) -> List[OralVideoTask]:
        return list(self._items.values())

    def get(self, task_id: str) -> OralVideoTask:
        if task_id not in self._items:
            raise KeyError(task_id)
        return self._items[task_id]

    def put(self, task: OralVideoTask) -> OralVideoTask:
        self._items[task.task_id] = task
        self._save()
        return task


repo = TaskRepository()
