from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from ..models import storage_dir


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublisherPlatform(str, Enum):
    douyin = "douyin"
    kuaishou = "kuaishou"
    xiaohongshu = "xiaohongshu"
    shipinhao = "shipinhao"


class PublisherAccountStatus(str, Enum):
    created = "created"
    login_opened = "login_opened"
    logged_in = "logged_in"
    needs_login = "needs_login"
    needs_user_action = "needs_user_action"
    expired = "expired"
    failed = "failed"


class PublishJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    published = "published"
    drafted = "drafted"
    needs_user_action = "needs_user_action"
    failed = "failed"


class PublisherAccount(BaseModel):
    account_id: str = Field(default_factory=lambda: str(uuid4()))
    platform: PublisherPlatform
    nickname: str = ""
    status: PublisherAccountStatus = PublisherAccountStatus.created
    provider: str = "rpa"
    profile_dir: str = ""
    storage_state_path: str = ""
    last_checked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error_message: Optional[str] = None

    @field_validator("nickname", mode="before")
    @classmethod
    def normalize_nickname(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return ""


class PublishJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    platform: PublisherPlatform
    account_id: str
    status: PublishJobStatus = PublishJobStatus.queued
    video_path: str
    title: str
    body: str = ""
    topics: List[str] = Field(default_factory=list)
    publish_mode: str = "direct"
    cover_path: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    result_url: Optional[str] = None
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CreatePublisherAccountRequest(BaseModel):
    platform: PublisherPlatform
    nickname: str = ""
    provider: str = "rpa"

    @field_validator("nickname", mode="before")
    @classmethod
    def normalize_nickname(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return ""


class LoginPublisherAccountRequest(BaseModel):
    timeout_seconds: int = Field(default=300, ge=30, le=1800)


class PublishRequestV2(BaseModel):
    account_ids: List[str] = Field(default_factory=list)
    platforms: List[PublisherPlatform] = Field(default_factory=list)
    title: Optional[str] = None
    body: str = ""
    topics: List[str] = Field(default_factory=list)
    publish_mode: str = "direct"
    video_path: Optional[str] = None
    cover_path: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class PublisherAccountListResponse(BaseModel):
    items: List[PublisherAccount]


class PublishJobListResponse(BaseModel):
    items: List[PublishJob]


def publisher_profile_dir(account_id: str) -> Path:
    path = storage_dir("publisher", "profiles", account_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def publisher_state_path(account_id: str) -> Path:
    path = storage_dir("publisher", "states")
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{account_id}.json"


def publisher_screenshot_path(job_id: str) -> Path:
    path = storage_dir("publisher", "screenshots")
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{job_id}.png"


PLATFORM_LOGIN_URLS: Dict[PublisherPlatform, str] = {
    PublisherPlatform.douyin: "https://creator.douyin.com/creator-micro/content/upload",
    PublisherPlatform.kuaishou: "https://cp.kuaishou.com/",
    PublisherPlatform.xiaohongshu: "https://creator.xiaohongshu.com/publish/publish",
    PublisherPlatform.shipinhao: "https://channels.weixin.qq.com/platform/post/create",
}


PLATFORM_PUBLISH_URLS: Dict[PublisherPlatform, str] = {
    PublisherPlatform.douyin: "https://creator.douyin.com/creator-micro/content/upload",
    PublisherPlatform.kuaishou: "https://cp.kuaishou.com/article/publish/video",
    PublisherPlatform.xiaohongshu: "https://creator.xiaohongshu.com/publish/publish",
    PublisherPlatform.shipinhao: "https://channels.weixin.qq.com/platform/post/create",
}
