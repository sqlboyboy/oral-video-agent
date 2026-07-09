from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_worker_claims_and_completes_job(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test")
    monkeypatch.setenv("WORKER_TOKEN", "worker-test")
    monkeypatch.setenv("CLOUD_DATABASE_PATH", str(tmp_path / "cloud.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "")

    import app.main as main

    importlib.reload(main)
    client = TestClient(main.app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["database_backend"] == "sqlite"
    assert health.json()["redis"]["enabled"] is False

    created = client.post(
        "/api/admin/jobs",
        headers={"X-Admin-Token": "admin-test"},
        json={"payload": {"duration_seconds": 600}, "priority": 1},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    claimed = client.post(
        "/api/worker/claim-job",
        headers={"Authorization": "Bearer worker-test"},
        json={"worker_id": "test-worker"},
    )
    assert claimed.status_code == 200
    assert claimed.json()["job"]["job_id"] == job_id
    assert claimed.json()["job"]["status"] == "running"

    completed = client.post(
        f"/api/worker/jobs/{job_id}/complete",
        headers={"Authorization": "Bearer worker-test"},
        json={"worker_id": "test-worker", "result": {"output_cos_key": "outputs/demo.mp4"}},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["progress_percent"] == 100

    queue = client.get("/api/admin/queue", headers={"X-Admin-Token": "admin-test"})
    assert queue.status_code == 200
    assert queue.json()["queued"] == 0


def test_preprocess_running_jobs_use_shorter_scheduler_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test")
    monkeypatch.setenv("WORKER_TOKEN", "worker-test")
    monkeypatch.setenv("CLOUD_DATABASE_PATH", str(tmp_path / "cloud.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "")

    import app.main as main

    importlib.reload(main)
    client = TestClient(main.app)

    render_job = client.post(
        "/api/admin/jobs",
        headers={"X-Admin-Token": "admin-test"},
        json={"payload": {}, "priority": 1, "job_type": "render"},
    ).json()
    claimed_render = client.post(
        "/api/worker/claim-job",
        headers={"Authorization": "Bearer worker-test"},
        json={"worker_id": "test-worker"},
    ).json()["job"]
    assert claimed_render["job_id"] == render_job["job_id"]

    preprocess_job = client.post(
        "/api/admin/jobs",
        headers={"X-Admin-Token": "admin-test"},
        json={"payload": {}, "priority": 1, "job_type": "preprocess"},
    ).json()
    claimed_preprocess = client.post(
        "/api/worker/claim-job",
        headers={"Authorization": "Bearer worker-test"},
        json={"worker_id": "test-worker"},
    ).json()["job"]
    assert claimed_preprocess["job_id"] == preprocess_job["job_id"]

    failed_jobs = main.store.fail_stale_running_jobs(
        timeout_seconds=9999,
        preprocess_timeout_seconds=0,
    )

    assert [job["job_id"] for job in failed_jobs] == [preprocess_job["job_id"]]
    assert main.store.get_job(render_job["job_id"])["status"] == "running"
    assert main.store.get_job(preprocess_job["job_id"])["status"] == "failed"
