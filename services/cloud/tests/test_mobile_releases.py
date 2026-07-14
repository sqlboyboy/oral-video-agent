from __future__ import annotations

import hashlib
import importlib
import json

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path) -> tuple[TestClient, object]:
    release_dir = tmp_path / "releases" / "android"
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test")
    monkeypatch.setenv("WORKER_TOKEN", "worker-test")
    monkeypatch.setenv("CLOUD_DATABASE_PATH", str(tmp_path / "cloud.sqlite3"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "")
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "object-storage"))
    monkeypatch.setenv("ANDROID_RELEASE_DIR", str(release_dir))

    import app.email_sender as email_sender_module
    import app.main as main_module
    import app.object_storage as object_storage_module
    import app.settings as settings_module

    importlib.reload(settings_module)
    importlib.reload(email_sender_module)
    importlib.reload(object_storage_module)
    importlib.reload(main_module)
    return TestClient(main_module.app), release_dir


def _publish_release(release_dir, *, min_supported_version_code: int = 2) -> bytes:
    release_dir.mkdir(parents=True)
    apk = b"signed android package fixture"
    apk_name = "jiesu-oral-video-0.2.0.apk"
    (release_dir / apk_name).write_bytes(apk)
    (release_dir / "latest.json").write_text(
        json.dumps(
            {
                "version_name": "0.2.0",
                "version_code": 3,
                "apk_file": apk_name,
                "sha256": hashlib.sha256(apk).hexdigest(),
                "min_supported_version_code": min_supported_version_code,
                "force_update": False,
                "release_notes": ["支持应用内更新", "加强账号安全"],
                "published_at": "2026-07-14T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return apk


def test_latest_android_release_is_public_and_downloadable(monkeypatch, tmp_path):
    client, release_dir = _client(monkeypatch, tmp_path)
    apk = _publish_release(release_dir, min_supported_version_code=3)

    response = client.get("/api/mobile/releases/latest?version_code=2")

    assert response.status_code == 200
    body = response.json()
    assert body["version_name"] == "0.2.0"
    assert body["version_code"] == 3
    assert body["update_available"] is True
    assert body["force_update"] is True
    assert body["size_bytes"] == len(apk)
    assert body["sha256"] == hashlib.sha256(apk).hexdigest()
    assert body["download_url"].endswith("/jiesu-oral-video-0.2.0.apk/download")

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.content == apk
    assert download.headers["content-type"] == "application/vnd.android.package-archive"
    assert download.headers["x-content-type-options"] == "nosniff"


def test_latest_android_release_reports_current_version(monkeypatch, tmp_path):
    client, release_dir = _client(monkeypatch, tmp_path)
    _publish_release(release_dir)

    response = client.get("/api/mobile/releases/latest?version_code=3")

    assert response.status_code == 200
    assert response.json()["update_available"] is False
    assert response.json()["force_update"] is False


def test_latest_android_release_returns_404_before_publish(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    response = client.get("/api/mobile/releases/latest?version_code=2")

    assert response.status_code == 404
    assert response.json()["detail"] == "android release not published"


def test_android_release_rejects_path_traversal(monkeypatch, tmp_path):
    client, release_dir = _client(monkeypatch, tmp_path)
    release_dir.mkdir(parents=True)
    (release_dir / "latest.json").write_text(
        json.dumps(
            {
                "version_name": "0.2.0",
                "version_code": 3,
                "apk_file": "../unsafe.apk",
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/api/mobile/releases/latest?version_code=2")

    assert response.status_code == 503
    assert response.json()["detail"] == "android release manifest is invalid"
