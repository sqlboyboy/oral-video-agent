from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import mimetypes
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .email_sender import create_email_sender
from .notifier import WebhookNotifier
from .object_storage import object_storage
from .redis_state import RedisState
from .rewrite import RewriteInput, rewrite_script
from .settings import settings
from .store import QueueStore, estimate_render_points, validate_password


app = FastAPI(title="Oral Video Agent Cloud", version="0.1.0")
store = QueueStore(settings.database_path, database_url=settings.database_url)
notifier = WebhookNotifier(settings.notify_webhook_url)
redis_state = RedisState(settings.redis_url)
email_sender = create_email_sender()


class JobCreateRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    job_type: str = "render"


class AdminLicenseKeyRequest(BaseModel):
    license_key: str | None = None
    max_activations: int = Field(default=1, ge=1, le=20)
    grant_points: int | None = Field(default=None, ge=0)
    expires_at: datetime | None = None


class AdminLicenseKeyUpdateRequest(BaseModel):
    expires_at: datetime | None


class AdminCreditCodeRequest(BaseModel):
    code: str | None = None
    points: int = Field(ge=1)


class AdminUserCreditRequest(BaseModel):
    points: int = Field(ge=1)
    note: str = ""


class AdminUserDebitRequest(BaseModel):
    points: int = Field(ge=1)
    note: str = ""


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AdminUserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    initial_points: int = Field(default=0, ge=0, le=100_000_000)


class AdminUserUpdateRequest(BaseModel):
    status: str | None = None
    license_status: str | None = None


class ClientActivationRequest(BaseModel):
    license_key: str
    device_fingerprint: str
    device_name: str = ""


class ClientEmailCodeRequest(BaseModel):
    email: str
    purpose: str = "register"
    device_fingerprint: str = ""


class ClientEmailLoginRequest(BaseModel):
    email: str
    code: str
    device_fingerprint: str
    device_name: str = ""


class ClientPasswordRegisterRequest(BaseModel):
    email: str
    code: str
    password: str
    device_name: str = ""
    device_fingerprint: str = ""


class ClientPasswordLoginRequest(BaseModel):
    email: str
    password: str
    device_name: str = ""
    device_fingerprint: str = ""


class ClientPasswordResetRequest(BaseModel):
    email: str
    code: str
    new_password: str
    device_name: str = ""
    device_fingerprint: str = ""


class ClientLicenseActivationRequest(BaseModel):
    license_key: str


class ClientCreditRedeemRequest(BaseModel):
    code: str


class ClientRenderEstimateRequest(BaseModel):
    duration_seconds: int = Field(gt=0)
    resolution: str = "1080p"


class ClientJobCreateRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: int = Field(gt=0)
    resolution: str = "1080p"
    job_type: str = "render"


class ClientAssetUploadSpec(BaseModel):
    kind: str = "source_video"
    file_name: str
    content_type: str = "application/octet-stream"
    file_size_bytes: int = Field(default=0, ge=0)


class ClientUploadSessionRequest(BaseModel):
    assets: list[ClientAssetUploadSpec] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    job_type: str = "render"


class ClientAssetUploadedRequest(BaseModel):
    file_size_bytes: int = Field(default=0, ge=0)


class ClientJobSubmitRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: int = Field(gt=0)
    resolution: str = "1080p"
    priority: int = 0


class ClientPreprocessJobRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class ClientRewriteRequest(BaseModel):
    source_script: str = Field(min_length=1)
    style: str = "同款口播"
    product_info: str = ""
    target_audience: str = ""
    max_chars: int = Field(default=300, ge=20, le=300)


class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    status: str = "idle"
    current_job_id: str | None = None
    message: str = ""


class WorkerClaimRequest(BaseModel):
    worker_id: str


class JobProgressRequest(BaseModel):
    worker_id: str
    percent: int = Field(ge=0, le=100)
    message: str = ""


class JobCompleteRequest(BaseModel):
    worker_id: str
    result: dict[str, Any] = Field(default_factory=dict)


class JobFailRequest(BaseModel):
    worker_id: str
    error_message: str


def _payload_source_script(payload: dict[str, Any]) -> str:
    return str(payload.get("source_script") or payload.get("original_script") or "").strip()


def _is_direct_rewrite_preprocess(payload: dict[str, Any]) -> bool:
    operation = str(payload.get("operation") or "").strip().lower()
    return operation == "rewrite" and bool(_payload_source_script(payload))


def _payload_max_chars(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("max_chars") or payload.get("maxChars") or 300)
    except (TypeError, ValueError):
        return 300


def _rewrite_result_from_payload(payload: dict[str, Any], *, user_id: str) -> dict[str, Any]:
    original_script = _payload_source_script(payload)
    rewritten = rewrite_script(
        RewriteInput(
            source_script=original_script,
            style=str(payload.get("style") or "同款口播"),
            product_info=str(payload.get("product_info") or ""),
            target_audience=str(payload.get("target_audience") or ""),
            max_chars=_payload_max_chars(payload),
        ),
        settings,
    )
    return {
        "mode": "direct_rewrite",
        "operation": "rewrite",
        "original_script": original_script,
        "rewritten_script": rewritten,
        "user_id": user_id,
    }


ADMIN_SESSION_COOKIE = "oral_video_admin_session"


def _create_admin_session() -> str:
    expires_at = int(time.time()) + 12 * 60 * 60
    payload = f"{settings.admin_username}|{expires_at}".encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.admin_token.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _valid_admin_session(value: str) -> bool:
    try:
        encoded, supplied_signature = value.rsplit(".", 1)
        expected_signature = hmac.new(
            settings.admin_token.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False
        padded = encoded + "=" * (-len(encoded) % 4)
        username, expires_text = base64.urlsafe_b64decode(padded).decode("utf-8").rsplit("|", 1)
        return hmac.compare_digest(username, settings.admin_username) and int(expires_text) > int(
            time.time()
        )
    except (ValueError, UnicodeDecodeError):
        return False


def require_admin(
    x_admin_token: str = Header(default=""),
    admin_session: str = Cookie(default="", alias=ADMIN_SESSION_COOKIE),
) -> None:
    valid_token = bool(settings.admin_token) and hmac.compare_digest(
        x_admin_token, settings.admin_token
    )
    if not valid_token and not _valid_admin_session(admin_session):
        raise HTTPException(status_code=401, detail="admin login required")


def require_worker(authorization: str = Header(default="")) -> None:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="missing worker token")
    token = authorization.removeprefix(prefix).strip()
    if not settings.worker_token or token != settings.worker_token:
        raise HTTPException(status_code=401, detail="invalid worker token")


def require_client(authorization: str = Header(default="")) -> dict[str, Any]:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="missing device token")
    token = authorization.removeprefix(prefix).strip()
    try:
        session = store.get_device_session(access_token=token)
    except KeyError:
        raise HTTPException(status_code=401, detail="invalid device token")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    _enforce_rate_limit(
        key=f"client:{session['device']['device_id']}",
        limit=settings.client_rate_limit_per_minute,
    )
    session["device_token"] = token
    return session


def require_device_activation(
    x_device_token: str = Header(default="", alias="X-Device-Token"),
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    token = x_device_token.strip()
    if not token and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing device activation token")
    try:
        activation = store.get_device_activation(access_token=token)
    except KeyError:
        raise HTTPException(status_code=401, detail="invalid device activation token")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    activation["activation_token"] = token
    return activation


def require_licensed_client(
    activation: dict[str, Any] = Depends(require_device_activation),
) -> dict[str, Any]:
    return activation


def require_cloud_account(
    session: dict[str, Any] = Depends(require_client),
    activation: dict[str, Any] = Depends(require_device_activation),
) -> dict[str, Any]:
    session["activation"] = activation
    return session


def _enforce_worker_rate_limit(worker_id: str) -> None:
    _enforce_rate_limit(
        key=f"worker:{worker_id}",
        limit=settings.worker_rate_limit_per_minute,
    )


def _enforce_rate_limit(
    *,
    key: str,
    limit: int,
    window_seconds: int = 60,
    detail: str = "rate limit exceeded",
) -> None:
    if not redis_state.allow_rate_limit(
        key=key,
        limit=limit,
        window_seconds=window_seconds,
    ):
        raise HTTPException(status_code=429, detail=detail)


def _require_local_object_storage() -> None:
    if not object_storage.using_local_storage:
        raise HTTPException(status_code=404, detail="local object storage is disabled")


def _verify_storage_signature(
    *,
    method: str,
    cos_key: str,
    expires: int,
    signature: str,
) -> None:
    try:
        object_storage.verify_signed_request(
            method=method,
            cos_key=cos_key,
            expires_at=expires,
            signature=signature,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "database_backend": store.backend,
        "redis": redis_state.health(),
    }


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_web() -> HTMLResponse:
    return HTMLResponse(Path(__file__).with_name("admin_web.html").read_text(encoding="utf-8"))


@app.post("/api/admin/session/login")
def admin_session_login(req: AdminLoginRequest, response: Response) -> dict[str, Any]:
    valid = hmac.compare_digest(req.username, settings.admin_username) and hmac.compare_digest(
        req.password, settings.admin_password
    )
    if not valid:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        _create_admin_session(),
        max_age=12 * 60 * 60,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"username": settings.admin_username}


@app.get("/api/admin/session", dependencies=[Depends(require_admin)])
def admin_session() -> dict[str, Any]:
    return {"username": settings.admin_username}


@app.post("/api/admin/session/logout")
def admin_session_logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return {"ok": True}


@app.put("/api/storage/objects/{cos_key:path}")
async def upload_storage_object(
    cos_key: str,
    request: Request,
    expires: int = Query(...),
    signature: str = Query(...),
) -> dict[str, Any]:
    _require_local_object_storage()
    _verify_storage_signature(
        method="PUT",
        cos_key=cos_key,
        expires=expires,
        signature=signature,
    )
    try:
        return await object_storage.save_upload_stream(
            cos_key=cos_key,
            stream=request.stream(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/storage/objects/{cos_key:path}")
@app.head("/api/storage/objects/{cos_key:path}")
async def download_storage_object(
    cos_key: str,
    expires: int = Query(...),
    signature: str = Query(...),
) -> FileResponse:
    _require_local_object_storage()
    _verify_storage_signature(
        method="GET",
        cos_key=cos_key,
        expires=expires,
        signature=signature,
    )
    try:
        path = object_storage.local_path_for_key(cos_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="object not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@app.post("/api/admin/jobs", dependencies=[Depends(require_admin)])
def create_job(req: JobCreateRequest) -> dict[str, Any]:
    job = store.create_job(payload=req.payload, priority=req.priority, job_type=req.job_type)
    redis_state.note_job_queued(job)
    maybe_notify_open_autodl()
    return job


@app.post("/api/admin/license-keys", dependencies=[Depends(require_admin)])
def create_license_key(req: AdminLicenseKeyRequest) -> dict[str, Any]:
    try:
        return store.create_license_key(
            license_key=req.license_key,
            max_activations=req.max_activations,
            grant_points=req.grant_points
            if req.grant_points is not None
            else settings.license_activation_grant_points,
            expires_at=req.expires_at.isoformat() if req.expires_at else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/admin/license-keys", dependencies=[Depends(require_admin)])
def list_license_keys(limit: int = 100) -> dict[str, Any]:
    return {"items": store.list_license_keys(limit=limit)}


@app.patch("/api/admin/license-keys/{license_key}", dependencies=[Depends(require_admin)])
def update_license_key(license_key: str, req: AdminLicenseKeyUpdateRequest) -> dict[str, Any]:
    try:
        return store.update_license_key(
            license_key=license_key,
            expires_at=req.expires_at.isoformat() if req.expires_at else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="license key not found")


@app.get("/api/admin/dashboard", dependencies=[Depends(require_admin)])
def admin_dashboard() -> dict[str, Any]:
    return store.admin_dashboard()


@app.post("/api/admin/credit-codes", dependencies=[Depends(require_admin)])
def create_credit_code(req: AdminCreditCodeRequest) -> dict[str, Any]:
    try:
        return store.create_credit_code(code=req.code, points=req.points)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/admin/users", dependencies=[Depends(require_admin)])
def list_users(email: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"items": store.list_users(email=email, limit=max(1, min(limit, 200)))}


@app.post("/api/admin/users", dependencies=[Depends(require_admin)])
def create_admin_user(req: AdminUserCreateRequest) -> dict[str, Any]:
    try:
        return store.create_admin_user(email=req.email, initial_points=req.initial_points)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if "exists" in detail else 400, detail=detail) from exc


@app.get("/api/admin/users/{user_id}", dependencies=[Depends(require_admin)])
def get_admin_user(user_id: str) -> dict[str, Any]:
    try:
        return store.get_user_detail(user_id=user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="user not found")


@app.post("/api/admin/users/{user_id}/credits", dependencies=[Depends(require_admin)])
def add_admin_user_credits(user_id: str, req: AdminUserCreditRequest) -> dict[str, Any]:
    try:
        return store.add_user_credits(user_id=user_id, points=req.points, note=req.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/users/{user_id}/debits", dependencies=[Depends(require_admin)])
def deduct_admin_user_credits(user_id: str, req: AdminUserDebitRequest) -> dict[str, Any]:
    try:
        return store.deduct_user_credits(user_id=user_id, points=req.points, note=req.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/admin/users/{user_id}", dependencies=[Depends(require_admin)])
def update_admin_user(user_id: str, req: AdminUserUpdateRequest) -> dict[str, Any]:
    try:
        return store.update_user(
            user_id=user_id,
            status=req.status,
            license_status=req.license_status,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/users/{user_id}/devices/reset", dependencies=[Depends(require_admin)])
def reset_admin_user_devices(user_id: str) -> dict[str, Any]:
    try:
        return store.reset_user_devices(user_id=user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="user not found")


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def list_jobs(
    limit: int = 50,
    job_status: str | None = Query(default=None, alias="status"),
    q: str | None = None,
) -> dict[str, Any]:
    allowed_statuses = {"uploading", "queued", "running", "completed", "failed", "canceled", "timed_out"}
    if job_status and job_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="invalid job status")
    return {
        "items": store.list_jobs(
            limit=max(1, min(limit, 500)),
            job_status=job_status,
            query=q,
        ),
        "summary": store.admin_job_summary(),
    }


@app.get("/api/admin/jobs/{job_id}", dependencies=[Depends(require_admin)])
def get_admin_job(job_id: str) -> dict[str, Any]:
    try:
        return store.get_admin_job_detail(job_id=job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")


@app.get("/api/admin/queue", dependencies=[Depends(require_admin)])
def queue_status() -> dict[str, Any]:
    stats = store.queue_stats(worker_stale_seconds=settings.worker_stale_seconds)
    stats["redis"] = redis_state.queue_snapshot()
    return stats


@app.post("/api/admin/notify-check", dependencies=[Depends(require_admin)])
def notify_check(force: bool = False) -> dict[str, Any]:
    return maybe_notify_open_autodl(force=force)


def _send_email_code(req: ClientEmailCodeRequest, *, device_rate_key: str) -> dict[str, Any]:
    email = req.email.strip().lower()
    purpose = req.purpose.strip().lower()
    if purpose not in {"register", "reset_password"}:
        raise HTTPException(status_code=400, detail="invalid email code purpose")
    try:
        has_password = store.email_account_has_password(email=email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if purpose == "register" and has_password:
        raise HTTPException(status_code=409, detail="账号已存在，请直接使用密码登录")
    if purpose == "reset_password" and not has_password:
        raise HTTPException(status_code=404, detail="该邮箱尚未注册密码账号")
    _enforce_rate_limit(
        key=f"email-code:email-hour:{email}",
        limit=settings.email_code_per_email_per_hour,
        window_seconds=3600,
        detail="该邮箱验证码发送次数过多，请一小时后再试",
    )
    _enforce_rate_limit(
        key=f"email-code:device-hour:{device_rate_key}",
        limit=settings.email_code_per_device_per_hour,
        window_seconds=3600,
        detail="当前设备验证码发送次数过多，请一小时后再试",
    )
    _enforce_rate_limit(
        key=f"email-code:device-day:{device_rate_key}",
        limit=settings.email_code_per_device_per_day,
        window_seconds=86400,
        detail="当前设备今日验证码发送次数已达上限，请明天再试",
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        item = store.create_email_login_code(
            email=req.email,
            code=code,
            ttl_seconds=settings.email_code_ttl_seconds,
            resend_seconds=settings.email_code_resend_seconds,
        )
        email_sender.send_login_code(
            email=req.email.strip().lower(),
            code=code,
            ttl_minutes=max(1, settings.email_code_ttl_seconds // 60),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    response = {
        "sent": True,
        "email": req.email.strip().lower(),
        "purpose": purpose,
        "expires_at": item["expires_at"],
        "resend_seconds": settings.email_code_resend_seconds,
    }
    if settings.email_provider == "console":
        response["debug_code"] = code
    return response


def _mobile_fingerprint(value: str) -> str:
    fingerprint = value.strip()
    if len(fingerprint) < 16 or len(fingerprint) > 200:
        raise HTTPException(status_code=400, detail="invalid mobile device fingerprint")
    return fingerprint


def _mobile_device_limit() -> int:
    # Keep the configured desktop allowance and reserve one additional slot
    # for the currently active Android installation.
    return max(2, settings.max_devices_per_user + 1)


def _mobile_permission_detail(exc: PermissionError) -> str:
    return {
        "device limit reached": "设备数量已达上限，请退出旧设备后重试",
        "mobile device limit reached": "手机设备数量已达上限，请重新登录后重试",
        "user account is disabled": "账号已被停用，请联系管理员",
        "mobile access is disabled": "手机端访问已被停用，请联系管理员",
    }.get(str(exc), str(exc))


def _provision_mobile_session(session: dict[str, Any]) -> dict[str, Any]:
    store.ensure_mobile_access(
        user_id=str(session["user"]["user_id"]),
        device_id=str(session["device"]["device_id"]),
        max_activations=_mobile_device_limit(),
    )
    return session


@app.post("/api/client/auth/email-code")
def send_client_email_code(
    req: ClientEmailCodeRequest,
    session: dict[str, Any] = Depends(require_licensed_client),
) -> dict[str, Any]:
    return _send_email_code(
        req,
        device_rate_key=str(session["device"]["device_id"]),
    )


@app.post("/api/mobile/auth/email-code")
def send_mobile_email_code(req: ClientEmailCodeRequest) -> dict[str, Any]:
    fingerprint = _mobile_fingerprint(req.device_fingerprint)
    fingerprint_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return _send_email_code(req, device_rate_key=f"mobile:{fingerprint_key}")


@app.post("/api/client/auth/register")
def register_client_with_password(
    req: ClientPasswordRegisterRequest,
    activation: dict[str, Any] = Depends(require_licensed_client),
) -> dict[str, Any]:
    try:
        validate_password(req.password)
        if store.email_account_has_password(email=req.email):
            raise HTTPException(status_code=409, detail="账号已存在，请直接登录")
        session = store.login_with_email_code(
            email=req.email,
            code=req.code,
            device_fingerprint=activation["device"]["device_fingerprint"],
            device_name=req.device_name,
            max_attempts=settings.email_code_max_attempts,
            max_devices=settings.max_devices_per_user,
        )
        session["user"] = store.set_user_password(
            user_id=session["user"]["user_id"],
            password=req.password,
        )
        return session
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/client/auth/password-login")
def login_client_with_password(
    req: ClientPasswordLoginRequest,
    activation: dict[str, Any] = Depends(require_licensed_client),
) -> dict[str, Any]:
    email_key = hashlib.sha256(req.email.strip().lower().encode("utf-8")).hexdigest()
    device_id = str(activation["device"]["device_id"])
    _enforce_rate_limit(
        key=f"password-login:{device_id}:{email_key}",
        limit=10,
        window_seconds=900,
        detail="登录尝试次数过多，请 15 分钟后再试",
    )
    try:
        return store.login_with_password(
            email=req.email,
            password=req.password,
            device_fingerprint=activation["device"]["device_fingerprint"],
            device_name=req.device_name,
            max_devices=settings.max_devices_per_user,
        )
    except KeyError:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/client/auth/password-reset")
def reset_client_password(
    req: ClientPasswordResetRequest,
    activation: dict[str, Any] = Depends(require_licensed_client),
) -> dict[str, Any]:
    try:
        validate_password(req.new_password)
        if not store.email_account_has_password(email=req.email):
            raise HTTPException(status_code=404, detail="该邮箱尚未注册密码账号")
        session = store.login_with_email_code(
            email=req.email,
            code=req.code,
            device_fingerprint=activation["device"]["device_fingerprint"],
            device_name=req.device_name,
            max_attempts=settings.email_code_max_attempts,
            max_devices=settings.max_devices_per_user,
        )
        session["user"] = store.set_user_password(
            user_id=session["user"]["user_id"],
            password=req.new_password,
        )
        return session
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/mobile/auth/register")
def register_mobile_with_password(
    req: ClientPasswordRegisterRequest,
) -> dict[str, Any]:
    fingerprint = _mobile_fingerprint(req.device_fingerprint)
    try:
        validate_password(req.password)
        if store.email_account_has_password(email=req.email):
            raise HTTPException(status_code=409, detail="账号已存在，请直接登录")
        session = store.login_with_email_code(
            email=req.email,
            code=req.code,
            device_fingerprint=fingerprint,
            device_name=req.device_name,
            max_attempts=settings.email_code_max_attempts,
            max_devices=_mobile_device_limit(),
            replace_device_prefix="android-",
        )
        session["user"] = store.set_user_password(
            user_id=session["user"]["user_id"],
            password=req.password,
        )
        return _provision_mobile_session(session)
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=_mobile_permission_detail(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/mobile/auth/password-login")
def login_mobile_with_password(
    req: ClientPasswordLoginRequest,
) -> dict[str, Any]:
    fingerprint = _mobile_fingerprint(req.device_fingerprint)
    email_key = hashlib.sha256(req.email.strip().lower().encode("utf-8")).hexdigest()
    device_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    _enforce_rate_limit(
        key=f"mobile-password-login:{device_key}:{email_key}",
        limit=10,
        window_seconds=900,
        detail="登录尝试次数过多，请 15 分钟后再试",
    )
    try:
        session = store.login_with_password(
            email=req.email,
            password=req.password,
            device_fingerprint=fingerprint,
            device_name=req.device_name,
            max_devices=_mobile_device_limit(),
            replace_device_prefix="android-",
        )
        return _provision_mobile_session(session)
    except KeyError:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=_mobile_permission_detail(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/mobile/auth/password-reset")
def reset_mobile_password(
    req: ClientPasswordResetRequest,
) -> dict[str, Any]:
    fingerprint = _mobile_fingerprint(req.device_fingerprint)
    try:
        validate_password(req.new_password)
        if not store.email_account_has_password(email=req.email):
            raise HTTPException(status_code=404, detail="该邮箱尚未注册密码账号")
        session = store.login_with_email_code(
            email=req.email,
            code=req.code,
            device_fingerprint=fingerprint,
            device_name=req.device_name,
            max_attempts=settings.email_code_max_attempts,
            max_devices=_mobile_device_limit(),
            replace_device_prefix="android-",
        )
        session["user"] = store.set_user_password(
            user_id=session["user"]["user_id"],
            password=req.new_password,
        )
        return _provision_mobile_session(session)
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=_mobile_permission_detail(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/client/auth/login")
def login_client_with_email(
    req: ClientEmailLoginRequest,
    activation: dict[str, Any] = Depends(require_licensed_client),
) -> dict[str, Any]:
    _enforce_rate_limit(
        key=f"activate:{req.device_fingerprint}",
        limit=settings.client_rate_limit_per_minute,
    )
    try:
        return store.login_with_email_code(
            email=req.email,
            code=req.code,
            device_fingerprint=activation["device"]["device_fingerprint"],
            device_name=req.device_name,
            max_attempts=settings.email_code_max_attempts,
            max_devices=settings.max_devices_per_user,
        )
    except KeyError:
        raise HTTPException(status_code=400, detail="invalid or expired email code")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/client/activate")
def activate_client(req: ClientActivationRequest) -> dict[str, Any]:
    _enforce_rate_limit(
        key=f"activate:{req.device_fingerprint}",
        limit=settings.client_rate_limit_per_minute,
    )
    try:
        return store.activate_license(
            license_key=req.license_key,
            device_fingerprint=req.device_fingerprint,
            device_name=req.device_name,
            max_devices_per_user=settings.max_devices_per_user,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="license key not found")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/client/activation")
def client_activation(
    activation: dict[str, Any] = Depends(require_device_activation),
) -> dict[str, Any]:
    return activation


@app.post("/api/client/license/activate")
def activate_client_license(
    req: ClientLicenseActivationRequest,
    session: dict[str, Any] = Depends(require_client),
) -> dict[str, Any]:
    try:
        return store.activate_user_license(
            user_id=session["user"]["user_id"],
            device_id=session["device"]["device_id"],
            license_key=req.license_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="license key not found")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/client/me")
def client_me(session: dict[str, Any] = Depends(require_client)) -> dict[str, Any]:
    return session


@app.get("/api/client/credits/ledger")
def client_credit_ledger(
    limit: int = 50,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    user_id = session["user"]["user_id"]
    return {
        "wallet": store.get_wallet(user_id=user_id),
        "items": store.list_credit_ledger(user_id=user_id, limit=limit),
    }


@app.post("/api/client/credits/redeem")
def redeem_client_credit_code(
    req: ClientCreditRedeemRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        return store.redeem_credit_code(
            user_id=session["user"]["user_id"],
            code=req.code,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="credit code not found or already redeemed")


@app.post("/api/client/jobs/estimate")
def estimate_client_job(
    req: ClientRenderEstimateRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    if req.duration_seconds > settings.max_render_duration_seconds:
        raise HTTPException(status_code=400, detail="single cloud job is limited to 10 minutes")
    try:
        points = estimate_render_points(
            duration_seconds=req.duration_seconds,
            resolution=req.resolution,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    wallet = store.get_wallet(user_id=session["user"]["user_id"])
    return {
        "duration_seconds": req.duration_seconds,
        "resolution": req.resolution,
        "estimated_points": points,
        "wallet": wallet,
        "enough_credits": wallet["available_points"] >= points,
    }


@app.get("/api/client/jobs")
def list_client_jobs(
    limit: int = 50,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    return {
        "items": store.list_client_jobs(
            user_id=session["user"]["user_id"],
            limit=limit,
        )
    }


@app.post("/api/client/jobs")
def create_client_job(
    req: ClientJobCreateRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.create_client_job(
            user_id=session["user"]["user_id"],
            payload=req.payload,
            duration_seconds=req.duration_seconds,
            resolution=req.resolution,
            max_duration_seconds=settings.max_render_duration_seconds,
            daily_bonus_limit=settings.bonus_daily_spend_limit,
            job_type=req.job_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    redis_state.note_job_queued(job)
    maybe_notify_open_autodl()
    return job


@app.post("/api/client/jobs/upload-session")
def create_client_upload_session(
    req: ClientUploadSessionRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.create_upload_session(
            user_id=session["user"]["user_id"],
            assets=[asset.model_dump() for asset in req.assets],
            payload=req.payload,
            job_type=req.job_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _with_upload_urls(job)


@app.get("/api/client/jobs/{job_id}")
def get_client_job(
    job_id: str,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        return store.get_client_job_with_assets(
            user_id=session["user"]["user_id"],
            job_id=job_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")


@app.post("/api/client/jobs/{job_id}/assets/{asset_id}/uploaded")
def mark_client_asset_uploaded(
    job_id: str,
    asset_id: str,
    req: ClientAssetUploadedRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        return store.mark_asset_uploaded(
            user_id=session["user"]["user_id"],
            job_id=job_id,
            asset_id=asset_id,
            file_size_bytes=req.file_size_bytes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="asset not found")


@app.post("/api/client/jobs/{job_id}/submit")
def submit_client_job(
    job_id: str,
    req: ClientJobSubmitRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.submit_uploaded_job(
            job_id=job_id,
            user_id=session["user"]["user_id"],
            payload=req.payload,
            duration_seconds=req.duration_seconds,
            resolution=req.resolution,
            max_duration_seconds=settings.max_render_duration_seconds,
            daily_bonus_limit=settings.bonus_daily_spend_limit,
            priority=req.priority,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    redis_state.note_job_queued(job)
    maybe_notify_open_autodl()
    return job


@app.get("/api/client/jobs/{job_id}/download")
def get_client_job_download_url(
    job_id: str,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        output_key = store.get_completed_output_key(
            user_id=session["user"]["user_id"],
            job_id=job_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="output not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "download": object_storage.presign_download(cos_key=output_key).as_dict(),
        "cleanup_after_hours": settings.cos_cleanup_hours,
    }


@app.post("/api/client/jobs/{job_id}/download-confirmed")
def confirm_client_job_downloaded(
    job_id: str,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.confirm_output_downloaded(
            user_id=session["user"]["user_id"],
            job_id=job_id,
            delete_delay_hours=settings.cos_download_confirm_delete_delay_hours,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="output not found")
    deleted_outputs = 0
    if settings.cos_download_confirm_delete_delay_hours <= 0:
        deleted_outputs = _delete_job_assets(job, output_only=True)
        if deleted_outputs:
            job = store.get_client_job_with_assets(
                user_id=session["user"]["user_id"],
                job_id=job_id,
            )
    return {
        "job": job,
        "delete_delay_hours": settings.cos_download_confirm_delete_delay_hours,
        "deleted_outputs": deleted_outputs,
    }


@app.post("/api/client/jobs/{job_id}/cancel")
def cancel_client_job(
    job_id: str,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.cancel_client_job(job_id=job_id, user_id=session["user"]["user_id"])
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    deleted_assets = _delete_job_assets(job, include_outputs=True)
    if deleted_assets:
        job = store.get_client_job_with_assets(
            user_id=session["user"]["user_id"],
            job_id=job_id,
        )
    redis_state.note_job_finished(job)
    return job


@app.post("/api/client/preprocess/jobs")
def create_client_preprocess_job(
    req: ClientPreprocessJobRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    if _is_direct_rewrite_preprocess(req.payload):
        try:
            result = _rewrite_result_from_payload(
                req.payload,
                user_id=session["user"]["user_id"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return store.create_completed_preprocess_job(
            user_id=session["user"]["user_id"],
            payload=req.payload,
            result=result,
            priority=req.priority,
            progress_message="Direct rewrite completed",
        )
    job = store.create_client_preprocess_job(
        user_id=session["user"]["user_id"],
        payload=req.payload,
        priority=req.priority,
    )
    redis_state.note_job_queued(job)
    maybe_notify_open_autodl()
    return job


@app.post("/api/client/rewrite")
def rewrite_client_script(
    req: ClientRewriteRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        return _rewrite_result_from_payload(
            {
                "operation": "rewrite",
                "source_script": req.source_script,
                "style": req.style,
                "product_info": req.product_info,
                "target_audience": req.target_audience,
                "max_chars": req.max_chars,
            },
            user_id=session["user"]["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/client/preprocess/upload-session")
def create_client_preprocess_upload_session(
    req: ClientUploadSessionRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.create_upload_session(
            user_id=session["user"]["user_id"],
            assets=[asset.model_dump() for asset in req.assets],
            payload=req.payload,
            job_type="preprocess",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _with_upload_urls(job)


@app.post("/api/client/preprocess/jobs/{job_id}/submit")
def submit_client_preprocess_job(
    job_id: str,
    req: ClientPreprocessJobRequest,
    session: dict[str, Any] = Depends(require_cloud_account),
) -> dict[str, Any]:
    try:
        job = store.submit_uploaded_preprocess_job(
            job_id=job_id,
            user_id=session["user"]["user_id"],
            payload=req.payload,
            priority=req.priority,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    redis_state.note_job_queued(job)
    maybe_notify_open_autodl()
    return job


@app.post("/api/worker/heartbeat", dependencies=[Depends(require_worker)])
def worker_heartbeat(req: WorkerHeartbeatRequest) -> dict[str, Any]:
    _enforce_worker_rate_limit(req.worker_id)
    return store.heartbeat(
        worker_id=req.worker_id,
        status=req.status,
        current_job_id=req.current_job_id,
        message=req.message,
    )


@app.post("/api/worker/claim-job", dependencies=[Depends(require_worker)])
def claim_job(req: WorkerClaimRequest) -> dict[str, Any]:
    _enforce_worker_rate_limit(req.worker_id)
    job = store.claim_job(worker_id=req.worker_id)
    if job is None:
        return {"job": None, "queue": queue_status()}
    job = _with_worker_storage_urls(job)
    redis_state.note_job_running(job, worker_id=req.worker_id)
    store.heartbeat(
        worker_id=req.worker_id,
        status="running",
        current_job_id=job["job_id"],
        message="claimed job",
    )
    return {"job": job}


@app.post("/api/worker/jobs/{job_id}/progress", dependencies=[Depends(require_worker)])
def job_progress(job_id: str, req: JobProgressRequest) -> dict[str, Any]:
    _enforce_worker_rate_limit(req.worker_id)
    try:
        return store.update_progress(
            job_id=job_id,
            worker_id=req.worker_id,
            percent=req.percent,
            message=req.message,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="running job not found")


@app.post("/api/worker/jobs/{job_id}/complete", dependencies=[Depends(require_worker)])
def job_complete(job_id: str, req: JobCompleteRequest) -> dict[str, Any]:
    _enforce_worker_rate_limit(req.worker_id)
    try:
        output_expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=settings.cos_cleanup_hours)
        ).isoformat()
        job = store.complete_job(
            job_id=job_id,
            worker_id=req.worker_id,
            result=req.result,
            output_expires_at=output_expires_at,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="running job not found")
    deleted_inputs = _delete_job_assets(job, include_outputs=False)
    if deleted_inputs:
        job = store.get_job_with_assets(job_id)
    redis_state.note_job_finished(job)
    maybe_notify_shutdown_autodl()
    return job


@app.post("/api/worker/jobs/{job_id}/fail", dependencies=[Depends(require_worker)])
def job_fail(job_id: str, req: JobFailRequest) -> dict[str, Any]:
    _enforce_worker_rate_limit(req.worker_id)
    try:
        job = store.fail_job(
            job_id=job_id,
            worker_id=req.worker_id,
            error_message=req.error_message,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="running job not found")
    deleted_assets = _delete_job_assets(job, include_outputs=True)
    if deleted_assets:
        job = store.get_job_with_assets(job_id)
    redis_state.note_job_finished(job)
    maybe_notify_shutdown_autodl()
    return job


@app.get("/api/worker/queue", dependencies=[Depends(require_worker)])
def worker_queue_status() -> dict[str, Any]:
    return queue_status()


def _delete_job_assets(
    job: dict[str, Any],
    *,
    include_outputs: bool = False,
    output_only: bool = False,
) -> int:
    deleted = 0
    for asset in job.get("assets", []):
        kind = str(asset.get("kind") or "")
        if output_only and kind != "output":
            continue
        if not output_only and not include_outputs and kind == "output":
            continue
        if asset.get("deleted_at"):
            continue
        if str(asset.get("status") or "") not in {"uploaded", "downloaded"}:
            continue
        cos_key = str(asset.get("cos_key") or "")
        if not cos_key:
            continue
        try:
            object_storage.delete_object(cos_key=cos_key)
            store.mark_asset_deleted(asset_id=str(asset["asset_id"]))
            deleted += 1
        except Exception:
            continue
    return deleted


def _with_upload_urls(job: dict[str, Any]) -> dict[str, Any]:
    items = []
    for asset in job.get("assets", []):
        item = dict(asset)
        item["upload"] = object_storage.presign_upload(
            cos_key=asset["cos_key"],
            content_type=asset.get("content_type") or "application/octet-stream",
        ).as_dict()
        items.append(item)
    result = dict(job)
    result["assets"] = items
    return result


def _worker_output_metadata(job: dict[str, Any]) -> tuple[str, str]:
    payload = dict(job.get("payload") or {})
    operation = str(payload.get("operation") or "").strip().lower()
    if job.get("job_type") == "preprocess" and operation == "voice":
        return "result.wav", "audio/wav"
    return "result.mp4", "video/mp4"


def _with_worker_storage_urls(job: dict[str, Any]) -> dict[str, Any]:
    result = dict(job)
    assets = store.list_job_assets(job_id=job["job_id"])
    input_assets = []
    for asset in assets:
        if asset["kind"] == "output":
            continue
        item = dict(asset)
        item["download"] = object_storage.presign_download(cos_key=asset["cos_key"]).as_dict()
        input_assets.append(item)
    user_id = job.get("user_id") or "admin"
    output_file_name, output_content_type = _worker_output_metadata(job)
    output_key = object_storage.output_key(
        user_id=user_id,
        job_id=job["job_id"],
        file_name=output_file_name,
    )
    result["input_assets"] = input_assets
    result["output_upload"] = object_storage.presign_upload(
        cos_key=output_key,
        content_type=output_content_type,
    ).as_dict()
    payload = dict(result.get("payload") or {})
    payload["input_assets"] = input_assets
    payload["output_cos_key"] = output_key
    payload["output_file_name"] = output_file_name
    payload["output_content_type"] = output_content_type
    payload["output_upload"] = result["output_upload"]
    result["payload"] = payload
    return result


def maybe_notify_open_autodl(*, force: bool = False) -> dict[str, Any]:
    stats = store.queue_stats(worker_stale_seconds=settings.worker_stale_seconds)
    should_notify = (
        stats["queued"] >= settings.notify_queued_threshold
        or stats["oldest_wait_seconds"] >= settings.notify_wait_minutes_threshold * 60
    )
    if not should_notify and not force:
        return {"sent": False, "reason": "threshold_not_reached", "stats": stats}
    if not settings.notify_webhook_url:
        return {"sent": False, "reason": "webhook_not_configured", "stats": stats}
    if not store.notification_allowed(
        key="open_autodl",
        cooldown_seconds=0 if force else settings.notify_cooldown_seconds,
    ):
        return {"sent": False, "reason": "cooldown", "stats": stats}
    minutes = stats["oldest_wait_seconds"] // 60
    sent = notifier.send_text(
        "口播云端队列需要 AutoDL 算力\n"
        f"排队任务：{stats['queued']}\n"
        f"运行任务：{stats['running']}\n"
        f"最长等待：{minutes} 分钟\n"
        "请打开 AutoDL 4090 实例，worker 会自动拉取任务。"
    )
    return {"sent": sent, "reason": "notified" if sent else "webhook_not_configured", "stats": stats}


def maybe_notify_shutdown_autodl() -> dict[str, Any]:
    stats = store.queue_stats(worker_stale_seconds=settings.worker_stale_seconds)
    if stats["queued"] > 0 or stats["running"] > 0:
        return {"sent": False, "reason": "queue_not_empty", "stats": stats}
    if not settings.notify_webhook_url:
        return {"sent": False, "reason": "webhook_not_configured", "stats": stats}
    if not store.notification_allowed(
        key="shutdown_autodl",
        cooldown_seconds=settings.notify_cooldown_seconds,
    ):
        return {"sent": False, "reason": "cooldown", "stats": stats}
    sent = notifier.send_text("口播云端队列已清空，可以关闭 AutoDL 实例。")
    return {"sent": sent, "reason": "notified" if sent else "webhook_not_configured", "stats": stats}
