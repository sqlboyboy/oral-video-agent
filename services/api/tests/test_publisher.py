import importlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import OralVideoTask, TaskStatus, storage_dir
from app.publisher.store import publisher_store
from app.repository import repo


client = TestClient(app)
publisher_router_module = importlib.import_module("app.publisher.router")
publisher_providers_module = importlib.import_module("app.publisher.providers")


@pytest.fixture(autouse=True)
def isolated_publisher_store(tmp_path):
    old_accounts_path = publisher_store._accounts_path
    old_jobs_path = publisher_store._jobs_path
    old_accounts = publisher_store._accounts.copy()
    old_jobs = publisher_store._jobs.copy()
    publisher_store._accounts_path = tmp_path / "accounts.json"
    publisher_store._jobs_path = tmp_path / "jobs.json"
    publisher_store._accounts = {}
    publisher_store._jobs = {}
    publisher_store.clear_for_tests()
    try:
        yield
    finally:
        publisher_store._accounts_path = old_accounts_path
        publisher_store._jobs_path = old_jobs_path
        publisher_store._accounts = old_accounts
        publisher_store._jobs = old_jobs


def test_publisher_account_lifecycle_and_publish_job(monkeypatch):
    monkeypatch.setenv("PUBLISHER_DISABLE_PLAYWRIGHT", "true")
    monkeypatch.setattr(publisher_router_module, "is_playable_mp4", lambda _: True)
    publisher_store.clear_for_tests()

    created = client.post(
        "/api/publisher/accounts",
        json={"platform": "douyin", "nickname": "brand-a"},
    )
    assert created.status_code == 200
    account = created.json()
    assert account["platform"] == "douyin"
    assert account["status"] == "needs_login"

    opened = client.post(
        f"/api/publisher/accounts/{account['account_id']}/login",
        json={"timeout_seconds": 30},
    )
    assert opened.status_code == 200
    assert opened.json()["status"] == "needs_user_action"

    state_path = Path(account["storage_state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"cookies": [{"name": "session", "value": "ok"}]}),
        encoding="utf-8",
    )
    checked = client.post(f"/api/publisher/accounts/{account['account_id']}/check-session")
    assert checked.status_code == 200
    assert checked.json()["status"] == "logged_in"

    video_path = storage_dir("outputs") / "publisher-test.mp4"
    video_path.write_bytes(b"fake mp4 bytes")
    task = OralVideoTask(title="发布测试", status=TaskStatus.completed)
    task.output_video_path = str(video_path)
    task.video_title = "发布测试标题"
    task.rewritten_script = "发布测试正文"
    repo.put(task)

    jobs = client.post(
        f"/api/tasks/{task.task_id}/publish-jobs",
        json={
            "account_ids": [account["account_id"]],
            "title": "发布测试标题",
            "body": "发布测试正文",
            "topics": ["口播", "#AI"],
        },
    )
    assert jobs.status_code == 200
    job = jobs.json()["items"][0]
    assert job["platform"] == "douyin"
    assert job["title"] == "发布测试标题"
    assert job["topics"] == ["口播", "AI"]

    final_job = job
    for _ in range(20):
        res = client.get(f"/api/publish-jobs/{job['job_id']}")
        assert res.status_code == 200
        final_job = res.json()
        if final_job["status"] in {"needs_user_action", "failed", "published"}:
            break
        time.sleep(0.1)

    assert final_job["status"] == "needs_user_action"
    assert "Playwright" in final_job["error_message"]


def test_publisher_account_allows_deferred_name_and_deduplicates():
    publisher_store.clear_for_tests()

    unnamed = client.post(
        "/api/publisher/accounts",
        json={"platform": "douyin", "nickname": ""},
    )
    assert unnamed.status_code == 200
    assert unnamed.json()["nickname"] == ""
    assert unnamed.json()["status"] == "needs_login"

    duplicate_unnamed = client.post(
        "/api/publisher/accounts",
        json={"platform": "douyin", "nickname": ""},
    )
    assert duplicate_unnamed.status_code == 200
    assert duplicate_unnamed.json()["account_id"] == unnamed.json()["account_id"]

    first = client.post(
        "/api/publisher/accounts",
        json={"platform": "douyin", "nickname": "主账号"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/publisher/accounts",
        json={"platform": "douyin", "nickname": "主账号"},
    )
    assert second.status_code == 200
    assert second.json()["account_id"] == first.json()["account_id"]
    listed = client.get("/api/publisher/accounts")
    assert len(listed.json()["items"]) == 2


def test_xiaohongshu_description_combines_body_and_topics():
    description = publisher_providers_module._compose_xiaohongshu_description(
        "这是前端第二个框的作品简介",
        ["人生感悟", "#新人视频", "人生感悟"],
    )

    assert description == "这是前端第二个框的作品简介 #人生感悟 #新人视频"
