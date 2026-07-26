from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    admin_token: str = os.getenv("ADMIN_TOKEN", "change-admin-token")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD") or os.getenv(
        "ADMIN_TOKEN", "change-admin-token"
    )
    admin_cookie_secure: bool = _bool_env("ADMIN_COOKIE_SECURE", False)
    worker_token: str = os.getenv("WORKER_TOKEN", "change-worker-token")
    database_path: Path = Path(os.getenv("CLOUD_DATABASE_PATH", "./data/cloud.sqlite3"))
    database_url: str = os.getenv("DATABASE_URL", "").strip()
    redis_url: str = os.getenv("REDIS_URL", "").strip()
    notify_webhook_url: str = os.getenv("NOTIFY_WEBHOOK_URL", "")
    notify_cooldown_seconds: int = _int_env("NOTIFY_COOLDOWN_SECONDS", 900)
    notify_queued_threshold: int = _int_env("NOTIFY_QUEUED_THRESHOLD", 1)
    notify_wait_minutes_threshold: int = _int_env("NOTIFY_WAIT_MINUTES_THRESHOLD", 30)
    worker_stale_seconds: int = _int_env("WORKER_STALE_SECONDS", 600)
    client_rate_limit_per_minute: int = _int_env("CLIENT_RATE_LIMIT_PER_MINUTE", 180)
    worker_rate_limit_per_minute: int = _int_env("WORKER_RATE_LIMIT_PER_MINUTE", 600)
    license_activation_grant_points: int = _int_env("LICENSE_ACTIVATION_GRANT_POINTS", 0)
    email_provider: str = os.getenv("EMAIL_PROVIDER", "console").strip().lower()
    tencentcloud_secret_id: str = os.getenv("TENCENTCLOUD_SECRET_ID", "")
    tencentcloud_secret_key: str = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
    ses_region: str = os.getenv("SES_REGION", "ap-guangzhou")
    ses_from_email: str = os.getenv("SES_FROM_EMAIL", "")
    ses_login_template_id: str = os.getenv("SES_LOGIN_TEMPLATE_ID", "")
    ses_login_subject: str = os.getenv(
        "SES_LOGIN_SUBJECT", "杰速口播邮箱验证码"
    ).strip()
    email_code_ttl_seconds: int = _int_env("EMAIL_CODE_TTL_SECONDS", 600)
    email_code_resend_seconds: int = _int_env("EMAIL_CODE_RESEND_SECONDS", 60)
    email_code_max_attempts: int = _int_env("EMAIL_CODE_MAX_ATTEMPTS", 5)
    email_code_per_email_per_hour: int = _int_env(
        "EMAIL_CODE_PER_EMAIL_PER_HOUR", 5
    )
    email_code_per_device_per_hour: int = _int_env(
        "EMAIL_CODE_PER_DEVICE_PER_HOUR", 10
    )
    email_code_per_device_per_day: int = _int_env(
        "EMAIL_CODE_PER_DEVICE_PER_DAY", 30
    )
    max_devices_per_user: int = _int_env("MAX_DEVICES_PER_USER", 1)
    bonus_daily_spend_limit: int = _int_env("BONUS_DAILY_SPEND_LIMIT", 90)
    max_render_duration_seconds: int = _int_env("MAX_RENDER_DURATION_SECONDS", 600)
    scheduler_interval_seconds: int = _int_env("SCHEDULER_INTERVAL_SECONDS", 60)
    running_job_timeout_seconds: int = _int_env("RUNNING_JOB_TIMEOUT_SECONDS", 7200)
    uploading_job_timeout_seconds: int = _int_env(
        "UPLOADING_JOB_TIMEOUT_SECONDS",
        7200,
    )
    queued_job_timeout_seconds: int = _int_env("QUEUED_JOB_TIMEOUT_SECONDS", 86400)
    invalid_job_retention_seconds: int = _int_env(
        "INVALID_JOB_RETENTION_SECONDS",
        7 * 24 * 60 * 60,
    )
    preprocess_running_job_timeout_seconds: int = _int_env(
        "PREPROCESS_RUNNING_JOB_TIMEOUT_SECONDS",
        300,
    )
    rewrite_provider: str = os.getenv("REWRITE_PROVIDER", "deepseek").strip().lower()
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_timeout_seconds: int = _int_env("DEEPSEEK_TIMEOUT_SECONDS", 30)
    cloud_public_base_url: str = os.getenv("CLOUD_PUBLIC_BASE_URL", "https://api.example.com").strip()
    object_storage_backend: str = os.getenv("OBJECT_STORAGE_BACKEND", "local").strip().lower()
    object_storage_root: Path = Path(os.getenv("OBJECT_STORAGE_ROOT", "./data/object_storage"))
    object_storage_public_base_url: str = os.getenv("OBJECT_STORAGE_PUBLIC_BASE_URL", "").strip()
    object_storage_stale_input_cleanup_hours: int = _int_env(
        "OBJECT_STORAGE_STALE_INPUT_CLEANUP_HOURS",
        24,
    )
    cos_bucket: str = os.getenv("COS_BUCKET", "oral-video-agent-dev")
    cos_region: str = os.getenv("COS_REGION", "ap-guangzhou")
    cos_secret_id: str = os.getenv("COS_SECRET_ID", "")
    cos_secret_key: str = os.getenv("COS_SECRET_KEY", "")
    cos_scheme: str = os.getenv("COS_SCHEME", "https")
    cos_public_base_url: str = os.getenv("COS_PUBLIC_BASE_URL", "")
    cos_mock_secret: str = os.getenv("COS_MOCK_SECRET", "change-cos-mock-secret")
    cos_upload_url_expires_seconds: int = _int_env("COS_UPLOAD_URL_EXPIRES_SECONDS", 3600)
    cos_download_url_expires_seconds: int = _int_env("COS_DOWNLOAD_URL_EXPIRES_SECONDS", 3600)
    cos_cleanup_hours: int = _int_env("COS_CLEANUP_HOURS", 72)
    cos_download_confirm_delete_delay_hours: int = _int_env(
        "COS_DOWNLOAD_CONFIRM_DELETE_DELAY_HOURS",
        0,
    )


settings = Settings()
