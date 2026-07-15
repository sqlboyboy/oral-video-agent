from __future__ import annotations

import json
import sys
from pathlib import Path

from worker.autodl_worker import AutoDlWorker


class DummyApi:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    def post(self, path: str, payload: dict) -> dict:
        self.posts.append((path, payload))
        return {}


def _worker(monkeypatch, tmp_path: Path) -> AutoDlWorker:
    monkeypatch.setenv("CLOUD_API_BASE", "https://cloud.example.com")
    monkeypatch.setenv("WORKER_TOKEN", "worker-token")
    monkeypatch.setenv("WORKER_WORK_DIR", str(tmp_path / "worker"))
    monkeypatch.setenv("SIMULATE_RENDER_SECONDS", "1")
    worker = AutoDlWorker()
    worker.api = DummyApi()
    return worker


def test_render_command_downloads_inputs_and_uploads_output(monkeypatch, tmp_path):
    script = tmp_path / "render.py"
    script.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "job = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))",
                "assert job['input_assets'][0]['local_path']",
                "pathlib.Path(job['local_output_path']).write_bytes(b'video-output')",
            ]
        ),
        encoding="utf-8",
    )
    worker = _worker(monkeypatch, tmp_path)
    worker.render_command = f'"{sys.executable}" "{script}" "{{job_json}}"'
    downloaded: list[tuple[str, Path]] = []
    uploaded: list[tuple[str, Path, dict[str, str], str]] = []

    def fake_download_file(*, url: str, dest: Path, headers: dict[str, str]) -> None:
        downloaded.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"input-video")

    def fake_upload_file(
        *,
        url: str,
        source: Path,
        headers: dict[str, str],
        method: str = "PUT",
    ) -> None:
        uploaded.append((url, source, headers, method))
        assert source.read_bytes() == b"video-output"

    monkeypatch.setattr(worker, "download_file", fake_download_file)
    monkeypatch.setattr(worker, "upload_file", fake_upload_file)
    job = {
        "job_id": "job-1",
        "payload": {
            "output_cos_key": "outputs/user/job-1/result.mp4",
            "output_upload": {
                "method": "PUT",
                "url": "https://cos.example.com/output",
                "headers": {"Content-Type": "video/mp4"},
            },
        },
        "input_assets": [
            {
                "asset_id": "asset-1",
                "kind": "source_video",
                "file_name": "source.mp4",
                "download": {
                    "method": "GET",
                    "url": "https://cos.example.com/input",
                    "headers": {},
                },
            }
        ],
        "output_upload": {
            "method": "PUT",
            "url": "https://cos.example.com/output",
            "headers": {"Content-Type": "video/mp4"},
        },
    }

    result = worker.run_render(job)

    assert result["mode"] == "render_command"
    assert result["output_cos_key"] == "outputs/user/job-1/result.mp4"
    assert result["output_file_name"] == "result.mp4"
    assert result["output_content_type"] == "video/mp4"
    assert result["output_file_size_bytes"] == len(b"video-output")
    assert downloaded[0][0] == "https://cos.example.com/input"
    assert downloaded[0][1].name == "00-source.mp4"
    assert uploaded[0][0] == "https://cos.example.com/output"
    assert uploaded[0][3] == "PUT"
    progress_messages = [payload["message"] for path, payload in worker.api.posts if path.endswith("/progress")]
    assert "执行本地渲染脚本" in progress_messages
    assert "上传成品到云端临时存储" in progress_messages


def test_render_command_requires_output_file(monkeypatch, tmp_path):
    script = tmp_path / "render_empty.py"
    script.write_text("import sys\n", encoding="utf-8")
    worker = _worker(monkeypatch, tmp_path)
    worker.render_command = f'"{sys.executable}" "{script}" "{{job_json}}"'
    monkeypatch.setattr(
        worker,
        "download_file",
        lambda *, url, dest, headers: dest.write_bytes(b"input-video"),
    )
    job = {
        "job_id": "job-2",
        "payload": {
            "output_upload": {
                "method": "PUT",
                "url": "https://cos.example.com/output",
                "headers": {"Content-Type": "video/mp4"},
            },
        },
        "input_assets": [
            {
                "asset_id": "asset-1",
                "file_name": "source.mp4",
                "download": {"url": "https://cos.example.com/input", "headers": {}},
            }
        ],
        "output_upload": {
            "method": "PUT",
            "url": "https://cos.example.com/output",
            "headers": {"Content-Type": "video/mp4"},
        },
    }

    try:
        worker.run_render(job)
    except RuntimeError as exc:
        assert "did not create output file" in str(exc)
    else:
        raise AssertionError("worker should reject missing render output")


def test_preprocess_command_times_out_and_writes_logs(monkeypatch, tmp_path):
    script = tmp_path / "slow_preprocess.py"
    script.write_text(
        "\n".join(
            [
                "import time",
                "print('started', flush=True)",
                "time.sleep(5)",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PREPROCESS_COMMAND_TIMEOUT_SECONDS", "1")
    worker = _worker(monkeypatch, tmp_path)
    worker.render_command = f'"{sys.executable}" "{script}" "{{job_json}}"'

    job = {
        "job_id": "job-timeout",
        "job_type": "preprocess",
        "payload": {"task_type": "preprocess"},
    }

    try:
        worker.run_render(job)
    except RuntimeError as exc:
        assert "timed out after 1s" in str(exc)
    else:
        raise AssertionError("preprocess command should time out")

    job_dir = tmp_path / "worker" / "job-timeout"
    assert (job_dir / "command.stdout").read_text(encoding="utf-8") == "started\n"
    assert (job_dir / "command.stderr").exists()
