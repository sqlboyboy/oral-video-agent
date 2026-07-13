import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

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

    legacy_placeholder = client.post(
        "/api/publisher/accounts",
        json={"platform": "douyin", "nickname": False},
    )
    assert legacy_placeholder.status_code == 200
    assert legacy_placeholder.json()["nickname"] == ""
    assert legacy_placeholder.json()["account_id"] == unnamed.json()["account_id"]

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


def test_publish_job_accepts_explicit_video_path(monkeypatch):
    monkeypatch.setenv("PUBLISHER_DISABLE_PLAYWRIGHT", "true")
    monkeypatch.setattr(publisher_router_module, "is_playable_mp4", lambda _: True)
    publisher_store.clear_for_tests()

    created = client.post(
        "/api/publisher/accounts",
        json={"platform": "xiaohongshu", "nickname": "Zzz"},
    )
    assert created.status_code == 200
    account = created.json()

    video_path = storage_dir("outputs") / "cloud-downloaded-test.mp4"
    video_path.write_bytes(b"fake mp4 bytes")
    task = OralVideoTask(title="云端发布测试", status=TaskStatus.completed)
    task.video_title = "云端发布标题"
    task.rewritten_script = "云端发布正文"
    repo.put(task)

    jobs = client.post(
        f"/api/tasks/{task.task_id}/publish-jobs",
        json={
            "account_ids": [account["account_id"]],
            "title": "云端发布标题",
            "body": "云端发布正文",
            "topics": ["云端"],
            "video_path": str(video_path),
        },
    )

    assert jobs.status_code == 200
    job = jobs.json()["items"][0]
    assert job["video_path"] == str(video_path)


def test_xiaohongshu_description_combines_body_and_topics():
    description = publisher_providers_module._compose_xiaohongshu_description(
        "这是前端第二个框的作品简介",
        ["人生感悟", "#新人视频", "人生感悟"],
    )

    assert description == "这是前端第二个框的作品简介 #人生感悟 #新人视频"


def test_douyin_topic_input_failure_is_not_reported_as_added(monkeypatch):
    removed = []
    clicked = []
    monkeypatch.setattr(
        publisher_providers_module, "_dismiss_douyin_publish_guides", lambda page: None
    )
    monkeypatch.setattr(
        publisher_providers_module, "_open_add_topic_entry", lambda page: True
    )
    monkeypatch.setattr(
        publisher_providers_module, "_type_topic_query", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        publisher_providers_module,
        "_remove_douyin_empty_topic_trigger",
        lambda page: removed.append(True),
    )
    monkeypatch.setattr(
        publisher_providers_module,
        "_click_topic_suggestion",
        lambda *args: clicked.append(True),
    )
    job = SimpleNamespace(logs=[])

    publisher_providers_module._best_effort_add_topics(
        object(),
        publisher_providers_module.PublisherPlatform.douyin,
        ["自动生成视频"],
        job,
    )

    assert removed == [True]
    assert clicked == []
    assert job.logs == ["topic_query_input_failed:自动生成视频"]


def test_douyin_topic_is_logged_only_after_editor_confirmation(monkeypatch):
    type_options = []
    monkeypatch.setattr(
        publisher_providers_module, "_dismiss_douyin_publish_guides", lambda page: None
    )
    monkeypatch.setattr(
        publisher_providers_module, "_open_add_topic_entry", lambda page: True
    )

    def type_topic(*args, **kwargs):
        type_options.append(kwargs)
        return True

    monkeypatch.setattr(publisher_providers_module, "_type_topic_query", type_topic)
    monkeypatch.setattr(
        publisher_providers_module,
        "_click_topic_suggestion",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publisher_providers_module, "_douyin_editor_has_topic", lambda *args: True
    )
    monkeypatch.setattr(
        publisher_providers_module,
        "_douyin_editor_has_native_topic",
        lambda *args: True,
    )
    monkeypatch.setattr(
        publisher_providers_module,
        "_close_douyin_topic_suggestions",
        lambda page: None,
    )
    job = SimpleNamespace(logs=[])

    publisher_providers_module._best_effort_add_topics(
        object(),
        publisher_providers_module.PublisherPlatform.douyin,
        ["自动生成视频"],
        job,
    )

    assert type_options == [{"allow_contenteditable": True}]
    assert job.logs == ["topic_added:自动生成视频:selected"]


def test_douyin_topic_without_exact_suggestion_is_kept_as_plain_text(monkeypatch):
    closed = []
    monkeypatch.setattr(
        publisher_providers_module, "_dismiss_douyin_publish_guides", lambda page: None
    )
    monkeypatch.setattr(
        publisher_providers_module, "_open_add_topic_entry", lambda page: True
    )
    monkeypatch.setattr(
        publisher_providers_module, "_type_topic_query", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        publisher_providers_module, "_click_topic_suggestion", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        publisher_providers_module, "_douyin_editor_has_topic", lambda *args: True
    )
    monkeypatch.setattr(
        publisher_providers_module,
        "_douyin_editor_has_native_topic",
        lambda *args: False,
    )
    monkeypatch.setattr(
        publisher_providers_module,
        "_close_douyin_topic_suggestions",
        lambda page: closed.append(True),
    )
    job = SimpleNamespace(logs=[])

    publisher_providers_module._best_effort_add_topics(
        object(),
        publisher_providers_module.PublisherPlatform.douyin,
        ["智能配音"],
        job,
    )

    assert closed == [True]
    assert job.logs == ["topic_added:智能配音:plain"]


def test_douyin_preview_transcoding_does_not_block_publish(monkeypatch):
    monkeypatch.setattr(
        publisher_providers_module,
        "_is_text_visible",
        lambda page, text: text == "转码过程也可以发布作品",
    )
    page = SimpleNamespace(
        wait_for_timeout=lambda milliseconds: pytest.fail("should not wait")
    )
    job = SimpleNamespace(logs=[])

    publisher_providers_module._wait_for_upload_ready(
        page,
        job,
        platform=publisher_providers_module.PublisherPlatform.douyin,
    )

    assert job.logs == ["upload_ready_douyin_transcoding_allowed"]


def test_douyin_uses_platform_specific_publish_button(monkeypatch):
    calls = []

    def click_douyin(page, mode, job):
        calls.append((page, mode, job))
        return True

    monkeypatch.setattr(
        publisher_providers_module, "_click_douyin_action", click_douyin
    )
    page = object()
    job = SimpleNamespace(logs=[])

    clicked = publisher_providers_module._best_effort_click_action(
        page,
        "direct",
        publisher_providers_module.PublisherPlatform.douyin,
        job,
    )

    assert clicked is True
    assert calls == [(page, "direct", job)]
