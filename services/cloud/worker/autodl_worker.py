from __future__ import annotations

import json
import http.client
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class ApiClient:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API {method} {path} failed: {exc.code} {detail}") from exc
        return json.loads(body) if body else {}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def output_tail(value: str | bytes | None, limit: int = 1200) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value[-limit:]


class AutoDlWorker:
    def __init__(self) -> None:
        base_url = required_env("CLOUD_API_BASE")
        token = required_env("WORKER_TOKEN")
        self.worker_id = os.getenv("WORKER_ID") or f"autodl-{socket.gethostname()}"
        self.poll_seconds = env_int("WORKER_POLL_SECONDS", 30)
        self.idle_shutdown_minutes = env_int("IDLE_SHUTDOWN_MINUTES", 15)
        self.enable_shutdown = env_bool("ENABLE_AUTODL_SHUTDOWN", False)
        self.shutdown_command = os.getenv("SHUTDOWN_COMMAND", "sudo shutdown -h now")
        self.simulate_seconds = env_int("SIMULATE_RENDER_SECONDS", 20)
        self.render_command = os.getenv("RENDER_COMMAND", "").strip()
        self.render_command_timeout_seconds = env_int("RENDER_COMMAND_TIMEOUT_SECONDS", 7200)
        self.preprocess_command_timeout_seconds = env_int("PREPROCESS_COMMAND_TIMEOUT_SECONDS", 300)
        self.work_dir = Path(os.getenv("WORKER_WORK_DIR", "/tmp/oral-video-agent-worker"))
        self.api = ApiClient(base_url=base_url, token=token)
        self.idle_started_at: float | None = None

    def run_forever(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.safe_heartbeat(status="idle", message="worker started")
        while True:
            try:
                response = self.api.post("/api/worker/claim-job", {"worker_id": self.worker_id})
                job = response.get("job")
                if job is None:
                    self.handle_idle()
                    continue
                self.idle_started_at = None
                self.process_job(job)
            except Exception as exc:
                self.safe_heartbeat(status="error", message=str(exc))
                time.sleep(min(self.poll_seconds, 60))

    def process_job(self, job: dict[str, Any]) -> None:
        job_id = job["job_id"]
        try:
            self.safe_heartbeat(status="running", current_job_id=job_id, message="processing")
            self.progress(job_id, 5, "任务开始")
            result = self.run_render(job)
            self.progress(job_id, 95, "上传结果完成")
            self.api.post(
                f"/api/worker/jobs/{job_id}/complete",
                {
                    "worker_id": self.worker_id,
                    "result": result,
                },
            )
            self.safe_heartbeat(status="idle", message="job completed")
        except Exception as exc:
            self.api.post(
                f"/api/worker/jobs/{job_id}/fail",
                {
                    "worker_id": self.worker_id,
                    "error_message": str(exc),
                },
            )
            self.safe_heartbeat(status="idle", message=f"job failed: {exc}")

    def run_render(self, job: dict[str, Any]) -> dict[str, Any]:
        job_work_dir = self.work_dir / job["job_id"]
        input_dir = job_work_dir / "inputs"
        output_dir = job_work_dir / "outputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        local_job = self.prepare_local_job(job, input_dir=input_dir, output_dir=output_dir)
        payload_path = job_work_dir / "job.json"
        payload_path.write_text(json.dumps(local_job, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.render_command:
            self.progress(job["job_id"], 15, "执行本地渲染脚本")
            command = self.render_command.format(
                job_json=str(payload_path),
                job_id=job["job_id"],
                output_path=local_job["local_output_path"],
                work_dir=str(job_work_dir),
            )
            env = os.environ.copy()
            env.update(
                {
                    "ORAL_VIDEO_JOB_JSON": str(payload_path),
                    "ORAL_VIDEO_JOB_ID": job["job_id"],
                    "ORAL_VIDEO_OUTPUT_PATH": local_job["local_output_path"],
                    "ORAL_VIDEO_WORK_DIR": str(job_work_dir),
                }
            )
            timeout_seconds = self.command_timeout_seconds(local_job)
            try:
                completed = subprocess.run(
                    command,
                    shell=True,
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                (job_work_dir / "command.stdout").write_text(
                    output_tail(exc.stdout, 8000),
                    encoding="utf-8",
                )
                (job_work_dir / "command.stderr").write_text(
                    output_tail(exc.stderr, 8000),
                    encoding="utf-8",
                )
                detail = output_tail(exc.stderr or exc.stdout)
                raise RuntimeError(
                    f"render command timed out after {timeout_seconds}s: {detail}"
                ) from exc
            (job_work_dir / "command.stdout").write_text(
                output_tail(completed.stdout, 8000),
                encoding="utf-8",
            )
            (job_work_dir / "command.stderr").write_text(
                output_tail(completed.stderr, 8000),
                encoding="utf-8",
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"render command failed: {detail[-1200:]}")
            if self.is_preprocess_job(local_job):
                result = self.parse_command_result(completed.stdout)
                result.setdefault("mode", "preprocess_command")
                result["job_json"] = str(payload_path)
                output_path = Path(local_job["local_output_path"])
                output_cos_key = (local_job.get("payload") or {}).get("output_cos_key")
                if output_cos_key and output_path.exists() and output_path.stat().st_size > 0:
                    self.progress(job["job_id"], 90, "上传预处理结果到云端临时存储")
                    self.upload_output(job=local_job, output_path=output_path)
                    result["output_cos_key"] = output_cos_key
                    result["output_file_name"] = (
                        (local_job.get("payload") or {}).get("output_file_name")
                        or output_path.name
                    )
                    result["output_content_type"] = (
                        (local_job.get("payload") or {}).get("output_content_type")
                        or "application/octet-stream"
                    )
                else:
                    self.progress(job["job_id"], 90, "云端文案处理完成")
                return result
            output_path = Path(local_job["local_output_path"])
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"render command did not create output file: {output_path}")
            self.progress(job["job_id"], 90, "上传成品到云端临时存储")
            self.upload_output(job=local_job, output_path=output_path)
            result = {
                "mode": "render_command",
                "stdout_tail": completed.stdout[-1200:],
                "job_json": str(payload_path),
                "output_path": str(output_path),
            }
            output_cos_key = (local_job.get("payload") or {}).get("output_cos_key")
            if output_cos_key:
                result["output_cos_key"] = output_cos_key
            return result
        raise RuntimeError(
            "RENDER_COMMAND is not configured; refusing to mark cloud render as completed"
        )

    def command_timeout_seconds(self, job: dict[str, Any]) -> int:
        if self.is_preprocess_job(job):
            return self.preprocess_command_timeout_seconds
        return self.render_command_timeout_seconds

    def is_preprocess_job(self, job: dict[str, Any]) -> bool:
        payload = job.get("payload") or {}
        return job.get("job_type") == "preprocess" or payload.get("task_type") == "preprocess"

    def parse_command_result(self, stdout: str) -> dict[str, Any]:
        for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise RuntimeError("render command did not return JSON result")

    def prepare_local_job(
        self,
        job: dict[str, Any],
        *,
        input_dir: Path,
        output_dir: Path,
    ) -> dict[str, Any]:
        local_job = json.loads(json.dumps(job, ensure_ascii=False))
        payload = dict(local_job.get("payload") or {})
        local_inputs: list[dict[str, Any]] = []
        input_assets = local_job.get("input_assets") or payload.get("input_assets") or []
        for index, asset in enumerate(input_assets):
            file_name = self.safe_file_name(asset.get("file_name") or f"asset-{index}")
            local_path = input_dir / f"{index:02d}-{file_name}"
            download = asset.get("download") or {}
            url = download.get("url")
            if not url:
                raise RuntimeError(f"input asset missing download url: {asset.get('asset_id')}")
            self.download_file(url=url, dest=local_path, headers=download.get("headers") or {})
            item = dict(asset)
            item["local_path"] = str(local_path)
            local_inputs.append(item)
        output_path = output_dir / self.output_file_name_for_job(local_job)
        payload["input_assets"] = local_inputs
        payload["local_output_path"] = str(output_path)
        local_job["input_assets"] = local_inputs
        local_job["local_output_path"] = str(output_path)
        local_job["payload"] = payload
        return local_job

    def output_file_name_for_job(self, job: dict[str, Any]) -> str:
        payload = job.get("payload") or {}
        configured = str(payload.get("output_file_name") or "").strip()
        if configured:
            return self.safe_file_name(configured)
        operation = str(payload.get("operation") or "").strip().lower()
        if self.is_preprocess_job(job) and operation == "voice":
            return "result.wav"
        return "result.mp4"

    def upload_output(self, *, job: dict[str, Any], output_path: Path) -> None:
        upload = job.get("output_upload") or (job.get("payload") or {}).get("output_upload")
        if not upload:
            raise RuntimeError("job missing output_upload url")
        url = upload.get("url")
        if not url:
            raise RuntimeError("job missing output_upload url")
        headers = dict(upload.get("headers") or {})
        if "Content-Type" not in headers:
            headers["Content-Type"] = "video/mp4"
        self.upload_file(
            url=url,
            source=output_path,
            headers=headers,
            method=upload.get("method") or "PUT",
        )

    def download_file(self, *, url: str, dest: Path, headers: dict[str, str]) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=300) as response, open(dest, "wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)

    def upload_file(
        self,
        *,
        url: str,
        source: Path,
        headers: dict[str, str],
        method: str = "PUT",
    ) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError(f"unsupported upload url scheme: {parsed.scheme}")
        connection_class = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request_headers = dict(headers)
        request_headers["Content-Length"] = str(source.stat().st_size)
        connection = connection_class(parsed.netloc, timeout=300)
        try:
            with open(source, "rb") as body:
                connection.request(method.upper(), path, body=body, headers=request_headers)
                response = connection.getresponse()
                detail = response.read().decode("utf-8", errors="replace")
                if response.status >= 300:
                    raise RuntimeError(
                        f"upload failed: HTTP {response.status} {detail[-500:]}"
                    )
        finally:
            connection.close()

    def safe_file_name(self, value: str) -> str:
        cleaned = value.replace("\\", "/").split("/")[-1].strip()
        return cleaned[:180] or "asset"

    def simulate_render(self, job: dict[str, Any]) -> dict[str, Any]:
        steps = max(1, min(self.simulate_seconds, 60))
        for index in range(steps):
            percent = 10 + int((index + 1) / steps * 80)
            self.progress(job["job_id"], percent, "模拟生成中")
            time.sleep(1)
        result = {
            "mode": "simulated",
            "message": "真实渲染命令尚未配置，worker 已完成队列协议测试。",
        }
        output_cos_key = (job.get("payload") or {}).get("output_cos_key")
        if output_cos_key:
            result["output_cos_key"] = output_cos_key
        return result

    def handle_idle(self) -> None:
        now = time.time()
        if self.idle_started_at is None:
            self.idle_started_at = now
        idle_seconds = int(now - self.idle_started_at)
        self.heartbeat(status="idle", message=f"idle {idle_seconds}s")
        if idle_seconds >= self.idle_shutdown_minutes * 60:
            self.shutdown_if_enabled()
        time.sleep(self.poll_seconds)

    def shutdown_if_enabled(self) -> None:
        if not self.enable_shutdown:
            self.heartbeat(
                status="idle",
                message="idle threshold reached; shutdown disabled",
            )
            self.idle_started_at = time.time()
            return
        self.heartbeat(status="shutting_down", message="idle threshold reached")
        subprocess.Popen(self.shutdown_command, shell=True)
        sys.exit(0)

    def heartbeat(
        self,
        *,
        status: str,
        message: str,
        current_job_id: str | None = None,
    ) -> None:
        self.api.post(
            "/api/worker/heartbeat",
            {
                "worker_id": self.worker_id,
                "status": status,
                "current_job_id": current_job_id,
                "message": message,
            },
        )

    def safe_heartbeat(
        self,
        *,
        status: str,
        message: str,
        current_job_id: str | None = None,
    ) -> None:
        try:
            self.heartbeat(
                status=status,
                message=message,
                current_job_id=current_job_id,
            )
        except Exception as exc:
            print(f"heartbeat failed: {exc}", file=sys.stderr, flush=True)

    def progress(self, job_id: str, percent: int, message: str) -> None:
        self.api.post(
            f"/api/worker/jobs/{job_id}/progress",
            {
                "worker_id": self.worker_id,
                "percent": percent,
                "message": message,
            },
        )


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    AutoDlWorker().run_forever()
