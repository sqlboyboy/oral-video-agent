from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test")
    monkeypatch.setenv("WORKER_TOKEN", "worker-test")
    monkeypatch.setenv("CLOUD_DATABASE_PATH", str(tmp_path / "cloud.sqlite3"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "")
    monkeypatch.setenv("LICENSE_ACTIVATION_GRANT_POINTS", "0")
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    monkeypatch.setenv("EMAIL_CODE_TTL_SECONDS", "600")
    monkeypatch.setenv("EMAIL_CODE_RESEND_SECONDS", "0")
    monkeypatch.setenv("EMAIL_CODE_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("MAX_DEVICES_PER_USER", "1")
    monkeypatch.setenv("BONUS_DAILY_SPEND_LIMIT", "90")
    monkeypatch.setenv("MAX_RENDER_DURATION_SECONDS", "600")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "object-storage"))
    monkeypatch.setenv("CLOUD_PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("COS_CLEANUP_HOURS", "72")
    monkeypatch.setenv("COS_DOWNLOAD_CONFIRM_DELETE_DELAY_HOURS", "0")

    import app.settings as settings_module
    import app.email_sender as email_sender_module
    import app.object_storage as object_storage_module
    import app.main as main_module

    importlib.reload(settings_module)
    importlib.reload(email_sender_module)
    importlib.reload(object_storage_module)
    importlib.reload(main_module)
    return TestClient(main_module.app)


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "admin-test"}


def _worker_headers() -> dict[str, str]:
    return {"Authorization": "Bearer worker-test"}


def _device_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_web_admin_login_and_dashboard(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    page = client.get("/admin")
    assert page.status_code == 200
    assert "口播云后台" in page.text

    denied = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert denied.status_code == 401

    logged_in = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "admin-test"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["username"] == "admin"

    dashboard = client.get("/api/admin/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["users"] == {"total": 0, "active": 0}
    assert dashboard.json()["wallets"]["paid_points"] == 0

    logged_out = client.post("/api/admin/session/logout")
    assert logged_out.status_code == 200
    assert client.get("/api/admin/dashboard").status_code == 401


def test_admin_creates_user_with_zero_usage_and_zero_points(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "admin-test"},
    )

    created = client.post(
        "/api/admin/users",
        json={"email": "new-user@example.com", "initial_points": 250},
    )

    assert created.status_code == 200
    body = created.json()
    user_id = body["user"]["user_id"]
    activation_code = body["activation_code"]
    assert body["user"]["email"] == "new-user@example.com"
    assert body["wallet"]["paid_balance"] == 0
    assert body["wallet"]["available_points"] == 0
    assert body["ledger"] == []
    assert body["user"]["usage_access"]["has_access"] is False
    assert body["user"]["usage_access"]["remaining_days"] == 0
    assert body["user"]["usage_access"]["remaining_hours"] == 0
    assert body["user"]["usage_access"]["remaining_minutes"] == 0

    duplicate = client.post(
        "/api/admin/users",
        json={"email": "NEW-USER@example.com", "initial_points": 0},
    )
    assert duplicate.status_code == 409

    licenses = client.get("/api/admin/license-keys").json()["items"]
    assigned = next(item for item in licenses if item["license_key"] == activation_code)
    assert assigned["assigned_user_id"] == user_id
    assert assigned["activation_count"] == 0

    activated = client.post(
        "/api/client/activate",
        json={
            "license_key": activation_code,
            "device_fingerprint": "new-user-device",
            "device_name": "Windows client",
        },
    )
    assert activated.status_code == 200
    assert activated.json()["user"]["user_id"] == user_id
    assert activated.json()["user"]["email"] == "new-user@example.com"
    assert activated.json()["user"]["license_status"] == "active"
    assert activated.json()["wallet"]["available_points"] == 0
    assert activated.json()["user"]["usage_access"]["has_access"] is False


def test_admin_updates_user_usage_with_shortcuts_and_points_are_disabled(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/admin/users",
        headers=_admin_headers(),
        json={"email": "debit@example.com", "initial_points": 0},
    )
    user_id = created.json()["user"]["user_id"]

    added_day = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "1d"},
    )
    assert added_day.status_code == 200
    access = added_day.json()["user"]["usage_access"]
    assert access["has_access"] is True
    assert access["unlimited"] is False
    assert access["remaining_days"] == 1

    added_week = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "7d"},
    )
    assert added_week.status_code == 200
    assert added_week.json()["user"]["usage_access"]["remaining_days"] == 8

    previous_expiry = datetime.fromisoformat(
        added_week.json()["user"]["usage_access"]["expires_at"]
    )
    custom_minutes = (2 * 24 * 60) + (3 * 60) + 4
    custom = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "custom", "duration_minutes": custom_minutes},
    )
    assert custom.status_code == 200
    custom_expiry = datetime.fromisoformat(
        custom.json()["user"]["usage_access"]["expires_at"]
    )
    assert (custom_expiry - previous_expiry).total_seconds() == custom_minutes * 60

    missing_custom_duration = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "custom"},
    )
    assert missing_custom_duration.status_code == 400

    specified_expiry = datetime.now(timezone.utc) + timedelta(
        days=12, hours=3, minutes=4
    )
    specified = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "expires_at", "expires_at": specified_expiry.isoformat()},
    )
    assert specified.status_code == 200
    specified_access = specified.json()["user"]["usage_access"]
    actual_expiry = datetime.fromisoformat(specified_access["expires_at"])
    assert abs((actual_expiry - specified_expiry).total_seconds()) < 1

    missing_expiry = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "expires_at"},
    )
    assert missing_expiry.status_code == 400

    unlimited = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "unlimited"},
    )
    assert unlimited.status_code == 200
    assert unlimited.json()["user"]["usage_access"]["unlimited"] is True

    old_credit = client.post(
        f"/api/admin/users/{user_id}/credits",
        headers=_admin_headers(),
        json={"points": 70},
    )
    assert old_credit.status_code == 410
    old_debit = client.post(
        f"/api/admin/users/{user_id}/debits",
        headers=_admin_headers(),
        json={"points": 10},
    )
    assert old_debit.status_code == 410


def test_admin_deletes_user_after_active_cloud_jobs_are_cleared(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/admin/users",
        headers=_admin_headers(),
        json={"email": "delete-user@example.com"},
    )
    assert created.status_code == 200
    user_id = created.json()["user"]["user_id"]
    activation_code = created.json()["activation_code"]

    activated = client.post(
        "/api/client/activate",
        json={
            "license_key": activation_code,
            "device_fingerprint": "delete-user-device",
            "device_name": "Windows client",
        },
    )
    assert activated.status_code == 200
    device_token = activated.json()["device_token"]

    granted = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "unlimited"},
    )
    assert granted.status_code == 200
    queued = client.post(
        "/api/client/jobs",
        headers=_device_headers(device_token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert queued.status_code == 200

    blocked = client.delete(
        f"/api/admin/users/{user_id}",
        headers=_admin_headers(),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "user has active cloud jobs"

    canceled = client.post(
        f"/api/client/jobs/{queued.json()['job_id']}/cancel",
        headers=_device_headers(device_token),
    )
    assert canceled.status_code == 200

    deleted = client.delete(
        f"/api/admin/users/{user_id}",
        headers=_admin_headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["user_id"] == user_id
    assert deleted.json()["jobs"] == 1
    assert deleted.json()["devices"] == 1

    assert (
        client.get(
            f"/api/admin/users/{user_id}",
            headers=_admin_headers(),
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/client/me",
            headers=_device_headers(device_token),
        ).status_code
        == 401
    )
    licenses = client.get(
        "/api/admin/license-keys",
        headers=_admin_headers(),
    ).json()["items"]
    assert all(item["license_key"] != activation_code for item in licenses)


def test_admin_delete_auto_cleans_stale_uploading_jobs(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/admin/users",
        headers=_admin_headers(),
        json={"email": "stale-upload-user@example.com"},
    ).json()
    user_id = created["user"]["user_id"]
    activated = client.post(
        "/api/client/activate",
        json={
            "license_key": created["activation_code"],
            "device_fingerprint": "stale-upload-device",
            "device_name": "Windows client",
        },
    )
    device_token = activated.json()["device_token"]
    client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "unlimited"},
    )
    uploading = client.post(
        "/api/client/jobs/upload-session",
        headers=_device_headers(device_token),
        json={
            "assets": [
                {
                    "kind": "source_video",
                    "file_name": "stale.mp4",
                    "content_type": "video/mp4",
                    "file_size_bytes": 1024,
                }
            ],
            "payload": {"script": "stale upload"},
        },
    )
    assert uploading.status_code == 200
    assert uploading.json()["status"] == "uploading"

    import app.main as main_module

    stale_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    with main_module.store.connect() as db:
        db.execute(
            "UPDATE render_jobs SET updated_at = ? WHERE job_id = ?",
            (stale_time, uploading.json()["job_id"]),
        )

    deleted = client.delete(
        f"/api/admin/users/{user_id}",
        headers=_admin_headers(),
    )

    assert deleted.status_code == 200
    assert deleted.json()["stale_upload_jobs_cleaned"] == 1
    assert (
        client.get(
            f"/api/admin/jobs/{uploading.json()['job_id']}",
            headers=_admin_headers(),
        ).status_code
        == 404
    )


def test_expired_invalid_jobs_are_purged_after_retention(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)
    uploading = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    job_id = uploading.json()["job_id"]
    canceled = client.post(
        f"/api/client/jobs/{job_id}/cancel",
        headers=_device_headers(token),
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"

    import app.main as main_module

    stale_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with main_module.store.connect() as db:
        db.execute(
            "UPDATE render_jobs SET updated_at = ? WHERE job_id = ?",
            (stale_time, job_id),
        )

    purged = main_module.store.purge_expired_invalid_jobs(
        retention_seconds=7 * 24 * 60 * 60,
    )

    assert purged["jobs"] == 1
    assert purged["job_ids"] == [job_id]
    assert (
        client.get(
            f"/api/admin/jobs/{job_id}",
            headers=_admin_headers(),
        ).status_code
        == 404
    )


def test_duration_billing_migration_resets_existing_users(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/admin/users",
        headers=_admin_headers(),
        json={"email": "legacy-points@example.com"},
    ).json()
    user_id = created["user"]["user_id"]

    import app.main as main_module

    now = datetime.now(timezone.utc).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    with main_module.store.connect() as db:
        db.execute(
            """
            UPDATE credit_wallets
            SET bonus_balance = 25, paid_balance = 75,
                frozen_bonus = 5, frozen_paid = 10
            WHERE user_id = ?
            """,
            (user_id,),
        )
        db.execute(
            """
            UPDATE users
            SET usage_expires_at = ?, usage_unlimited = 1
            WHERE user_id = ?
            """,
            (future, user_id),
        )
        db.execute(
            """
            INSERT INTO credit_holds (
                hold_id, user_id, status, bonus_points, paid_points,
                total_points, created_at, updated_at, reason
            )
            VALUES ('legacy-hold', ?, 'active', 5, 10, 15, ?, ?, 'legacy')
            """,
            (user_id, now, now),
        )
        db.execute("UPDATE license_keys SET grant_points = 500")
        db.execute(
            "DELETE FROM schema_migrations WHERE migration_key = ?",
            ("2026-07-25-duration-billing-v1",),
        )

    migrated = type(main_module.store)(
        main_module.store.database_path,
        database_url=main_module.store.database_url,
    )
    detail = migrated.get_user_detail(user_id=user_id)
    assert detail["wallet"]["total_points"] == 0
    assert detail["user"]["usage_access"]["has_access"] is False
    assert detail["user"]["usage_access"]["remaining_days"] == 0
    with migrated.connect() as db:
        hold = db.execute(
            "SELECT * FROM credit_holds WHERE hold_id = 'legacy-hold'"
        ).fetchone()
        license_row = db.execute(
            "SELECT * FROM license_keys WHERE assigned_user_id = ?",
            (user_id,),
        ).fetchone()
    assert hold["status"] == "released"
    assert hold["total_points"] == 0
    assert license_row["grant_points"] == 0


def test_admin_displays_and_edits_license_expiration(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    created = client.post(
        "/api/admin/license-keys",
        headers=_admin_headers(),
        json={
            "license_key": "EXPIRY-EDIT",
            "max_activations": 1,
            "grant_points": 0,
            "expires_at": future,
        },
    )
    assert created.status_code == 200
    assert created.json()["expires_at"] == future

    listed = client.get("/api/admin/license-keys", headers=_admin_headers()).json()["items"]
    license_item = next(item for item in listed if item["license_key"] == "EXPIRY-EDIT")
    assert license_item["effective_status"] == "active"

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    expired = client.patch(
        "/api/admin/license-keys/EXPIRY-EDIT",
        headers=_admin_headers(),
        json={"expires_at": past},
    )
    assert expired.status_code == 200
    assert expired.json()["effective_status"] == "expired"
    blocked = client.post(
        "/api/client/activate",
        json={
            "license_key": "EXPIRY-EDIT",
            "device_fingerprint": "expiry-device",
        },
    )
    assert blocked.status_code == 404

    permanent = client.patch(
        "/api/admin/license-keys/EXPIRY-EDIT",
        headers=_admin_headers(),
        json={"expires_at": None},
    )
    assert permanent.status_code == 200
    assert permanent.json()["expires_at"] is None
    assert permanent.json()["effective_status"] == "active"
    activated = client.post(
        "/api/client/activate",
        json={
            "license_key": "EXPIRY-EDIT",
            "device_fingerprint": "expiry-device",
        },
    )
    assert activated.status_code == 200


def _activate_software(
    client: TestClient,
    *,
    license_key: str = "LIC-MVP",
    fingerprint: str = "windows-device-1",
    max_activations: int = 1,
) -> tuple[str, dict]:
    created = client.post(
        "/api/admin/license-keys",
        headers=_admin_headers(),
        json={"license_key": license_key, "max_activations": max_activations},
    )
    assert created.status_code == 200
    activated = client.post(
        "/api/client/activate",
        json={
            "license_key": license_key,
            "device_fingerprint": fingerprint,
            "device_name": "Windows client",
        },
    )
    assert activated.status_code == 200
    body = activated.json()
    return body["device_token"], body


def _bind_email(
    client: TestClient,
    token: str,
    *,
    email: str = "client@example.com",
    fingerprint: str = "windows-device-1",
) -> tuple[str, dict]:
    sent = client.post(
        "/api/client/auth/email-code",
        headers=_device_headers(token),
        json={"email": email},
    )
    assert sent.status_code == 200, sent.text
    code = sent.json()["debug_code"]
    logged_in = client.post(
        "/api/client/auth/login",
        headers=_device_headers(token),
        json={
            "email": email,
            "code": code,
            "device_fingerprint": fingerprint,
            "device_name": "Windows client",
        },
    )
    assert logged_in.status_code == 200
    body = logged_in.json()
    return body["device_token"], body


def _activate(client: TestClient, license_key: str = "LIC-MVP") -> str:
    token, body = _activate_software(client, license_key=license_key)
    assert body["user"]["license_status"] == "active"
    assert body["user"]["email"] is None
    assert body["wallet"]["bonus_balance"] == 0
    assert body["wallet"]["available_points"] == 0
    token, body = _bind_email(client, token)
    assert body["user"]["email"] == "client@example.com"
    granted = client.post(
        f"/api/admin/users/{body['user']['user_id']}/usage",
        headers=_admin_headers(),
        json={"preset": "unlimited"},
    )
    assert granted.status_code == 200
    assert granted.json()["user"]["usage_access"]["unlimited"] is True
    return token


def test_software_activation_required_before_email_account_and_cloud_job(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    unauthenticated_code = client.post(
        "/api/client/auth/email-code",
        json={"email": "client@example.com"},
    )
    assert unauthenticated_code.status_code == 401

    token, activated = _activate_software(client)
    assert activated["user"]["license_status"] == "active"
    assert activated["user"]["email"] is None
    assert activated["wallet"]["available_points"] == 0

    estimated_without_account = client.post(
        "/api/client/jobs/estimate",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert estimated_without_account.status_code == 403

    ledger_without_account = client.get(
        "/api/client/credits/ledger",
        headers=_device_headers(token),
    )
    assert ledger_without_account.status_code == 200
    assert ledger_without_account.json()["wallet"]["available_points"] == 0

    token, bound = _bind_email(client, token)
    assert bound["user"]["email"] == "client@example.com"

    me = client.get("/api/client/me", headers=_device_headers(token))
    assert me.status_code == 200
    assert me.json()["wallet"]["available_points"] == 0
    assert me.json()["user"]["usage_access"]["has_access"] is False
    assert me.json()["device"]["device_fingerprint"] == "windows-device-1"

    expired_estimate = client.post(
        "/api/client/jobs/estimate",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert expired_estimate.status_code == 403

    granted = client.post(
        f"/api/admin/users/{bound['user']['user_id']}/usage",
        headers=_admin_headers(),
        json={"preset": "1d"},
    )
    assert granted.status_code == 200
    estimated = client.post(
        "/api/client/jobs/estimate",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert estimated.status_code == 200
    assert estimated.json()["estimated_points"] == 0
    assert estimated.json()["enough_credits"] is True


def test_client_rewrite_runs_directly_without_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("REWRITE_PROVIDER", "placeholder")
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    rewritten = client.post(
        "/api/client/rewrite",
        headers=_device_headers(token),
        json={
            "source_script": "大家好今天聊一聊做视频这件事先开始再慢慢优化",
            "style": "同款口播",
            "product_info": "",
            "target_audience": "",
            "max_chars": 300,
        },
    )

    assert rewritten.status_code == 200
    body = rewritten.json()
    assert body["mode"] == "direct_rewrite"
    assert body["operation"] == "rewrite"
    assert body["rewritten_script"]
    queue = client.get("/api/admin/queue", headers=_admin_headers()).json()
    assert queue["queued"] == 0
    assert queue["running"] == 0


def test_legacy_preprocess_rewrite_completes_directly_without_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("REWRITE_PROVIDER", "placeholder")
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    created = client.post(
        "/api/client/preprocess/jobs",
        headers=_device_headers(token),
        json={
            "payload": {
                "task_type": "preprocess",
                "operation": "rewrite",
                "source_script": "Hello 大家好 今天终于拍了第一条视频",
                "style": "同款口播",
                "max_chars": 300,
            }
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "completed"
    assert body["progress_percent"] == 100
    assert body["result"]["mode"] == "direct_rewrite"
    assert body["result"]["rewritten_script"]

    queue = client.get("/api/admin/queue", headers=_admin_headers()).json()
    assert queue["queued"] == 0
    assert queue["running"] == 0
    claimed = client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )
    assert claimed.status_code == 200
    assert claimed.json()["job"] is None


def test_email_code_rejects_wrong_code_and_then_accepts_valid_code(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token, _ = _activate_software(client)
    sent = client.post(
        "/api/client/auth/email-code",
        headers=_device_headers(token),
        json={"email": "user@example.com"},
    )
    assert sent.status_code == 200

    wrong = client.post(
        "/api/client/auth/login",
        headers=_device_headers(token),
        json={
            "email": "user@example.com",
            "code": "000000",
            "device_fingerprint": "device-1",
        },
    )
    assert wrong.status_code == 400

    ok = client.post(
        "/api/client/auth/login",
        headers=_device_headers(token),
        json={
            "email": "user@example.com",
            "code": sent.json()["debug_code"],
            "device_fingerprint": "device-1",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["device_token"]


def test_license_key_must_activate_software_before_any_account(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    first_token, first_body = _activate_software(
        client,
        license_key="LIC-ONE",
        fingerprint="device-1",
    )
    assert first_body["user"]["email"] is None

    second = client.post(
        "/api/client/activate",
        json={
            "license_key": "LIC-ONE",
            "device_fingerprint": "device-2",
            "device_name": "Windows client",
        },
    )
    assert second.status_code == 409
    assert "activation limit" in second.json()["detail"]

    token, bound = _bind_email(
        client,
        first_token,
        email="first@example.com",
        fingerprint="device-1",
    )
    assert bound["user"]["email"] == "first@example.com"
    assert token != first_token


def test_device_limit_and_admin_reset(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    activation_token, activated = _activate_software(
        client, license_key="LIC-DEVICE", fingerprint="device-1"
    )
    token, body = _bind_email(
        client,
        activation_token,
        email="device@example.com",
        fingerprint="device-1",
    )
    activation_user_id = activated["user"]["user_id"]
    account_user_id = body["user"]["user_id"]

    blocked = client.post(
        "/api/client/activate",
        json={
            "license_key": "LIC-DEVICE",
            "device_fingerprint": "device-2",
            "device_name": "Windows client",
        },
    )
    assert blocked.status_code == 409
    assert "activation limit" in blocked.json()["detail"]

    reset = client.post(
        f"/api/admin/users/{activation_user_id}/devices/reset",
        headers=_admin_headers(),
    )
    assert reset.status_code == 200
    account_reset = client.post(
        f"/api/admin/users/{account_user_id}/devices/reset",
        headers=_admin_headers(),
    )
    assert account_reset.status_code == 200

    reactivated = client.post(
        "/api/client/activate",
        json={
            "license_key": "LIC-DEVICE",
            "device_fingerprint": "device-2",
            "device_name": "Windows client",
        },
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["user"]["user_id"] == activation_user_id

    new_token = reactivated.json()["device_token"]
    _, rebound = _bind_email(
        client,
        new_token,
        email="device@example.com",
        fingerprint="device-2",
    )
    assert rebound["user"]["email"] == "device@example.com"

    revoked_activation = client.get(
        "/api/client/activation",
        headers={"X-Device-Token": activation_token},
    )
    assert revoked_activation.status_code == 401
    account_session = client.get("/api/client/me", headers=_device_headers(token))
    assert account_session.status_code == 401


def test_account_device_limit_applies_even_when_license_allows_more(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _activate_software(
        client,
        license_key="LIC-MULTI",
        fingerprint="device-1",
        max_activations=2,
    )

    blocked = client.post(
        "/api/client/activate",
        json={
            "license_key": "LIC-MULTI",
            "device_fingerprint": "device-2",
            "device_name": "Windows client",
        },
    )
    assert blocked.status_code == 409
    assert "device limit" in blocked.json()["detail"]


def test_admin_grants_usage_and_lists_user_by_email(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token, _ = _activate_software(client, license_key="LIC-PAID", fingerprint="device-1")
    account_token, body = _bind_email(
        client, token, email="paid@example.com", fingerprint="device-1"
    )
    user_id = body["user"]["user_id"]

    granted = client.post(
        f"/api/admin/users/{user_id}/usage",
        headers=_admin_headers(),
        json={"preset": "7d"},
    )
    assert granted.status_code == 200
    assert granted.json()["user"]["usage_access"]["remaining_days"] == 7

    detail = client.get(f"/api/admin/users/{user_id}", headers=_admin_headers())
    assert detail.status_code == 200
    assert detail.json()["wallet"]["available_points"] == 0
    assert detail.json()["ledger"] == []

    client_usage = client.get(
        "/api/client/usage",
        headers=_device_headers(account_token),
    )
    assert client_usage.status_code == 200
    assert client_usage.json()["usage_access"]["has_access"] is True

    listed = client.get(
        "/api/admin/users",
        headers=_admin_headers(),
        params={"email": "paid@example.com"},
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["user_id"] == user_id


def test_device_activation_survives_account_logout_and_switch(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    activation_token, _ = _activate_software(
        client,
        license_key="LIC-SWITCH",
        fingerprint="device-switch-1",
    )

    first_token, first = _bind_email(
        client,
        activation_token,
        email="first-switch@example.com",
        fingerprint="device-switch-1",
    )
    second_token, second = _bind_email(
        client,
        activation_token,
        email="second-switch@example.com",
        fingerprint="device-switch-1",
    )

    assert first_token != second_token
    assert first["user"]["user_id"] != second["user"]["user_id"]
    activation = client.get(
        "/api/client/activation",
        headers={"X-Device-Token": activation_token},
    )
    assert activation.status_code == 200
    assert activation.json()["activated"] is True

    second_ledger = client.get(
        "/api/client/credits/ledger",
        headers={
            "Authorization": f"Bearer {second_token}",
            "X-Device-Token": activation_token,
        },
    )
    assert second_ledger.status_code == 200


def test_password_registration_login_and_reset(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    activation_token, _ = _activate_software(
        client,
        license_key="LIC-PASSWORD",
        fingerprint="password-device-1",
    )
    activation_headers = {"X-Device-Token": activation_token}

    sent = client.post(
        "/api/client/auth/email-code",
        headers=activation_headers,
        json={"email": "password@example.com", "purpose": "register"},
    )
    assert sent.status_code == 200, sent.text
    registered = client.post(
        "/api/client/auth/register",
        headers=activation_headers,
        json={
            "email": "password@example.com",
            "code": sent.json()["debug_code"],
            "password": "initial-password-123",
            "device_name": "Windows client",
        },
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["device_token"]
    assert "password_hash" not in registered.json()["user"]

    duplicate_code = client.post(
        "/api/client/auth/email-code",
        headers=activation_headers,
        json={"email": "password@example.com", "purpose": "register"},
    )
    assert duplicate_code.status_code == 409

    wrong = client.post(
        "/api/client/auth/password-login",
        headers=activation_headers,
        json={
            "email": "password@example.com",
            "password": "wrong-password",
            "device_name": "Windows client",
        },
    )
    assert wrong.status_code == 401

    logged_in = client.post(
        "/api/client/auth/password-login",
        headers=activation_headers,
        json={
            "email": "password@example.com",
            "password": "initial-password-123",
            "device_name": "Windows client",
        },
    )
    assert logged_in.status_code == 200, logged_in.text

    reset_code = client.post(
        "/api/client/auth/email-code",
        headers=activation_headers,
        json={"email": "password@example.com", "purpose": "reset_password"},
    )
    assert reset_code.status_code == 200, reset_code.text
    reset = client.post(
        "/api/client/auth/password-reset",
        headers=activation_headers,
        json={
            "email": "password@example.com",
            "code": reset_code.json()["debug_code"],
            "new_password": "updated-password-456",
            "device_name": "Windows client",
        },
    )
    assert reset.status_code == 200, reset.text

    old_password = client.post(
        "/api/client/auth/password-login",
        headers=activation_headers,
        json={
            "email": "password@example.com",
            "password": "initial-password-123",
            "device_name": "Windows client",
        },
    )
    assert old_password.status_code == 401
    new_password = client.post(
        "/api/client/auth/password-login",
        headers=activation_headers,
        json={
            "email": "password@example.com",
            "password": "updated-password-456",
            "device_name": "Windows client",
        },
    )
    assert new_password.status_code == 200, new_password.text


def test_credit_codes_are_disabled(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    code = client.post(
        "/api/admin/credit-codes",
        headers=_admin_headers(),
        json={"code": "TOPUP-100", "points": 100},
    )
    assert code.status_code == 410

    redeemed = client.post(
        "/api/client/credits/redeem",
        headers=_device_headers(token),
        json={"code": "TOPUP-100"},
    )

    assert redeemed.status_code == 410


def test_client_job_uses_active_period_without_points(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    estimated = client.post(
        "/api/client/jobs/estimate",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p"},
    )
    assert estimated.status_code == 200
    assert estimated.json()["estimated_points"] == 0

    created = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p", "payload": {"script": "demo"}},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    assert created.json()["estimated_points"] == 0
    assert created.json()["hold_id"] is None

    after_hold = client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]
    assert after_hold["paid_balance"] == 0
    assert after_hold["frozen_paid"] == 0

    claimed = client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )
    assert claimed.status_code == 200
    assert claimed.json()["job"]["job_id"] == job_id

    completed = client.post(
        f"/api/worker/jobs/{job_id}/complete",
        headers=_worker_headers(),
        json={"worker_id": "worker-1", "result": {"output_cos_key": "outputs/demo.mp4"}},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    wallet = client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]
    assert wallet["paid_balance"] == 0
    assert wallet["frozen_paid"] == 0
    assert wallet["total_points"] == 0


def test_upload_session_submit_worker_urls_and_download_link(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    session = client.post(
        "/api/client/jobs/upload-session",
        headers=_device_headers(token),
        json={
            "assets": [
                {
                    "kind": "source_video",
                    "file_name": "source.mp4",
                    "content_type": "video/mp4",
                    "file_size_bytes": 1024,
                }
            ],
            "payload": {"script": "demo"},
        },
    )
    assert session.status_code == 200
    upload_job = session.json()
    assert upload_job["status"] == "uploading"
    assert upload_job["assets"][0]["upload"]["method"] == "PUT"
    assert upload_job["assets"][0]["upload"]["cos_key"].startswith("inputs/")
    put_input = client.request(
        upload_job["assets"][0]["upload"]["method"],
        upload_job["assets"][0]["upload"]["url"],
        headers=upload_job["assets"][0]["upload"]["headers"],
        content=b"source-video-bytes",
    )
    assert put_input.status_code == 200

    job_id = upload_job["job_id"]
    asset_id = upload_job["assets"][0]["asset_id"]
    uploaded = client.post(
        f"/api/client/jobs/{job_id}/assets/{asset_id}/uploaded",
        headers=_device_headers(token),
        json={"file_size_bytes": 2048},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["assets"][0]["status"] == "uploaded"

    submitted = client.post(
        f"/api/client/jobs/{job_id}/submit",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p", "payload": {"script": "demo"}},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "queued"
    assert submitted.json()["estimated_points"] == 0
    assert submitted.json()["hold_id"] is None

    claimed = client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )
    assert claimed.status_code == 200
    worker_job = claimed.json()["job"]
    assert worker_job["input_assets"][0]["download"]["method"] == "GET"
    assert worker_job["output_upload"]["method"] == "PUT"
    input_download = client.get(worker_job["input_assets"][0]["download"]["url"])
    assert input_download.status_code == 200
    assert input_download.content == b"source-video-bytes"
    output_key = worker_job["payload"]["output_cos_key"]
    assert output_key.startswith("outputs/")
    put_output = client.request(
        worker_job["output_upload"]["method"],
        worker_job["output_upload"]["url"],
        headers=worker_job["output_upload"]["headers"],
        content=b"rendered-mp4-bytes",
    )
    assert put_output.status_code == 200

    completed = client.post(
        f"/api/worker/jobs/{job_id}/complete",
        headers=_worker_headers(),
        json={"worker_id": "worker-1", "result": {"output_cos_key": output_key}},
    )
    assert completed.status_code == 200

    download = client.get(
        f"/api/client/jobs/{job_id}/download",
        headers=_device_headers(token),
    )
    assert download.status_code == 200
    assert download.json()["download"]["method"] == "GET"
    assert download.json()["download"]["cos_key"] == output_key
    assert "signature=" in download.json()["download"]["url"]
    output_download = client.get(download.json()["download"]["url"])
    assert output_download.status_code == 200
    assert output_download.content == b"rendered-mp4-bytes"


def test_download_confirmation_deletes_output_immediately(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    created = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    job_id = created.json()["job_id"]
    client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )
    completed = client.post(
        f"/api/worker/jobs/{job_id}/complete",
        headers=_worker_headers(),
        json={"worker_id": "worker-1", "result": {"output_cos_key": "outputs/demo.mp4"}},
    )
    assert completed.status_code == 200
    output_asset = next(asset for asset in completed.json()["assets"] if asset["kind"] == "output")

    confirmed = client.post(
        f"/api/client/jobs/{job_id}/download-confirmed",
        headers=_device_headers(token),
    )

    assert confirmed.status_code == 200
    confirmed_output = next(
        asset
        for asset in confirmed.json()["job"]["assets"]
        if asset["kind"] == "output"
    )
    assert confirmed_output["status"] == "deleted"
    assert confirmed_output["downloaded_at"]
    assert confirmed_output["deleted_at"]
    assert confirmed.json()["deleted_outputs"] == 1


def test_scheduler_deletes_expired_output_assets(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    created = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    job_id = created.json()["job_id"]
    client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )
    completed = client.post(
        f"/api/worker/jobs/{job_id}/complete",
        headers=_worker_headers(),
        json={"worker_id": "worker-1", "result": {"output_cos_key": "outputs/demo.mp4"}},
    )
    output_asset = next(asset for asset in completed.json()["assets"] if asset["kind"] == "output")

    import app.main as main_module
    import app.scheduler as scheduler_module

    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with main_module.store.connect() as db:
        db.execute(
            "UPDATE job_assets SET expires_at = ? WHERE asset_id = ?",
            (expired_at, output_asset["asset_id"]),
        )

    result = scheduler_module.run_once()

    assert result["expired_outputs_deleted"] == 1
    job = client.get(f"/api/client/jobs/{job_id}", headers=_device_headers(token)).json()
    deleted_output = next(asset for asset in job["assets"] if asset["kind"] == "output")
    assert deleted_output["status"] == "deleted"
    assert deleted_output["deleted_at"]


def test_client_can_have_only_one_queued_job(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    first = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )

    assert second.status_code == 409
    assert "queued job limit" in second.json()["detail"]


def test_worker_does_not_claim_second_running_job_for_same_user(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    first = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert first.status_code == 200
    first_job_id = first.json()["job_id"]
    first_claim = client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )
    assert first_claim.status_code == 200
    assert first_claim.json()["job"]["job_id"] == first_job_id

    second = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )
    assert second.status_code == 200
    second_job_id = second.json()["job_id"]

    blocked_claim = client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-2"},
    )
    assert blocked_claim.status_code == 200
    assert blocked_claim.json()["job"] is None

    completed = client.post(
        f"/api/worker/jobs/{first_job_id}/complete",
        headers=_worker_headers(),
        json={"worker_id": "worker-1", "result": {}},
    )
    assert completed.status_code == 200

    next_claim = client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-2"},
    )
    assert next_claim.status_code == 200
    assert next_claim.json()["job"]["job_id"] == second_job_id


def test_failed_job_keeps_zero_point_wallet(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    created = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p"},
    )
    job_id = created.json()["job_id"]
    client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )

    failed = client.post(
        f"/api/worker/jobs/{job_id}/fail",
        headers=_worker_headers(),
        json={"worker_id": "worker-1", "error_message": "render failed"},
    )

    assert failed.status_code == 200
    wallet = client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]
    assert wallet["paid_balance"] == 0
    assert wallet["frozen_points"] == 0


def test_cancel_jobs_does_not_change_zero_point_wallet(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    queued = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p"},
    )
    queued_job_id = queued.json()["job_id"]
    canceled_queued = client.post(
        f"/api/client/jobs/{queued_job_id}/cancel",
        headers=_device_headers(token),
    )
    assert canceled_queued.status_code == 200
    assert canceled_queued.json()["status"] == "canceled"
    assert client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]["total_points"] == 0

    running = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p"},
    )
    running_job_id = running.json()["job_id"]
    client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )

    canceled_running = client.post(
        f"/api/client/jobs/{running_job_id}/cancel",
        headers=_device_headers(token),
    )

    assert canceled_running.status_code == 200
    assert canceled_running.json()["status"] == "canceled"
    wallet = client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]
    assert wallet["total_points"] == 0
    assert wallet["frozen_points"] == 0


def test_unlimited_usage_is_not_capped_by_old_bonus_daily_limit(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    for index in range(3):
        created = client.post(
            "/api/client/jobs",
            headers=_device_headers(token),
            json={"duration_seconds": 600, "resolution": "1080p"},
        )
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        client.post(
            "/api/worker/claim-job",
            headers=_worker_headers(),
            json={"worker_id": f"worker-{index}"},
        )
        completed = client.post(
            f"/api/worker/jobs/{job_id}/complete",
            headers=_worker_headers(),
            json={"worker_id": f"worker-{index}", "result": {}},
        )
        assert completed.status_code == 200

    allowed = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 60, "resolution": "1080p"},
    )

    assert allowed.status_code == 200


def test_scheduler_timeout_keeps_zero_point_wallet(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)

    created = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p"},
    )
    job_id = created.json()["job_id"]
    client.post(
        "/api/worker/claim-job",
        headers=_worker_headers(),
        json={"worker_id": "worker-1"},
    )

    import app.main as main_module

    failed_jobs = main_module.store.fail_stale_running_jobs(timeout_seconds=0)

    assert [job["job_id"] for job in failed_jobs] == [job_id]
    assert failed_jobs[0]["status"] == "failed"
    wallet = client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]
    assert wallet["paid_balance"] == 0
    assert wallet["frozen_points"] == 0


def test_queued_job_times_out_after_24_hours_and_leaves_queue(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    token = _activate(client)
    created = client.post(
        "/api/client/jobs",
        headers=_device_headers(token),
        json={"duration_seconds": 600, "resolution": "1080p"},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    import app.main as main_module

    stale_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    with main_module.store.connect() as db:
        db.execute(
            "UPDATE render_jobs SET updated_at = ? WHERE job_id = ?",
            (stale_time, job_id),
        )

    timed_out = main_module.store.timeout_stale_queued_jobs(
        timeout_seconds=24 * 60 * 60,
    )
    assert [job["job_id"] for job in timed_out] == [job_id]
    assert timed_out[0]["status"] == "timed_out"
    assert main_module.store.queue_stats(worker_stale_seconds=600)["queued"] == 0
    wallet = client.get("/api/client/me", headers=_device_headers(token)).json()["wallet"]
    assert wallet["frozen_points"] == 0
