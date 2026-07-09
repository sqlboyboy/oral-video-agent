import threading
import threading
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from ..models import storage_dir
from ..pipeline.renderer import is_playable_mp4
from ..repository import repo
from .models import (
    CreatePublisherAccountRequest,
    LoginPublisherAccountRequest,
    PublishJob,
    PublishJobListResponse,
    PublishJobStatus,
    PublishRequestV2,
    PublisherAccount,
    PublisherAccountListResponse,
    PublisherAccountStatus,
    publisher_profile_dir,
    publisher_state_path,
    utc_now,
)
from .providers import get_provider
from .store import publisher_store


router = APIRouter(prefix="/api", tags=["publisher"])


def _limit_title(value: str, max_chars: int = 20) -> str:
    return "".join(list(value.strip())[:max_chars])


@router.get("/publisher/accounts")
def list_publisher_accounts() -> PublisherAccountListResponse:
    return PublisherAccountListResponse(items=publisher_store.list_accounts())


@router.post("/publisher/accounts")
def create_publisher_account(req: CreatePublisherAccountRequest) -> PublisherAccount:
    nickname = req.nickname.strip()
    if nickname:
        existing = publisher_store.find_account_by_platform_and_nickname(
            req.platform.value,
            nickname,
        )
        if existing is not None:
            return existing
    else:
        for existing in reversed(publisher_store.list_accounts()):
            if existing.platform == req.platform and not existing.nickname.strip() and existing.status != PublisherAccountStatus.logged_in:
                return existing
    account = PublisherAccount(
        platform=req.platform,
        nickname=nickname,
        provider=req.provider.strip() or "rpa",
        status=PublisherAccountStatus.needs_login,
    )
    account.profile_dir = str(publisher_profile_dir(account.account_id))
    account.storage_state_path = str(publisher_state_path(account.account_id))
    return publisher_store.put_account(account)


@router.post("/publisher/accounts/{account_id}/login")
def login_publisher_account(
    account_id: str,
    req: LoginPublisherAccountRequest = LoginPublisherAccountRequest(),
) -> PublisherAccount:
    account = _get_account_or_404(account_id)
    return get_provider(account).login(account, req.timeout_seconds)


@router.post("/publisher/accounts/{account_id}/check-session")
def check_publisher_account_session(account_id: str) -> PublisherAccount:
    account = _get_account_or_404(account_id)
    return get_provider(account).check_session(account)


@router.get("/publish-jobs")
def list_publish_jobs() -> PublishJobListResponse:
    return PublishJobListResponse(items=publisher_store.list_jobs())


@router.post("/publisher/reset-local-state")
def reset_publisher_local_state():
    publisher_store.clear_all()
    publisher_root = storage_dir("publisher")
    for child in ("profiles", "states", "screenshots"):
        path = publisher_root / child
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
    return {"ok": True}


@router.get("/publish-jobs/{job_id}")
def get_publish_job(job_id: str) -> PublishJob:
    try:
        return publisher_store.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="发布任务不存在")


@router.post("/tasks/{task_id}/publish-jobs")
def create_publish_jobs(task_id: str, req: PublishRequestV2) -> PublishJobListResponse:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")

    video_path = _resolve_publish_video_path(task.output_video_path, req.video_path)
    if not video_path:
        raise HTTPException(status_code=409, detail="请先生成可发布的视频")
    if not is_playable_mp4(video_path):
        raise HTTPException(status_code=409, detail="成品视频不是可发布的 MP4")

    accounts = _select_accounts(req)
    if not accounts:
        raise HTTPException(status_code=409, detail="没有匹配的发布账号，请先添加并登录账号")

    title = _limit_title(req.title or task.video_title or task.title or "未命名口播视频")
    body = req.body.strip() or task.rewritten_script or task.original_script
    jobs: List[PublishJob] = []
    for account in accounts:
        job = PublishJob(
            task_id=task_id,
            platform=account.platform,
            account_id=account.account_id,
            video_path=video_path,
            title=title,
            body=body,
            topics=[topic.strip().lstrip("#") for topic in req.topics if topic.strip()],
            publish_mode=req.publish_mode,
            cover_path=req.cover_path or task.cover_path,
            scheduled_at=req.scheduled_at,
        )
        publisher_store.put_job(job)
        jobs.append(job)
        threading.Thread(target=_run_publish_job, args=(job.job_id,), daemon=True).start()

    task.publish_results = {
        **task.publish_results,
        **{job.platform.value: f"发布任务已创建：{job.job_id}" for job in jobs},
    }
    repo.put(task)
    return PublishJobListResponse(items=jobs)


def _resolve_publish_video_path(
    task_video_path: str | None,
    request_video_path: str | None,
) -> str | None:
    for candidate in (request_video_path, task_video_path):
        clean = (candidate or "").strip()
        if clean and Path(clean).exists():
            return clean
    return None


def _run_publish_job(job_id: str) -> None:
    try:
        job = publisher_store.get_job(job_id)
        account = publisher_store.get_account(job.account_id)
        job.status = PublishJobStatus.running
        job.updated_at = utc_now()
        publisher_store.put_job(job)
        result = get_provider(account).publish(account, job)
        _sync_task_publish_result(result)
    except Exception as exc:
        try:
            job = publisher_store.get_job(job_id)
            job.status = PublishJobStatus.failed
            job.error_message = str(exc)
            job.updated_at = utc_now()
            publisher_store.put_job(job)
            _sync_task_publish_result(job)
        except Exception:
            pass


def _sync_task_publish_result(job: PublishJob) -> None:
    try:
        task = repo.get(job.task_id)
    except KeyError:
        return
    detail = job.status.value
    if job.error_message:
        detail = f"{detail}: {job.error_message}"
    task.publish_results[job.platform.value] = detail
    repo.put(task)


def _select_accounts(req: PublishRequestV2) -> List[PublisherAccount]:
    accounts = publisher_store.list_accounts()
    if req.account_ids:
        requested = set(req.account_ids)
        return [account for account in accounts if account.account_id in requested]
    if req.platforms:
        requested_platforms = set(req.platforms)
        return [account for account in accounts if account.platform in requested_platforms]
    return accounts


def _get_account_or_404(account_id: str) -> PublisherAccount:
    try:
        return publisher_store.get_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="发布账号不存在")
