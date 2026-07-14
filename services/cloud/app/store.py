from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_password(password: str) -> str:
    value = password
    if len(value) < 8:
        raise ValueError("password must contain at least 8 characters")
    if len(value) > 128:
        raise ValueError("password must not exceed 128 characters")
    if not value.strip():
        raise ValueError("password must not be blank")
    return value


def hash_password(password: str) -> str:
    value = validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        value.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32
    )
    return "scrypt$16384$8$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def estimate_render_points(*, duration_seconds: int, resolution: str = "1080p") -> int:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if resolution != "1080p":
        raise ValueError("MVP only supports 1080p cloud render jobs")
    return max(1, math.ceil(duration_seconds / 60) * 3)


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError("invalid email")
    return value


class _EmptyCursor:
    rowcount = 0

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _PostgresConnection:
    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - only hit in misconfigured deployments
            raise RuntimeError(
                "DATABASE_URL requires installing psycopg[binary]"
            ) from exc
        self._connection = psycopg.connect(database_url, row_factory=dict_row)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        normalized = sql.strip().upper()
        if normalized.startswith("PRAGMA"):
            return _EmptyCursor()
        if normalized == "BEGIN IMMEDIATE":
            return self._connection.execute("SELECT pg_advisory_xact_lock(684202601)")
        translated = sql.replace("?", "%s")
        return self._connection.execute(translated, params)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


class QueueStore:
    def __init__(self, database_path: Path, *, database_url: str = "") -> None:
        self.database_path = database_path
        self.database_url = database_url.strip()
        self.backend = "postgresql" if self.database_url else "sqlite"
        if self.backend == "sqlite":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.backend == "postgresql":
            connection = _PostgresConnection(self.database_url)
        else:
            connection = sqlite3.connect(self.database_path, timeout=15)
            connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            rollback = getattr(connection, "rollback", None)
            if rollback is not None:
                rollback()
            raise
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS render_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    hold_id TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    job_type TEXT NOT NULL DEFAULT 'render',
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT,
                    estimated_points INTEGER NOT NULL DEFAULT 0,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    resolution TEXT NOT NULL DEFAULT '1080p',
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    worker_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_render_jobs_queue
                ON render_jobs(status, priority DESC, created_at ASC)
                """
            )
            self._ensure_columns(
                db,
                "render_jobs",
                {
                    "user_id": "TEXT",
                    "hold_id": "TEXT",
                    "estimated_points": "INTEGER NOT NULL DEFAULT 0",
                    "duration_seconds": "INTEGER NOT NULL DEFAULT 0",
                    "resolution": "TEXT NOT NULL DEFAULT '1080p'",
                    "cancel_requested_at": "TEXT",
                },
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT,
                    email_verified_at TEXT,
                    password_hash TEXT,
                    license_status TEXT NOT NULL DEFAULT 'inactive',
                    license_key TEXT,
                    license_activated_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                db,
                "users",
                {
                    "email": "TEXT",
                    "email_verified_at": "TEXT",
                    "password_hash": "TEXT",
                    "license_status": "TEXT NOT NULL DEFAULT 'inactive'",
                    "license_key": "TEXT",
                    "license_activated_at": "TEXT",
                },
            )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
                ON users(email)
                WHERE email IS NOT NULL
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    device_fingerprint TEXT NOT NULL,
                    device_name TEXT NOT NULL DEFAULT '',
                    access_token TEXT NOT NULL UNIQUE,
                    activated_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT,
                    UNIQUE(user_id, device_fingerprint)
                )
                """
            )
            self._ensure_columns(
                db,
                "devices",
                {
                    "revoked_at": "TEXT",
                },
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS license_keys (
                    license_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'active',
                    max_activations INTEGER NOT NULL DEFAULT 1,
                    grant_points INTEGER NOT NULL DEFAULT 3000,
                    assigned_user_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            self._ensure_columns(
                db,
                "license_keys",
                {
                    "grant_points": "INTEGER NOT NULL DEFAULT 3000",
                    "assigned_user_id": "TEXT",
                },
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS license_activations (
                    activation_id TEXT PRIMARY KEY,
                    license_key TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    UNIQUE(license_key, device_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS email_login_codes (
                    code_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    code TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_email_login_codes_email_status
                ON email_login_codes(email, status, sent_at DESC)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_codes (
                    code TEXT PRIMARY KEY,
                    points INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    redeemed_by_user_id TEXT,
                    redeemed_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_wallets (
                    user_id TEXT PRIMARY KEY,
                    bonus_balance INTEGER NOT NULL DEFAULT 0,
                    paid_balance INTEGER NOT NULL DEFAULT 0,
                    frozen_bonus INTEGER NOT NULL DEFAULT 0,
                    frozen_paid INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    ledger_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    points INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    job_id TEXT,
                    hold_id TEXT,
                    code TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_holds (
                    hold_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    job_id TEXT,
                    status TEXT NOT NULL,
                    bonus_points INTEGER NOT NULL DEFAULT 0,
                    paid_points INTEGER NOT NULL DEFAULT 0,
                    total_points INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    captured_at TEXT,
                    released_at TEXT,
                    reason TEXT NOT NULL DEFAULT ''
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS job_events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS job_assets (
                    asset_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    cos_key TEXT NOT NULL,
                    file_name TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT '',
                    file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    downloaded_at TEXT,
                    expires_at TEXT,
                    deleted_at TEXT
                )
                """
            )
            self._ensure_columns(
                db,
                "job_assets",
                {
                    "file_size_bytes": "INTEGER NOT NULL DEFAULT 0",
                    "uploaded_at": "TEXT",
                    "downloaded_at": "TEXT",
                    "expires_at": "TEXT",
                    "deleted_at": "TEXT",
                },
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_nodes (
                    worker_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    current_job_id TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    key TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    current_job_id TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS douyin_transcriptions (
                    transcription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    share_url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    transcript TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_douyin_transcriptions_user_created
                ON douyin_transcriptions(user_id, created_at DESC)
                """
            )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_douyin_transcriptions_user_active
                ON douyin_transcriptions(user_id)
                WHERE status IN ('queued', 'running')
                """
            )

    def _ensure_columns(
        self,
        db: Any,
        table: str,
        columns: dict[str, str],
    ) -> None:
        if self.backend == "postgresql":
            existing = {
                row["name"]
                for row in db.execute(
                    """
                    SELECT column_name AS name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = ?
                    """,
                    (table,),
                ).fetchall()
            }
        else:
            existing = {
                row["name"]
                for row in db.execute(f"PRAGMA table_info({table})").fetchall()
            }
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def create_license_key(
        self,
        *,
        license_key: str | None = None,
        max_activations: int = 1,
        grant_points: int = 3000,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        key = (license_key or secrets.token_urlsafe(12)).strip()
        if not key:
            raise ValueError("license_key is required")
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO license_keys (
                    license_key, status, max_activations, grant_points, created_at, expires_at
                )
                VALUES (?, 'active', ?, ?, ?, ?)
                """,
                (key, max_activations, grant_points, now, expires_at),
            )
            row = db.execute(
                "SELECT * FROM license_keys WHERE license_key = ?",
                (key,),
            ).fetchone()
        return dict(row)

    def update_license_key(
        self,
        *,
        license_key: str,
        expires_at: str | None,
    ) -> dict[str, Any]:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE license_keys SET expires_at = ? WHERE license_key = ?",
                (expires_at, license_key),
            )
            if cursor.rowcount == 0:
                raise KeyError(license_key)
            row = db.execute(
                "SELECT * FROM license_keys WHERE license_key = ?",
                (license_key,),
            ).fetchone()
        item = dict(row)
        item["effective_status"] = self._license_effective_status(item)
        return item

    @staticmethod
    def _license_effective_status(item: dict[str, Any]) -> str:
        if item["status"] != "active":
            return str(item["status"])
        expires_at = parse_time(item.get("expires_at"))
        if expires_at and expires_at <= datetime.now(timezone.utc):
            return "expired"
        return "active"

    def create_credit_code(self, *, code: str | None = None, points: int) -> dict[str, Any]:
        if points <= 0:
            raise ValueError("points must be positive")
        value = (code or secrets.token_urlsafe(10)).strip()
        if not value:
            raise ValueError("code is required")
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO credit_codes (code, points, status, created_at)
                VALUES (?, ?, 'active', ?)
                """,
                (value, points, now),
            )
            row = db.execute("SELECT * FROM credit_codes WHERE code = ?", (value,)).fetchone()
        return dict(row)

    def activate_license(
        self,
        *,
        license_key: str,
        device_fingerprint: str,
        device_name: str = "",
        max_devices_per_user: int = 1,
    ) -> dict[str, Any]:
        now = utc_now()
        key = license_key.strip()
        fingerprint = device_fingerprint.strip()
        if not key or not fingerprint:
            raise ValueError("license_key and device_fingerprint are required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            license_row = db.execute(
                "SELECT * FROM license_keys WHERE license_key = ?",
                (key,),
            ).fetchone()
            if license_row is None or license_row["status"] != "active":
                raise KeyError("license_key")
            if license_row["expires_at"]:
                expires_at = parse_time(license_row["expires_at"])
                if expires_at and expires_at < datetime.now(timezone.utc):
                    raise KeyError("license_key")

            existing_device = db.execute(
                """
                SELECT d.* FROM devices d
                JOIN license_activations a ON a.device_id = d.device_id
                WHERE a.license_key = ? AND d.device_fingerprint = ?
                  AND d.revoked_at IS NULL
                """,
                (key, fingerprint),
            ).fetchone()
            if existing_device is not None:
                db.execute(
                    "UPDATE devices SET last_seen_at = ?, device_name = ? WHERE device_id = ?",
                    (now, device_name[:120], existing_device["device_id"]),
                )
                user_id = existing_device["user_id"]
                db.execute(
                    """
                    UPDATE users
                    SET license_status = 'active',
                        license_key = COALESCE(license_key, ?),
                        license_activated_at = COALESCE(license_activated_at, ?),
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (key, now, now, user_id),
                )
                device_id = existing_device["device_id"]
                access_token = existing_device["access_token"]
                wallet = self._wallet_for_user(db, user_id)
                return {
                    "user": self._user_for_id(db, user_id),
                    "device": self._device_for_id(db, device_id),
                    "device_token": access_token,
                    "wallet": wallet,
                    "license_key": key,
                }

            activation_rows = db.execute(
                """
                SELECT * FROM license_activations
                WHERE license_key = ?
                ORDER BY activated_at ASC
                """,
                (key,),
            ).fetchall()
            active_activation_rows = db.execute(
                """
                SELECT a.* FROM license_activations a
                JOIN devices d ON d.device_id = a.device_id
                WHERE a.license_key = ?
                  AND d.revoked_at IS NULL
                ORDER BY a.activated_at ASC
                """,
                (key,),
            ).fetchall()
            if len(active_activation_rows) >= int(license_row["max_activations"]):
                raise PermissionError("license activation limit reached")

            assigned_user_id = license_row["assigned_user_id"]
            if activation_rows:
                user_id = activation_rows[0]["user_id"]
            elif assigned_user_id:
                user_id = assigned_user_id
                assigned_user = self._user_for_id(db, user_id)
                if assigned_user["status"] != "active":
                    raise PermissionError("user account is disabled")
            else:
                user_id = str(uuid4())
                db.execute(
                    """
                    INSERT INTO users (
                        user_id, license_status, license_key, license_activated_at,
                        status, created_at, updated_at
                    )
                    VALUES (?, 'active', ?, ?, 'active', ?, ?)
                    """,
                    (user_id, key, now, now, now),
                )
                db.execute(
                    """
                    INSERT INTO credit_wallets (
                        user_id, bonus_balance, paid_balance, frozen_bonus, frozen_paid, updated_at
                    )
                    VALUES (?, 0, 0, 0, 0, ?)
                    """,
                    (user_id, now),
                )
            if activation_rows or assigned_user_id:
                db.execute(
                    """
                    UPDATE users
                    SET license_status = 'active',
                        license_key = COALESCE(license_key, ?),
                        license_activated_at = COALESCE(license_activated_at, ?),
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (key, now, now, user_id),
                )

            active_device_count = db.execute(
                """
                SELECT COUNT(*) AS count FROM devices
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (user_id,),
            ).fetchone()["count"]
            if active_device_count >= max(1, max_devices_per_user):
                raise PermissionError("device limit reached; ask admin to reset device binding")

            device_id = str(uuid4())
            access_token = secrets.token_urlsafe(32)
            db.execute(
                """
                INSERT INTO devices (
                    device_id, user_id, device_fingerprint, device_name,
                    access_token, activated_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (device_id, user_id, fingerprint, device_name[:120], access_token, now, now),
            )
            db.execute(
                """
                INSERT INTO license_activations (
                    activation_id, license_key, user_id, device_id, activated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid4()), key, user_id, device_id, now),
            )

            return {
                "user": self._user_for_id(db, user_id),
                "device": self._device_for_id(db, device_id),
                "device_token": access_token,
                "wallet": self._wallet_for_user(db, user_id),
                "license_key": key,
            }

    def create_email_login_code(
        self,
        *,
        email: str,
        code: str,
        ttl_seconds: int,
        resend_seconds: int,
    ) -> dict[str, Any]:
        address = normalize_email(email)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(seconds=max(60, ttl_seconds))).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                """
                SELECT * FROM email_login_codes
                WHERE email = ? AND status = 'active'
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            if latest is not None:
                sent_at = parse_time(latest["sent_at"])
                latest_expires_at = parse_time(latest["expires_at"])
                if latest_expires_at and latest_expires_at <= now_dt:
                    db.execute(
                        "UPDATE email_login_codes SET status = 'expired' WHERE code_id = ?",
                        (latest["code_id"],),
                    )
                elif sent_at and (now_dt - sent_at).total_seconds() < resend_seconds:
                    elapsed = int((now_dt - sent_at).total_seconds())
                    remaining = max(1, resend_seconds - elapsed)
                    raise RuntimeError(f"请等待 {remaining} 秒后重新发送验证码")
                else:
                    db.execute(
                        "UPDATE email_login_codes SET status = 'superseded' WHERE code_id = ?",
                        (latest["code_id"],),
                    )
            code_id = str(uuid4())
            db.execute(
                """
                INSERT INTO email_login_codes (
                    code_id, email, code, status, attempts, created_at, sent_at, expires_at
                )
                VALUES (?, ?, ?, 'active', 0, ?, ?, ?)
                """,
                (code_id, address, code, now, now, expires_at),
            )
            row = db.execute(
                "SELECT * FROM email_login_codes WHERE code_id = ?",
                (code_id,),
            ).fetchone()
        item = dict(row)
        item.pop("code", None)
        return item

    def email_account_has_password(self, *, email: str) -> bool:
        address = normalize_email(email)
        with self.connect() as db:
            row = db.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                (address,),
            ).fetchone()
        return bool(row and row["password_hash"])

    def set_user_password(self, *, user_id: str, password: str) -> dict[str, Any]:
        encoded = hash_password(password)
        now = utc_now()
        with self.connect() as db:
            self._user_for_id(db, user_id)
            db.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (encoded, now, user_id),
            )
            return self._user_for_id(db, user_id)

    def login_with_password(
        self,
        *,
        email: str,
        password: str,
        device_fingerprint: str,
        device_name: str,
        max_devices: int,
        replace_device_prefix: str = "",
    ) -> dict[str, Any]:
        address = normalize_email(email)
        fingerprint = device_fingerprint.strip()
        if not password or not fingerprint:
            raise ValueError("password and device_fingerprint are required")
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute(
                "SELECT * FROM users WHERE email = ?",
                (address,),
            ).fetchone()
            if user is None or not verify_password(password, user["password_hash"]):
                raise KeyError("credentials")
            if user["status"] != "active":
                raise PermissionError("user account is disabled")

            replacement_prefix = replace_device_prefix.strip()
            if replacement_prefix and fingerprint.startswith(replacement_prefix):
                db.execute(
                    """
                    UPDATE devices
                    SET revoked_at = ?
                    WHERE user_id = ?
                      AND revoked_at IS NULL
                      AND device_fingerprint != ?
                      AND device_fingerprint LIKE ?
                    """,
                    (
                        now,
                        user["user_id"],
                        fingerprint,
                        f"{replacement_prefix}%",
                    ),
                )

            existing_device = db.execute(
                """
                SELECT * FROM devices
                WHERE user_id = ? AND device_fingerprint = ?
                """,
                (user["user_id"], fingerprint),
            ).fetchone()
            active_other_devices = db.execute(
                """
                SELECT COUNT(*) AS count FROM devices
                WHERE user_id = ?
                  AND revoked_at IS NULL
                  AND device_fingerprint != ?
                """,
                (user["user_id"], fingerprint),
            ).fetchone()["count"]
            if (
                (existing_device is None or existing_device["revoked_at"] is not None)
                and int(active_other_devices) >= max_devices
            ):
                raise PermissionError("device limit reached")

            device_id = existing_device["device_id"] if existing_device else str(uuid4())
            access_token = secrets.token_urlsafe(32)
            if existing_device is None:
                db.execute(
                    """
                    INSERT INTO devices (
                        device_id, user_id, device_fingerprint, device_name,
                        access_token, activated_at, last_seen_at, revoked_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        device_id,
                        user["user_id"],
                        fingerprint,
                        device_name[:120],
                        access_token,
                        now,
                        now,
                    ),
                )
            else:
                db.execute(
                    """
                    UPDATE devices
                    SET device_name = ?,
                        access_token = ?,
                        last_seen_at = ?,
                        revoked_at = NULL
                    WHERE device_id = ?
                    """,
                    (device_name[:120], access_token, now, device_id),
                )
            return {
                "user": self._user_for_id(db, user["user_id"]),
                "device": self._device_for_id(db, device_id),
                "device_token": access_token,
                "wallet": self._wallet_for_user(db, user["user_id"]),
            }

    def login_with_email_code(
        self,
        *,
        email: str,
        code: str,
        device_fingerprint: str,
        device_name: str,
        max_attempts: int,
        max_devices: int,
        replace_device_prefix: str = "",
    ) -> dict[str, Any]:
        address = normalize_email(email)
        value = code.strip()
        fingerprint = device_fingerprint.strip()
        if not value or not fingerprint:
            raise ValueError("email code and device_fingerprint are required")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            code_row = db.execute(
                """
                SELECT * FROM email_login_codes
                WHERE email = ? AND status = 'active'
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            if code_row is None:
                raise KeyError("email_code")
            expires_at = parse_time(code_row["expires_at"])
            if expires_at and expires_at < now_dt:
                db.execute(
                    "UPDATE email_login_codes SET status = 'expired' WHERE code_id = ?",
                    (code_row["code_id"],),
                )
                raise KeyError("email_code")
            if int(code_row["attempts"]) >= max_attempts:
                db.execute(
                    "UPDATE email_login_codes SET status = 'locked' WHERE code_id = ?",
                    (code_row["code_id"],),
                )
                raise PermissionError("email code attempt limit reached")
            if str(code_row["code"]) != value:
                attempts = int(code_row["attempts"]) + 1
                status = "locked" if attempts >= max_attempts else "active"
                db.execute(
                    """
                    UPDATE email_login_codes
                    SET attempts = ?, status = ?
                    WHERE code_id = ?
                    """,
                    (attempts, status, code_row["code_id"]),
                )
                raise KeyError("email_code")
            db.execute(
                """
                UPDATE email_login_codes
                SET status = 'consumed',
                    consumed_at = ?
                WHERE code_id = ?
                """,
                (now, code_row["code_id"]),
            )

            user = db.execute("SELECT * FROM users WHERE email = ?", (address,)).fetchone()
            if user is None:
                user_id = str(uuid4())
                db.execute(
                    """
                    INSERT INTO users (
                        user_id, email, email_verified_at, license_status,
                        status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'inactive', 'active', ?, ?)
                    """,
                    (user_id, address, now, now, now),
                )
                db.execute(
                    """
                    INSERT INTO credit_wallets (
                        user_id, bonus_balance, paid_balance, frozen_bonus, frozen_paid, updated_at
                    )
                    VALUES (?, 0, 0, 0, 0, ?)
                    """,
                    (user_id, now),
                )
                user = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            else:
                user_id = user["user_id"]
                db.execute(
                    """
                    UPDATE users
                    SET email_verified_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now, now, user_id),
                )
                user = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if user["status"] != "active":
                raise PermissionError("user account is disabled")

            replacement_prefix = replace_device_prefix.strip()
            if replacement_prefix and fingerprint.startswith(replacement_prefix):
                db.execute(
                    """
                    UPDATE devices
                    SET revoked_at = ?
                    WHERE user_id = ?
                      AND revoked_at IS NULL
                      AND device_fingerprint != ?
                      AND device_fingerprint LIKE ?
                    """,
                    (
                        now,
                        user["user_id"],
                        fingerprint,
                        f"{replacement_prefix}%",
                    ),
                )

            existing_device = db.execute(
                """
                SELECT * FROM devices
                WHERE user_id = ? AND device_fingerprint = ?
                """,
                (user["user_id"], fingerprint),
            ).fetchone()
            active_other_devices = db.execute(
                """
                SELECT COUNT(*) AS count FROM devices
                WHERE user_id = ?
                  AND revoked_at IS NULL
                  AND device_fingerprint != ?
                """,
                (user["user_id"], fingerprint),
            ).fetchone()["count"]
            if (
                (existing_device is None or existing_device["revoked_at"] is not None)
                and int(active_other_devices) >= max_devices
            ):
                raise PermissionError("device limit reached")
            device_id = existing_device["device_id"] if existing_device else str(uuid4())
            access_token = secrets.token_urlsafe(32)
            if existing_device is None:
                db.execute(
                    """
                    INSERT INTO devices (
                        device_id, user_id, device_fingerprint, device_name,
                        access_token, activated_at, last_seen_at, revoked_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        device_id,
                        user["user_id"],
                        fingerprint,
                        device_name[:120],
                        access_token,
                        now,
                        now,
                    ),
                )
            else:
                db.execute(
                    """
                    UPDATE devices
                    SET device_name = ?,
                        access_token = ?,
                        last_seen_at = ?,
                        revoked_at = NULL
                    WHERE device_id = ?
                    """,
                    (device_name[:120], access_token, now, device_id),
                )
            return {
                "user": self._user_for_id(db, user["user_id"]),
                "device": self._device_for_id(db, device_id),
                "device_token": access_token,
                "wallet": self._wallet_for_user(db, user["user_id"]),
            }

    def ensure_mobile_access(
        self,
        *,
        user_id: str,
        device_id: str,
        max_activations: int,
    ) -> dict[str, Any]:
        """Provision internal cloud access for a registered mobile device.

        Mobile users never receive this internal license key.  Keeping the
        activation record server-side lets the existing cloud-job authorization
        continue to require both a valid account session and an approved device,
        without exposing an activation-code step in the Android client.
        """

        now = utc_now()
        activation_limit = max(1, int(max_activations))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = self._user_for_id(db, user_id)
            device = db.execute(
                "SELECT * FROM devices WHERE device_id = ? AND user_id = ? AND revoked_at IS NULL",
                (device_id, user_id),
            ).fetchone()
            if device is None:
                raise KeyError(device_id)
            if user["status"] != "active":
                raise PermissionError("user account is disabled")

            license_row = db.execute(
                """
                SELECT * FROM license_keys
                WHERE assigned_user_id = ? AND substr(license_key, 1, 7) = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (user_id, "mobile_"),
            ).fetchone()
            if license_row is None:
                license_key = f"mobile_{secrets.token_urlsafe(24)}"
                db.execute(
                    """
                    INSERT INTO license_keys (
                        license_key, status, max_activations, grant_points,
                        assigned_user_id, created_at
                    )
                    VALUES (?, 'active', ?, 0, ?, ?)
                    """,
                    (license_key, activation_limit, user_id, now),
                )
            else:
                if license_row["status"] != "active":
                    raise PermissionError("mobile access is disabled")
                license_key = str(license_row["license_key"])
                if int(license_row["max_activations"]) < activation_limit:
                    db.execute(
                        "UPDATE license_keys SET max_activations = ? WHERE license_key = ?",
                        (activation_limit, license_key),
                    )

            existing = db.execute(
                """
                SELECT activation_id FROM license_activations
                WHERE license_key = ? AND device_id = ?
                """,
                (license_key, device_id),
            ).fetchone()
            if existing is None:
                active_count = db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM license_activations a
                    JOIN devices d ON d.device_id = a.device_id
                    WHERE a.license_key = ? AND d.revoked_at IS NULL
                    """,
                    (license_key,),
                ).fetchone()["count"]
                if int(active_count) >= activation_limit:
                    raise PermissionError("mobile device limit reached")
                db.execute(
                    """
                    INSERT INTO license_activations (
                        activation_id, license_key, user_id, device_id, activated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (str(uuid4()), license_key, user_id, device_id, now),
                )

            return {
                "activated": True,
                "device": self._device_for_id(db, device_id),
                "activated_at": now,
            }

    def activate_user_license(
        self,
        *,
        user_id: str,
        device_id: str,
        license_key: str,
    ) -> dict[str, Any]:
        key = license_key.strip()
        if not key:
            raise ValueError("license_key is required")
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = self._user_for_id(db, user_id)
            if user["status"] != "active":
                raise PermissionError("user account is disabled")
            license_row = db.execute(
                "SELECT * FROM license_keys WHERE license_key = ?",
                (key,),
            ).fetchone()
            if license_row is None or license_row["status"] != "active":
                raise KeyError("license_key")
            if license_row["expires_at"]:
                expires_at = parse_time(license_row["expires_at"])
                if expires_at and expires_at < datetime.now(timezone.utc):
                    raise KeyError("license_key")
            existing = db.execute(
                """
                SELECT * FROM license_activations
                WHERE license_key = ?
                ORDER BY activated_at ASC
                """,
                (key,),
            ).fetchall()
            existing_user_ids = {row["user_id"] for row in existing}
            if existing_user_ids and existing_user_ids != {user_id}:
                raise PermissionError("license key is already bound to another account")
            if (
                user["license_status"] == "active"
                and user["license_key"]
                and user["license_key"] != key
            ):
                raise PermissionError("user account already has an active license")
            if not existing:
                db.execute(
                    """
                    INSERT INTO license_activations (
                        activation_id, license_key, user_id, device_id, activated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (str(uuid4()), key, user_id, device_id, now),
                )
            db.execute(
                """
                UPDATE users
                SET license_status = 'active',
                    license_key = ?,
                    license_activated_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (key, now, now, user_id),
            )
            return {
                "user": self._user_for_id(db, user_id),
                "device": self._device_for_id(db, device_id),
                "wallet": self._wallet_for_user(db, user_id),
                "license_key": key,
            }

    def bind_email_with_code(
        self,
        *,
        user_id: str,
        device_id: str,
        device_token: str,
        email: str,
        code: str,
        max_attempts: int,
    ) -> dict[str, Any]:
        address = normalize_email(email)
        value = code.strip()
        if not value:
            raise ValueError("email code is required")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = self._user_for_id(db, user_id)
            if user["status"] != "active":
                raise PermissionError("user account is disabled")
            if user["license_status"] != "active":
                raise PermissionError("software is not activated")
            code_row = db.execute(
                """
                SELECT * FROM email_login_codes
                WHERE email = ? AND status = 'active'
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            if code_row is None:
                raise KeyError("email_code")
            expires_at = parse_time(code_row["expires_at"])
            if expires_at and expires_at < now_dt:
                db.execute(
                    "UPDATE email_login_codes SET status = 'expired' WHERE code_id = ?",
                    (code_row["code_id"],),
                )
                raise KeyError("email_code")
            if int(code_row["attempts"]) >= max_attempts:
                db.execute(
                    "UPDATE email_login_codes SET status = 'locked' WHERE code_id = ?",
                    (code_row["code_id"],),
                )
                raise PermissionError("email code attempt limit reached")
            if str(code_row["code"]) != value:
                attempts = int(code_row["attempts"]) + 1
                status = "locked" if attempts >= max_attempts else "active"
                db.execute(
                    """
                    UPDATE email_login_codes
                    SET attempts = ?, status = ?
                    WHERE code_id = ?
                    """,
                    (attempts, status, code_row["code_id"]),
                )
                raise KeyError("email_code")
            existing = db.execute(
                "SELECT * FROM users WHERE email = ? AND user_id != ?",
                (address, user_id),
            ).fetchone()
            if existing is not None:
                raise PermissionError("email is already bound to another account")
            db.execute(
                """
                UPDATE email_login_codes
                SET status = 'consumed',
                    consumed_at = ?
                WHERE code_id = ?
                """,
                (now, code_row["code_id"]),
            )
            db.execute(
                """
                UPDATE users
                SET email = ?,
                    email_verified_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (address, now, now, user_id),
            )
            return {
                "user": self._user_for_id(db, user_id),
                "device": self._device_for_id(db, device_id),
                "device_token": device_token,
                "wallet": self._wallet_for_user(db, user_id),
            }

    def get_device_session(self, *, access_token: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM devices WHERE access_token = ? AND revoked_at IS NULL",
                (access_token,),
            ).fetchone()
            if row is None:
                raise KeyError("device")
            user = self._user_for_id(db, row["user_id"])
            if user["status"] != "active":
                raise PermissionError("user account is disabled")
            db.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (now, row["device_id"]),
            )
            return {
                "user": user,
                "device": self._device_for_id(db, row["device_id"]),
                "wallet": self._wallet_for_user(db, row["user_id"]),
            }

    def get_device_activation(self, *, access_token: str) -> dict[str, Any]:
        """Resolve software activation by physical device fingerprint.

        Account sessions may change, but any active session created on the same
        physical device inherits that device's software activation.
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self.connect() as db:
            current_device = db.execute(
                "SELECT * FROM devices WHERE access_token = ? AND revoked_at IS NULL",
                (access_token,),
            ).fetchone()
            if current_device is None:
                raise KeyError("device")
            activation = db.execute(
                """
                SELECT a.activation_id,
                       a.license_key,
                       a.activated_at AS license_activated_at,
                       d.device_id AS activated_device_id,
                       l.status AS license_status,
                       l.expires_at AS license_expires_at
                FROM license_activations a
                JOIN devices d ON d.device_id = a.device_id
                JOIN license_keys l ON l.license_key = a.license_key
                WHERE d.device_fingerprint = ?
                  AND d.revoked_at IS NULL
                ORDER BY a.activated_at DESC
                LIMIT 1
                """,
                (current_device["device_fingerprint"],),
            ).fetchone()
            if activation is None or activation["license_status"] != "active":
                raise PermissionError("software is not activated on this device")
            expires_at = parse_time(activation["license_expires_at"])
            if expires_at and expires_at < now_dt:
                raise PermissionError("software activation has expired")
            db.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (now, current_device["device_id"]),
            )
            return {
                "activated": True,
                "device": self._device_for_id(db, current_device["device_id"]),
                "activated_at": activation["license_activated_at"],
            }

    def get_wallet(self, *, user_id: str) -> dict[str, Any]:
        with self.connect() as db:
            return self._wallet_for_user(db, user_id)

    def redeem_credit_code(self, *, user_id: str, code: str) -> dict[str, Any]:
        now = utc_now()
        value = code.strip()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM credit_codes WHERE code = ?",
                (value,),
            ).fetchone()
            if row is None or row["status"] != "active":
                raise KeyError("credit_code")
            db.execute(
                """
                UPDATE credit_codes
                SET status = 'redeemed',
                    redeemed_by_user_id = ?,
                    redeemed_at = ?
                WHERE code = ? AND status = 'active'
                """,
                (user_id, now, value),
            )
            db.execute(
                """
                UPDATE credit_wallets
                SET paid_balance = paid_balance + ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (int(row["points"]), now, user_id),
            )
            self._insert_ledger(
                db,
                user_id=user_id,
                event_type="credit_redeem",
                points=int(row["points"]),
                source="paid",
                code=value,
                note="credit code redeemed",
            )
            return {
                "code": value,
                "points": int(row["points"]),
                "wallet": self._wallet_for_user(db, user_id),
            }

    def create_upload_session(
        self,
        *,
        user_id: str,
        assets: list[dict[str, Any]],
        payload: dict[str, Any] | None = None,
        job_type: str = "render",
    ) -> dict[str, Any]:
        if not assets:
            raise ValueError("at least one asset is required")
        job_id = str(uuid4())
        now = utc_now()
        clean_assets: list[dict[str, Any]] = []
        for raw_asset in assets:
            asset_id = str(uuid4())
            file_name = self._safe_file_name(str(raw_asset.get("file_name") or "asset"))
            kind = str(raw_asset.get("kind") or "source_video").strip()
            if not kind:
                raise ValueError("asset kind is required")
            cos_key = f"inputs/{user_id}/{job_id}/{asset_id}/{file_name}"
            clean_assets.append(
                {
                    "asset_id": asset_id,
                    "job_id": job_id,
                    "user_id": user_id,
                    "kind": kind,
                    "cos_key": cos_key,
                    "file_name": file_name,
                    "content_type": str(raw_asset.get("content_type") or "application/octet-stream"),
                    "file_size_bytes": max(0, int(raw_asset.get("file_size_bytes") or 0)),
                    "status": "pending",
                }
            )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO render_jobs (
                    job_id, user_id, status, priority, job_type, payload_json,
                    created_at, updated_at, progress_message
                )
                VALUES (?, ?, 'uploading', 0, ?, ?, ?, ?, 'Waiting for cloud uploads')
                """,
                (job_id, user_id, job_type, json.dumps(payload or {}, ensure_ascii=False), now, now),
            )
            for asset in clean_assets:
                db.execute(
                    """
                    INSERT INTO job_assets (
                        asset_id, job_id, user_id, kind, cos_key, file_name,
                        content_type, file_size_bytes, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset["asset_id"],
                        asset["job_id"],
                        asset["user_id"],
                        asset["kind"],
                        asset["cos_key"],
                        asset["file_name"],
                        asset["content_type"],
                        asset["file_size_bytes"],
                        asset["status"],
                        now,
                        now,
                    ),
                )
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="upload_session_created",
                message=f"created {len(clean_assets)} upload assets",
            )
        return self.get_job_with_assets(job_id)

    def mark_asset_uploaded(
        self,
        *,
        user_id: str,
        job_id: str,
        asset_id: str,
        file_size_bytes: int = 0,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE job_assets
                SET status = 'uploaded',
                    file_size_bytes = CASE WHEN ? > 0 THEN ? ELSE file_size_bytes END,
                    updated_at = ?,
                    uploaded_at = ?
                WHERE user_id = ? AND job_id = ? AND asset_id = ?
                """,
                (file_size_bytes, file_size_bytes, now, now, user_id, job_id, asset_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(asset_id)
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="asset_uploaded",
                message=asset_id,
            )
        return self.get_job_with_assets(job_id)

    def submit_uploaded_job(
        self,
        *,
        job_id: str,
        user_id: str,
        payload: dict[str, Any],
        duration_seconds: int,
        resolution: str,
        max_duration_seconds: int,
        daily_bonus_limit: int,
        priority: int = 0,
    ) -> dict[str, Any]:
        if duration_seconds <= 0 or duration_seconds > max_duration_seconds:
            raise ValueError("duration_seconds exceeds MVP limit")
        points = estimate_render_points(
            duration_seconds=duration_seconds,
            resolution=resolution,
        )
        hold_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                """
                SELECT * FROM render_jobs
                WHERE job_id = ? AND user_id = ? AND status = 'uploading'
                """,
                (job_id, user_id),
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            queued = db.execute(
                """
                SELECT COUNT(*) AS count FROM render_jobs
                WHERE user_id = ? AND status = 'queued'
                """,
                (user_id,),
            ).fetchone()["count"]
            if queued >= 1:
                raise RuntimeError("queued job limit reached")
            pending_assets = db.execute(
                """
                SELECT COUNT(*) AS count FROM job_assets
                WHERE user_id = ? AND job_id = ? AND status != 'uploaded'
                """,
                (user_id, job_id),
            ).fetchone()["count"]
            if pending_assets:
                raise RuntimeError("assets are not uploaded")
            assets = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM job_assets WHERE user_id = ? AND job_id = ? ORDER BY created_at ASC",
                    (user_id, job_id),
                ).fetchall()
            ]
            wallet = self._wallet_for_user(db, user_id)
            daily_bonus_available = max(
                0,
                daily_bonus_limit - self._bonus_reserved_today(db, user_id=user_id),
            )
            bonus_points = min(int(wallet["bonus_balance"]), daily_bonus_available, points)
            paid_points = points - bonus_points
            if int(wallet["paid_balance"]) < paid_points:
                raise ValueError("insufficient credits")
            db.execute(
                """
                UPDATE credit_wallets
                SET bonus_balance = bonus_balance - ?,
                    paid_balance = paid_balance - ?,
                    frozen_bonus = frozen_bonus + ?,
                    frozen_paid = frozen_paid + ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (bonus_points, paid_points, bonus_points, paid_points, now, user_id),
            )
            db.execute(
                """
                INSERT INTO credit_holds (
                    hold_id, user_id, job_id, status, bonus_points, paid_points,
                    total_points, created_at, updated_at, reason
                )
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, 'render_job_hold')
                """,
                (hold_id, user_id, job_id, bonus_points, paid_points, points, now, now),
            )
            if bonus_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="hold",
                    points=-bonus_points,
                    source="bonus",
                    job_id=job_id,
                    hold_id=hold_id,
                    note="render job hold",
                )
            if paid_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="hold",
                    points=-paid_points,
                    source="paid",
                    job_id=job_id,
                    hold_id=hold_id,
                    note="render job hold",
                )
            queued_payload = dict(payload)
            queued_payload.update(
                {
                    "duration_seconds": duration_seconds,
                    "resolution": resolution,
                    "estimated_points": points,
                    "input_assets": assets,
                }
            )
            db.execute(
                """
                UPDATE render_jobs
                SET status = 'queued',
                    hold_id = ?,
                    priority = ?,
                    payload_json = ?,
                    estimated_points = ?,
                    duration_seconds = ?,
                    resolution = ?,
                    updated_at = ?,
                    progress_message = 'Queued'
                WHERE job_id = ? AND user_id = ? AND status = 'uploading'
                """,
                (
                    hold_id,
                    priority,
                    json.dumps(queued_payload, ensure_ascii=False),
                    points,
                    duration_seconds,
                    resolution,
                    now,
                    job_id,
                    user_id,
                ),
            )
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="queued",
                message=f"held {points} credits",
            )
        return self.get_job_with_assets(job_id)

    def submit_uploaded_preprocess_job(
        self,
        *,
        job_id: str,
        user_id: str,
        payload: dict[str, Any],
        priority: int = 0,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                """
                SELECT * FROM render_jobs
                WHERE job_id = ? AND user_id = ? AND status = 'uploading'
                """,
                (job_id, user_id),
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            pending_assets = db.execute(
                """
                SELECT COUNT(*) AS count FROM job_assets
                WHERE user_id = ? AND job_id = ? AND status != 'uploaded'
                """,
                (user_id, job_id),
            ).fetchone()["count"]
            if pending_assets:
                raise RuntimeError("assets are not uploaded")
            assets = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM job_assets WHERE user_id = ? AND job_id = ? ORDER BY created_at ASC",
                    (user_id, job_id),
                ).fetchall()
            ]
            queued_payload = dict(payload)
            queued_payload.update({"input_assets": assets})
            db.execute(
                """
                UPDATE render_jobs
                SET status = 'queued',
                    priority = ?,
                    payload_json = ?,
                    estimated_points = 0,
                    duration_seconds = 0,
                    updated_at = ?,
                    progress_message = 'Queued'
                WHERE job_id = ? AND user_id = ? AND status = 'uploading'
                """,
                (
                    priority,
                    json.dumps(queued_payload, ensure_ascii=False),
                    now,
                    job_id,
                    user_id,
                ),
            )
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="queued",
                message="queued preprocess job",
            )
        return self.get_job_with_assets(job_id)

    def create_client_preprocess_job(
        self,
        *,
        user_id: str,
        payload: dict[str, Any],
        priority: int = 0,
    ) -> dict[str, Any]:
        job_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO render_jobs (
                    job_id, user_id, status, priority, job_type, payload_json,
                    estimated_points, duration_seconds, created_at, updated_at, progress_message
                )
                VALUES (?, ?, 'queued', ?, 'preprocess', ?, 0, 0, ?, ?, 'Queued')
                """,
                (
                    job_id,
                    user_id,
                    priority,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="queued",
                message="queued preprocess job",
            )
        return self.get_job_with_assets(job_id)

    def create_completed_preprocess_job(
        self,
        *,
        user_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
        priority: int = 0,
        progress_message: str = "Completed",
    ) -> dict[str, Any]:
        job_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO render_jobs (
                    job_id, user_id, status, priority, job_type, payload_json,
                    result_json, estimated_points, duration_seconds,
                    progress_percent, progress_message,
                    created_at, updated_at, completed_at
                )
                VALUES (?, ?, 'completed', ?, 'preprocess', ?, ?, 0, 0, 100, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    priority,
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    progress_message[:500],
                    now,
                    now,
                    now,
                ),
            )
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="completed",
                message="preprocess completed directly by cloud api",
            )
        return self.get_job_with_assets(job_id)

    def complete_preprocess_job_direct(
        self,
        *,
        job_id: str,
        user_id: str,
        result: dict[str, Any],
        progress_message: str = "Completed",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """
                UPDATE render_jobs
                SET status = 'completed',
                    result_json = ?,
                    error_message = NULL,
                    progress_percent = 100,
                    progress_message = ?,
                    worker_id = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE job_id = ?
                  AND user_id = ?
                  AND job_type = 'preprocess'
                  AND status IN ('queued', 'running', 'uploading')
                """,
                (
                    json.dumps(result or {}, ensure_ascii=False),
                    progress_message[:500],
                    now,
                    now,
                    job_id,
                    user_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="completed",
                message="preprocess completed directly by cloud api",
            )
        return self.get_job_with_assets(job_id)

    def get_job_with_assets(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        job["assets"] = self.list_job_assets(job_id=job_id)
        return job

    def get_client_job_with_assets(self, *, user_id: str, job_id: str) -> dict[str, Any]:
        job = self.get_job_with_assets(job_id)
        if job.get("user_id") != user_id:
            raise KeyError(job_id)
        return job

    def list_users(self, *, email: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            if email:
                pattern = f"%{email.strip().lower()}%"
                rows = db.execute(
                    """
                    SELECT * FROM users
                    WHERE lower(COALESCE(email, '')) LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (pattern, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM users
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item.pop("password_hash", None)
                item["wallet"] = self._wallet_for_user(db, row["user_id"])
                items.append(item)
        return items

    def create_admin_user(
        self,
        *,
        email: str,
        initial_points: int = 0,
    ) -> dict[str, Any]:
        if initial_points < 0:
            raise ValueError("initial_points must not be negative")
        address = normalize_email(email)
        now = utc_now()
        user_id = str(uuid4())
        license_key = secrets.token_urlsafe(12)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT user_id FROM users WHERE email = ?", (address,)).fetchone()
            if existing is not None:
                raise ValueError("email already exists")
            db.execute(
                """
                INSERT INTO users (
                    user_id, email, email_verified_at, license_status, license_key,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, 'inactive', ?, 'active', ?, ?)
                """,
                (user_id, address, now, license_key, now, now),
            )
            db.execute(
                """
                INSERT INTO credit_wallets (
                    user_id, bonus_balance, paid_balance, frozen_bonus, frozen_paid, updated_at
                )
                VALUES (?, 0, ?, 0, 0, ?)
                """,
                (user_id, initial_points, now),
            )
            db.execute(
                """
                INSERT INTO license_keys (
                    license_key, status, max_activations, grant_points,
                    assigned_user_id, created_at
                )
                VALUES (?, 'active', 1, 0, ?, ?)
                """,
                (license_key, user_id, now),
            )
            if initial_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="admin_credit",
                    points=initial_points,
                    source="paid",
                    note="initial admin credit",
                )
        detail = self.get_user_detail(user_id=user_id)
        detail["activation_code"] = license_key
        return detail

    def admin_dashboard(self) -> dict[str, Any]:
        with self.connect() as db:
            user_counts = db.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active
                FROM users
                """
            ).fetchone()
            wallet_totals = db.execute(
                """
                SELECT COALESCE(SUM(bonus_balance), 0) AS bonus,
                       COALESCE(SUM(paid_balance), 0) AS paid,
                       COALESCE(SUM(frozen_bonus + frozen_paid), 0) AS frozen
                FROM credit_wallets
                """
            ).fetchone()
            license_counts = db.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'active'
                                     AND (expires_at IS NULL OR expires_at > ?)
                                THEN 1 ELSE 0 END) AS active
                FROM license_keys
                """,
                (utc_now(),),
            ).fetchone()
            job_counts = {
                row["status"]: int(row["count"])
                for row in db.execute(
                    "SELECT status, COUNT(*) AS count FROM render_jobs GROUP BY status"
                ).fetchall()
            }
        return {
            "users": {
                "total": int(user_counts["total"] or 0),
                "active": int(user_counts["active"] or 0),
            },
            "wallets": {
                "bonus_points": int(wallet_totals["bonus"] or 0),
                "paid_points": int(wallet_totals["paid"] or 0),
                "frozen_points": int(wallet_totals["frozen"] or 0),
            },
            "licenses": {
                "total": int(license_counts["total"] or 0),
                "active": int(license_counts["active"] or 0),
            },
            "jobs": job_counts,
        }

    def list_license_keys(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT l.*,
                       (SELECT COUNT(*) FROM license_activations a
                        WHERE a.license_key = l.license_key) AS activation_count
                FROM license_keys l
                ORDER BY l.created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["effective_status"] = self._license_effective_status(item)
        return items

    def get_user_detail(self, *, user_id: str) -> dict[str, Any]:
        with self.connect() as db:
            user = self._user_for_id(db, user_id)
            devices = [
                self._device_public(dict(row))
                for row in db.execute(
                    """
                    SELECT * FROM devices
                    WHERE user_id = ?
                    ORDER BY last_seen_at DESC
                    """,
                    (user_id,),
                ).fetchall()
            ]
            ledger = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM credit_ledger
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    (user_id,),
                ).fetchall()
            ]
            jobs = [
                self._job_from_row(row)
                for row in db.execute(
                    """
                    SELECT * FROM render_jobs
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    (user_id,),
                ).fetchall()
            ]
            license_activations = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM license_activations
                    WHERE user_id = ?
                    ORDER BY activated_at DESC
                    """,
                    (user_id,),
                ).fetchall()
            ]
            return {
                "user": user,
                "wallet": self._wallet_for_user(db, user_id),
                "devices": devices,
                "ledger": ledger,
                "jobs": jobs,
                "license_activations": license_activations,
            }

    def list_credit_ledger(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            self._user_for_id(db, user_id)
            rows = db.execute(
                """
                SELECT * FROM credit_ledger
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_user_credits(self, *, user_id: str, points: int, note: str = "") -> dict[str, Any]:
        if points <= 0:
            raise ValueError("points must be positive")
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._user_for_id(db, user_id)
            db.execute(
                """
                UPDATE credit_wallets
                SET paid_balance = paid_balance + ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (points, now, user_id),
            )
            self._insert_ledger(
                db,
                user_id=user_id,
                event_type="admin_credit",
                points=points,
                source="paid",
                note=note or "manual admin credit",
            )
            return {
                "user": self._user_for_id(db, user_id),
                "wallet": self._wallet_for_user(db, user_id),
            }

    def deduct_user_credits(self, *, user_id: str, points: int, note: str = "") -> dict[str, Any]:
        if points <= 0:
            raise ValueError("points must be positive")
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._user_for_id(db, user_id)
            wallet = self._wallet_for_user(db, user_id)
            if int(wallet["available_points"]) < points:
                raise ValueError("insufficient available points")
            paid_points = min(points, int(wallet["paid_balance"]))
            bonus_points = points - paid_points
            db.execute(
                """
                UPDATE credit_wallets
                SET paid_balance = paid_balance - ?,
                    bonus_balance = bonus_balance - ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (paid_points, bonus_points, now, user_id),
            )
            if paid_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="admin_debit",
                    points=-paid_points,
                    source="paid",
                    note=note or "manual admin debit",
                )
            if bonus_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="admin_debit",
                    points=-bonus_points,
                    source="bonus",
                    note=note or "manual admin debit",
                )
            return {
                "user": self._user_for_id(db, user_id),
                "wallet": self._wallet_for_user(db, user_id),
            }

    def update_user(
        self,
        *,
        user_id: str,
        status: str | None = None,
        license_status: str | None = None,
    ) -> dict[str, Any]:
        allowed_status = {"active", "disabled"}
        allowed_license_status = {"inactive", "active", "disabled"}
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            if status not in allowed_status:
                raise ValueError("invalid user status")
            updates.append("status = ?")
            params.append(status)
        if license_status is not None:
            if license_status not in allowed_license_status:
                raise ValueError("invalid license status")
            updates.append("license_status = ?")
            params.append(license_status)
        if not updates:
            return self.get_user_detail(user_id=user_id)
        now = utc_now()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(user_id)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                tuple(params),
            )
            if cursor.rowcount == 0:
                raise KeyError(user_id)
        return self.get_user_detail(user_id=user_id)

    def reset_user_devices(self, *, user_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            self._user_for_id(db, user_id)
            rows = db.execute(
                "SELECT device_id FROM devices WHERE user_id = ? AND revoked_at IS NULL",
                (user_id,),
            ).fetchall()
            for row in rows:
                db.execute(
                    """
                    UPDATE devices
                    SET revoked_at = ?,
                        access_token = ?
                    WHERE device_id = ?
                    """,
                    (now, f"revoked:{row['device_id']}:{uuid4()}", row["device_id"]),
                )
        return self.get_user_detail(user_id=user_id)

    def list_job_assets(self, *, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM job_assets
                WHERE job_id = ?
                ORDER BY created_at ASC
                """,
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_completed_output_key(self, *, user_id: str, job_id: str) -> str:
        job = self.get_client_job_with_assets(user_id=user_id, job_id=job_id)
        if job["status"] != "completed":
            raise RuntimeError("job is not completed")
        result = job.get("result") or {}
        output_key = result.get("output_cos_key")
        if output_key:
            return str(output_key)
        for asset in job["assets"]:
            if asset["kind"] == "output" and asset["status"] == "uploaded":
                return str(asset["cos_key"])
        raise KeyError("output_cos_key")

    def confirm_output_downloaded(
        self,
        *,
        user_id: str,
        job_id: str,
        delete_delay_hours: int,
    ) -> dict[str, Any]:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(hours=max(1, delete_delay_hours))).isoformat()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE job_assets
                SET status = 'downloaded',
                    downloaded_at = ?,
                    expires_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                  AND job_id = ?
                  AND kind = 'output'
                  AND deleted_at IS NULL
                  AND status IN ('uploaded', 'downloaded')
                """,
                (now, expires_at, now, user_id, job_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("output")
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="download_confirmed",
                message=f"output scheduled for deletion at {expires_at}",
            )
        return self.get_client_job_with_assets(user_id=user_id, job_id=job_id)

    def list_expired_output_assets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        now = utc_now()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM job_assets
                WHERE kind = 'output'
                  AND deleted_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                  AND status IN ('uploaded', 'downloaded')
                ORDER BY expires_at ASC
                LIMIT ?
                """,
                (now, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_stale_input_assets(
        self,
        *,
        older_than_hours: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max(1, older_than_hours))
        ).isoformat()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM job_assets
                WHERE kind != 'output'
                  AND deleted_at IS NULL
                  AND created_at <= ?
                  AND status IN ('pending', 'uploaded', 'downloaded')
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (cutoff, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_asset_deleted(self, *, asset_id: str) -> None:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                UPDATE job_assets
                SET status = 'deleted',
                    deleted_at = ?,
                    updated_at = ?
                WHERE asset_id = ?
                """,
                (now, now, asset_id),
            )

    def create_client_job(
        self,
        *,
        user_id: str,
        payload: dict[str, Any],
        duration_seconds: int,
        resolution: str,
        max_duration_seconds: int,
        daily_bonus_limit: int,
        priority: int = 0,
        job_type: str = "render",
    ) -> dict[str, Any]:
        if duration_seconds <= 0 or duration_seconds > max_duration_seconds:
            raise ValueError("duration_seconds exceeds MVP limit")
        points = estimate_render_points(
            duration_seconds=duration_seconds,
            resolution=resolution,
        )
        job_id = str(uuid4())
        hold_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            queued = db.execute(
                """
                SELECT COUNT(*) AS count FROM render_jobs
                WHERE user_id = ? AND status = 'queued'
                """,
                (user_id,),
            ).fetchone()["count"]
            if queued >= 1:
                raise RuntimeError("queued job limit reached")

            wallet = self._wallet_for_user(db, user_id)
            daily_bonus_available = max(
                0,
                daily_bonus_limit - self._bonus_reserved_today(db, user_id=user_id),
            )
            bonus_points = min(int(wallet["bonus_balance"]), daily_bonus_available, points)
            paid_points = points - bonus_points
            if int(wallet["paid_balance"]) < paid_points:
                raise ValueError("insufficient credits")
            db.execute(
                """
                UPDATE credit_wallets
                SET bonus_balance = bonus_balance - ?,
                    paid_balance = paid_balance - ?,
                    frozen_bonus = frozen_bonus + ?,
                    frozen_paid = frozen_paid + ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (bonus_points, paid_points, bonus_points, paid_points, now, user_id),
            )
            db.execute(
                """
                INSERT INTO credit_holds (
                    hold_id, user_id, job_id, status, bonus_points, paid_points,
                    total_points, created_at, updated_at, reason
                )
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, 'render_job_hold')
                """,
                (hold_id, user_id, job_id, bonus_points, paid_points, points, now, now),
            )
            if bonus_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="hold",
                    points=-bonus_points,
                    source="bonus",
                    job_id=job_id,
                    hold_id=hold_id,
                    note="render job hold",
                )
            if paid_points:
                self._insert_ledger(
                    db,
                    user_id=user_id,
                    event_type="hold",
                    points=-paid_points,
                    source="paid",
                    job_id=job_id,
                    hold_id=hold_id,
                    note="render job hold",
                )
            queued_payload = dict(payload)
            queued_payload.update(
                {
                    "duration_seconds": duration_seconds,
                    "resolution": resolution,
                    "estimated_points": points,
                }
            )
            db.execute(
                """
                INSERT INTO render_jobs (
                    job_id, user_id, hold_id, status, priority, job_type,
                    payload_json, estimated_points, duration_seconds, resolution,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    hold_id,
                    priority,
                    job_type,
                    json.dumps(queued_payload, ensure_ascii=False),
                    points,
                    duration_seconds,
                    resolution,
                    now,
                    now,
                ),
            )
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="queued",
                message=f"held {points} credits",
            )
        return self.get_job_with_assets(job_id)

    def cancel_client_job(self, *, job_id: str, user_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM render_jobs WHERE job_id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] == "uploading":
                db.execute(
                    """
                    UPDATE render_jobs
                    SET status = 'canceled',
                        progress_message = 'Canceled before submit',
                        updated_at = ?,
                        completed_at = ?
                    WHERE job_id = ?
                    """,
                    (now, now, job_id),
                )
                self._insert_job_event(
                    db,
                    job_id=job_id,
                    event_type="canceled",
                    message="canceled before job submit",
                )
            elif row["status"] == "queued":
                db.execute(
                    """
                    UPDATE render_jobs
                    SET status = 'canceled',
                        progress_message = 'Canceled before start',
                        updated_at = ?,
                        completed_at = ?
                    WHERE job_id = ?
                    """,
                    (now, now, job_id),
                )
                self._release_hold(db, hold_id=row["hold_id"], reason="canceled_before_start")
                self._insert_job_event(
                    db,
                    job_id=job_id,
                    event_type="canceled",
                    message="canceled before worker started",
                )
            elif row["status"] == "running":
                db.execute(
                    """
                    UPDATE render_jobs
                    SET status = 'canceled',
                        progress_message = 'Canceled after start',
                        cancel_requested_at = ?,
                        updated_at = ?,
                        completed_at = ?
                    WHERE job_id = ?
                    """,
                    (now, now, now, job_id),
                )
                self._capture_cancel_fee(db, hold_id=row["hold_id"], fee_ratio=0.30)
                self._insert_job_event(
                    db,
                    job_id=job_id,
                    event_type="canceled",
                    message="canceled after worker started; captured 30% fee",
                )
            else:
                raise RuntimeError("job cannot be canceled")
        return self.get_job_with_assets(job_id)

    def fail_stale_running_jobs(
        self,
        *,
        timeout_seconds: int,
        preprocess_timeout_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(seconds=timeout_seconds)).isoformat()
        preprocess_timeout = (
            timeout_seconds if preprocess_timeout_seconds is None else preprocess_timeout_seconds
        )
        preprocess_cutoff = (now_dt - timedelta(seconds=preprocess_timeout)).isoformat()
        now = now_dt.isoformat()
        failed_ids: list[str] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT * FROM render_jobs
                WHERE status = 'running'
                  AND (
                    updated_at < ?
                    OR (job_type = 'preprocess' AND updated_at < ?)
                  )
                """,
                (cutoff, preprocess_cutoff),
            ).fetchall()
            for row in rows:
                db.execute(
                    """
                    UPDATE render_jobs
                    SET status = 'failed',
                        error_message = 'scheduler timeout: worker stopped reporting progress',
                        progress_message = 'Failed by scheduler timeout',
                        updated_at = ?,
                        completed_at = ?
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (now, now, row["job_id"]),
                )
                self._release_hold(db, hold_id=row["hold_id"], reason="scheduler_timeout")
                self._insert_job_event(
                    db,
                    job_id=row["job_id"],
                    event_type="failed",
                    message="scheduler timeout; released frozen credits",
                )
                failed_ids.append(row["job_id"])
        return [self.get_job(job_id) for job_id in failed_ids]

    def timeout_stale_queued_jobs(self, *, timeout_seconds: int) -> list[dict[str, Any]]:
        now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(seconds=max(1, timeout_seconds))).isoformat()
        now = now_dt.isoformat()
        timed_out_ids: list[str] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT * FROM render_jobs
                WHERE status = 'queued' AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                db.execute(
                    """
                    UPDATE render_jobs
                    SET status = 'timed_out',
                        error_message = 'queue timeout: no worker response within 24 hours',
                        progress_message = 'Queue timed out after 24 hours',
                        updated_at = ?,
                        completed_at = ?
                    WHERE job_id = ? AND status = 'queued'
                    """,
                    (now, now, row["job_id"]),
                )
                self._release_hold(db, hold_id=row["hold_id"], reason="queue_timeout")
                self._insert_job_event(
                    db,
                    job_id=row["job_id"],
                    event_type="timed_out",
                    message="queue timed out after 24 hours; released frozen credits",
                )
                timed_out_ids.append(row["job_id"])
        return [self.get_job(job_id) for job_id in timed_out_ids]

    def _user_for_id(self, db: sqlite3.Connection, user_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        item = dict(row)
        item.pop("password_hash", None)
        return item

    def _device_for_id(self, db: sqlite3.Connection, device_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if row is None:
            raise KeyError(device_id)
        return self._device_public(dict(row))

    def _device_public(self, item: dict[str, Any]) -> dict[str, Any]:
        item.pop("access_token", None)
        return item

    def _wallet_for_user(self, db: sqlite3.Connection, user_id: str) -> dict[str, Any]:
        row = db.execute(
            "SELECT * FROM credit_wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            now = utc_now()
            db.execute(
                """
                INSERT INTO credit_wallets (
                    user_id, bonus_balance, paid_balance, frozen_bonus, frozen_paid, updated_at
                )
                VALUES (?, 0, 0, 0, 0, ?)
                """,
                (user_id, now),
            )
            row = db.execute(
                "SELECT * FROM credit_wallets WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        item = dict(row)
        item["available_points"] = int(item["bonus_balance"]) + int(item["paid_balance"])
        item["frozen_points"] = int(item["frozen_bonus"]) + int(item["frozen_paid"])
        item["total_points"] = item["available_points"] + item["frozen_points"]
        return item

    def _safe_file_name(self, value: str) -> str:
        cleaned = value.replace("\\", "/").split("/")[-1].strip()
        return cleaned[:180] or "asset"

    def _insert_ledger(
        self,
        db: sqlite3.Connection,
        *,
        user_id: str,
        event_type: str,
        points: int,
        source: str,
        job_id: str | None = None,
        hold_id: str | None = None,
        code: str | None = None,
        note: str = "",
    ) -> None:
        db.execute(
            """
            INSERT INTO credit_ledger (
                ledger_id, user_id, event_type, points, source,
                job_id, hold_id, code, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                user_id,
                event_type,
                points,
                source,
                job_id,
                hold_id,
                code,
                note[:500],
                utc_now(),
            ),
        )

    def _insert_job_event(
        self,
        db: sqlite3.Connection,
        *,
        job_id: str,
        event_type: str,
        message: str = "",
    ) -> None:
        db.execute(
            """
            INSERT INTO job_events (event_id, job_id, event_type, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), job_id, event_type, message[:500], utc_now()),
        )

    def _bonus_reserved_today(self, db: sqlite3.Connection, *, user_id: str) -> int:
        start = datetime.combine(
            datetime.now(timezone.utc).date(),
            time.min,
            tzinfo=timezone.utc,
        ).isoformat()
        ledger_row = db.execute(
            """
            SELECT COALESCE(SUM(ABS(points)), 0) AS points
            FROM credit_ledger
            WHERE user_id = ?
              AND source = 'bonus'
              AND event_type IN ('capture', 'cancel_fee')
              AND created_at >= ?
            """,
            (user_id, start),
        ).fetchone()
        hold_row = db.execute(
            """
            SELECT COALESCE(SUM(bonus_points), 0) AS points
            FROM credit_holds
            WHERE user_id = ?
              AND status = 'active'
              AND created_at >= ?
            """,
            (user_id, start),
        ).fetchone()
        return int(ledger_row["points"]) + int(hold_row["points"])

    def _capture_hold(self, db: sqlite3.Connection, *, hold_id: str | None) -> None:
        if not hold_id:
            return
        now = utc_now()
        hold = db.execute(
            "SELECT * FROM credit_holds WHERE hold_id = ? AND status = 'active'",
            (hold_id,),
        ).fetchone()
        if hold is None:
            return
        db.execute(
            """
            UPDATE credit_wallets
            SET frozen_bonus = frozen_bonus - ?,
                frozen_paid = frozen_paid - ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (hold["bonus_points"], hold["paid_points"], now, hold["user_id"]),
        )
        db.execute(
            """
            UPDATE credit_holds
            SET status = 'captured',
                updated_at = ?,
                captured_at = ?,
                reason = 'job_completed'
            WHERE hold_id = ?
            """,
            (now, now, hold_id),
        )
        if int(hold["bonus_points"]):
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="capture",
                points=-int(hold["bonus_points"]),
                source="bonus",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note="job completed",
            )
        if int(hold["paid_points"]):
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="capture",
                points=-int(hold["paid_points"]),
                source="paid",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note="job completed",
            )

    def _release_hold(
        self,
        db: sqlite3.Connection,
        *,
        hold_id: str | None,
        reason: str,
    ) -> None:
        if not hold_id:
            return
        now = utc_now()
        hold = db.execute(
            "SELECT * FROM credit_holds WHERE hold_id = ? AND status = 'active'",
            (hold_id,),
        ).fetchone()
        if hold is None:
            return
        db.execute(
            """
            UPDATE credit_wallets
            SET bonus_balance = bonus_balance + ?,
                paid_balance = paid_balance + ?,
                frozen_bonus = frozen_bonus - ?,
                frozen_paid = frozen_paid - ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                hold["bonus_points"],
                hold["paid_points"],
                hold["bonus_points"],
                hold["paid_points"],
                now,
                hold["user_id"],
            ),
        )
        db.execute(
            """
            UPDATE credit_holds
            SET status = 'released',
                updated_at = ?,
                released_at = ?,
                reason = ?
            WHERE hold_id = ?
            """,
            (now, now, reason[:120], hold_id),
        )
        if int(hold["bonus_points"]):
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="release",
                points=int(hold["bonus_points"]),
                source="bonus",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note=reason,
            )
        if int(hold["paid_points"]):
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="release",
                points=int(hold["paid_points"]),
                source="paid",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note=reason,
            )

    def _capture_cancel_fee(
        self,
        db: sqlite3.Connection,
        *,
        hold_id: str | None,
        fee_ratio: float,
    ) -> None:
        if not hold_id:
            return
        now = utc_now()
        hold = db.execute(
            "SELECT * FROM credit_holds WHERE hold_id = ? AND status = 'active'",
            (hold_id,),
        ).fetchone()
        if hold is None:
            return
        total = int(hold["total_points"])
        fee_total = max(1, math.ceil(total * fee_ratio))
        bonus_points = int(hold["bonus_points"])
        paid_points = int(hold["paid_points"])
        fee_bonus = min(bonus_points, math.floor(fee_total * bonus_points / total))
        fee_paid = min(paid_points, fee_total - fee_bonus)
        if fee_bonus + fee_paid < fee_total:
            fee_bonus = min(bonus_points, fee_bonus + fee_total - fee_bonus - fee_paid)
        release_bonus = bonus_points - fee_bonus
        release_paid = paid_points - fee_paid
        db.execute(
            """
            UPDATE credit_wallets
            SET bonus_balance = bonus_balance + ?,
                paid_balance = paid_balance + ?,
                frozen_bonus = frozen_bonus - ?,
                frozen_paid = frozen_paid - ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                release_bonus,
                release_paid,
                bonus_points,
                paid_points,
                now,
                hold["user_id"],
            ),
        )
        db.execute(
            """
            UPDATE credit_holds
            SET status = 'cancel_fee_captured',
                updated_at = ?,
                captured_at = ?,
                released_at = ?,
                reason = 'canceled_after_start'
            WHERE hold_id = ?
            """,
            (now, now, now, hold_id),
        )
        if fee_bonus:
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="cancel_fee",
                points=-fee_bonus,
                source="bonus",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note="30 percent fee for started job cancellation",
            )
        if fee_paid:
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="cancel_fee",
                points=-fee_paid,
                source="paid",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note="30 percent fee for started job cancellation",
            )
        if release_bonus:
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="release",
                points=release_bonus,
                source="bonus",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note="released remaining canceled hold",
            )
        if release_paid:
            self._insert_ledger(
                db,
                user_id=hold["user_id"],
                event_type="release",
                points=release_paid,
                source="paid",
                job_id=hold["job_id"],
                hold_id=hold_id,
                note="released remaining canceled hold",
            )

    def create_job(
        self,
        *,
        payload: dict[str, Any],
        priority: int = 0,
        job_type: str = "render",
    ) -> dict[str, Any]:
        job_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO render_jobs (
                    job_id, status, priority, job_type, payload_json, created_at, updated_at
                )
                VALUES (?, 'queued', ?, ?, ?, ?, ?)
                """,
                (job_id, priority, job_type, json.dumps(payload, ensure_ascii=False), now, now),
            )
        return self.get_job_with_assets(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM render_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    def list_jobs(
        self,
        *,
        limit: int = 50,
        job_status: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if job_status:
            conditions.append("j.status = ?")
            params.append(job_status)
        if query and query.strip():
            pattern = f"%{query.strip().lower()}%"
            conditions.append(
                "(lower(j.job_id) LIKE ? OR lower(COALESCE(u.email, '')) LIKE ? "
                "OR lower(COALESCE(j.worker_id, '')) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT j.*, u.email,
                       (SELECT COUNT(*) FROM job_assets a WHERE a.job_id = j.job_id)
                           AS asset_count
                FROM render_jobs j
                LEFT JOIN users u ON u.user_id = j.user_id
                {where_clause}
                ORDER BY j.created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_client_jobs(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM render_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def admin_job_summary(self) -> dict[str, int]:
        with self.connect() as db:
            counts = {
                str(row["status"]): int(row["count"])
                for row in db.execute(
                    "SELECT status, COUNT(*) AS count FROM render_jobs GROUP BY status"
                ).fetchall()
            }
        counts["total"] = sum(counts.values())
        counts["pending"] = sum(
            counts.get(key, 0) for key in ("uploading", "queued", "running")
        )
        return counts

    def get_admin_job_detail(self, *, job_id: str) -> dict[str, Any]:
        job = self.get_job_with_assets(job_id)
        with self.connect() as db:
            events = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM job_events
                    WHERE job_id = ?
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    (job_id,),
                ).fetchall()
            ]
            user = None
            wallet = None
            if job.get("user_id"):
                user = self._user_for_id(db, job["user_id"])
                wallet = self._wallet_for_user(db, job["user_id"])
        job["events"] = events
        job["user"] = user
        job["wallet"] = wallet
        return job

    def claim_job(self, *, worker_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT * FROM render_jobs AS queued_job
                WHERE queued_job.status = 'queued'
                  AND (
                    queued_job.user_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM render_jobs AS running_job
                        WHERE running_job.user_id = queued_job.user_id
                          AND running_job.status = 'running'
                    )
                  )
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            updated = db.execute(
                """
                UPDATE render_jobs
                SET status = 'running',
                    worker_id = ?,
                    claimed_at = ?,
                    updated_at = ?,
                    progress_message = 'Worker claimed job'
                WHERE job_id = ? AND status = 'queued'
                """,
                (worker_id, now, now, row["job_id"]),
            )
            if getattr(updated, "rowcount", 0) != 1:
                return None
            self._insert_job_event(
                db,
                job_id=row["job_id"],
                event_type="claimed",
                message=f"claimed by {worker_id}",
            )
            claimed = db.execute(
                "SELECT * FROM render_jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()
        return self._job_from_row(claimed)

    def update_progress(
        self,
        *,
        job_id: str,
        worker_id: str,
        percent: int,
        message: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE render_jobs
                SET progress_percent = ?,
                    progress_message = ?,
                    updated_at = ?
                WHERE job_id = ? AND worker_id = ? AND status = 'running'
                """,
                (max(0, min(percent, 99)), message[:500], now, job_id, worker_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
        return self.get_job_with_assets(job_id)

    def complete_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        result: dict[str, Any],
        output_expires_at: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE render_jobs
                SET status = 'completed',
                    result_json = ?,
                    progress_percent = 100,
                    progress_message = 'Completed',
                    updated_at = ?,
                    completed_at = ?
                WHERE job_id = ? AND worker_id = ? AND status = 'running'
                """,
                (json.dumps(result, ensure_ascii=False), now, now, job_id, worker_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            row = db.execute("SELECT * FROM render_jobs WHERE job_id = ?", (job_id,)).fetchone()
            output_cos_key = result.get("output_cos_key")
            if output_cos_key and row["user_id"]:
                output_file_name = self._safe_file_name(
                    str(result.get("output_file_name") or Path(str(output_cos_key)).name or "result.mp4")
                )
                output_content_type = str(result.get("output_content_type") or "video/mp4")
                db.execute(
                    """
                    INSERT INTO job_assets (
                        asset_id, job_id, user_id, kind, cos_key, file_name,
                        content_type, status, created_at, updated_at, uploaded_at, expires_at
                    )
                    VALUES (?, ?, ?, 'output', ?, ?, ?, 'uploaded', ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        job_id,
                        row["user_id"],
                        str(output_cos_key),
                        output_file_name,
                        output_content_type,
                        now,
                        now,
                        now,
                        output_expires_at,
                    ),
                )
            self._capture_hold(db, hold_id=row["hold_id"])
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="completed",
                message="worker completed job",
            )
        return self.get_job_with_assets(job_id)

    def fail_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE render_jobs
                SET status = 'failed',
                    error_message = ?,
                    progress_message = 'Failed',
                    updated_at = ?,
                    completed_at = ?
                WHERE job_id = ? AND worker_id = ? AND status = 'running'
                """,
                (error_message[:1200], now, now, job_id, worker_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            row = db.execute("SELECT * FROM render_jobs WHERE job_id = ?", (job_id,)).fetchone()
            self._release_hold(db, hold_id=row["hold_id"], reason="job_failed")
            self._insert_job_event(
                db,
                job_id=job_id,
                event_type="failed",
                message=error_message[:500],
            )
        return self.get_job_with_assets(job_id)

    def heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        current_job_id: str | None,
        message: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO worker_heartbeats (
                    worker_id, status, current_job_id, message, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    status = excluded.status,
                    current_job_id = excluded.current_job_id,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (worker_id, status, current_job_id, message[:500], now),
            )
            db.execute(
                """
                INSERT INTO worker_nodes (
                    worker_id, status, current_job_id, message, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    status = excluded.status,
                    current_job_id = excluded.current_job_id,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (worker_id, status, current_job_id, message[:500], now),
            )
            row = db.execute(
                "SELECT * FROM worker_nodes WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
        return dict(row)

    def fail_interrupted_douyin_transcriptions(self) -> int:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE douyin_transcriptions
                SET status = 'failed',
                    progress_message = '服务器重启，任务已中断，请重新提交',
                    error_message = '服务器重启，任务已中断，请重新提交',
                    updated_at = ?,
                    completed_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (now, now),
            )
        return max(0, int(cursor.rowcount))

    def create_douyin_transcription(
        self,
        *,
        user_id: str,
        share_url: str,
    ) -> dict[str, Any]:
        now = utc_now()
        transcription_id = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                """
                SELECT transcription_id
                FROM douyin_transcriptions
                WHERE user_id = ? AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if active is not None:
                raise RuntimeError("已有抖音文案提取任务正在处理，请稍后再试")
            db.execute(
                """
                INSERT INTO douyin_transcriptions (
                    transcription_id, user_id, share_url, status,
                    progress_percent, progress_message, transcript,
                    error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', 0, '等待服务器处理', '', '', ?, ?)
                """,
                (transcription_id, user_id, share_url, now, now),
            )
            row = db.execute(
                "SELECT * FROM douyin_transcriptions WHERE transcription_id = ?",
                (transcription_id,),
            ).fetchone()
        return dict(row)

    def get_douyin_transcription(
        self,
        *,
        transcription_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        sql = "SELECT * FROM douyin_transcriptions WHERE transcription_id = ?"
        params: tuple[Any, ...] = (transcription_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        with self.connect() as db:
            row = db.execute(sql, params).fetchone()
        if row is None:
            raise KeyError(transcription_id)
        return dict(row)

    def update_douyin_transcription(
        self,
        *,
        transcription_id: str,
        status: str | None = None,
        progress_percent: int | None = None,
        progress_message: str | None = None,
        transcript: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in {"queued", "running", "completed", "failed"}:
            raise ValueError("invalid douyin transcription status")
        now = utc_now()
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [now]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
            if status in {"completed", "failed"}:
                updates.append("completed_at = ?")
                values.append(now)
        if progress_percent is not None:
            updates.append("progress_percent = ?")
            values.append(max(0, min(100, int(progress_percent))))
        if progress_message is not None:
            updates.append("progress_message = ?")
            values.append(progress_message[:500])
        if transcript is not None:
            updates.append("transcript = ?")
            values.append(transcript)
        if error_message is not None:
            updates.append("error_message = ?")
            values.append(error_message[:1200])
        values.append(transcription_id)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE douyin_transcriptions SET {', '.join(updates)} "
                "WHERE transcription_id = ?",
                tuple(values),
            )
            if cursor.rowcount == 0:
                raise KeyError(transcription_id)
            row = db.execute(
                "SELECT * FROM douyin_transcriptions WHERE transcription_id = ?",
                (transcription_id,),
            ).fetchone()
        return dict(row)

    def queue_stats(self, *, worker_stale_seconds: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.connect() as db:
            counts = {
                row["status"]: row["count"]
                for row in db.execute(
                    "SELECT status, COUNT(*) AS count FROM render_jobs GROUP BY status"
                ).fetchall()
            }
            oldest = db.execute(
                """
                SELECT created_at FROM render_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            workers = [dict(row) for row in db.execute("SELECT * FROM worker_nodes").fetchall()]
        oldest_wait_seconds = 0
        if oldest is not None:
            created_at = parse_time(oldest["created_at"])
            if created_at is not None:
                oldest_wait_seconds = max(0, int((now - created_at).total_seconds()))
        online_workers = []
        stale_workers = []
        for worker in workers:
            updated_at = parse_time(worker["updated_at"])
            age = int((now - updated_at).total_seconds()) if updated_at else worker_stale_seconds + 1
            worker["age_seconds"] = age
            if age <= worker_stale_seconds:
                online_workers.append(worker)
            else:
                stale_workers.append(worker)
        return {
            "counts": counts,
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "oldest_wait_seconds": oldest_wait_seconds,
            "online_workers": online_workers,
            "stale_workers": stale_workers,
        }

    def notification_allowed(self, *, key: str, cooldown_seconds: int) -> bool:
        now = datetime.now(timezone.utc)
        with self.connect() as db:
            row = db.execute("SELECT sent_at FROM notifications WHERE key = ?", (key,)).fetchone()
            if row is not None:
                sent_at = parse_time(row["sent_at"])
                if sent_at is not None and (now - sent_at).total_seconds() < cooldown_seconds:
                    return False
            db.execute(
                """
                INSERT INTO notifications (key, sent_at)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET sent_at = excluded.sent_at
                """,
                (key, now.isoformat()),
            )
        return True

    def _job_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        result_json = item.pop("result_json")
        item["result"] = json.loads(result_json) if result_json else None
        return item
