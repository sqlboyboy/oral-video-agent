from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.models import OralVideoTask, project_root
from app.mouth_quality import build_mouth_quality_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize internal mouth quality signals across rendered tasks.")
    parser.add_argument(
        "--tasks",
        default=str(project_root() / "storage" / "tasks" / "tasks.json"),
        help="Path to storage/tasks/tasks.json.",
    )
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--quality-only", action="store_true", help="Only include tasks with mouth_quality signals in items.")
    return parser.parse_args()


def load_tasks(path: Path) -> list[OralVideoTask]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("tasks JSON must contain a list.")
    return [OralVideoTask.model_validate(item) for item in data if isinstance(item, dict)]


def main() -> None:
    args = parse_args()
    report = build_mouth_quality_report(load_tasks(Path(args.tasks)), include_missing=not args.quality_only)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
