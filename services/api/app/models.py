from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    created = "created"
    imported = "imported"
    transcribed = "transcribed"
    rewritten = "rewritten"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"


class SubtitleStyle(BaseModel):
    font_size: int = Field(default=42, ge=16, le=96)
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    position: str = "bottom"
    max_chars_per_line: int = Field(default=18, ge=8, le=40)


class RenderOptions(BaseModel):
    script: Optional[str] = None
    voice_id: str = "default-female"
    voice_reference_asset_id: Optional[str] = None
    bgm_id: Optional[str] = "default-light"
    bgm_volume: float = Field(default=0.18, ge=0, le=1)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class CreateTaskRequest(BaseModel):
    douyin_url: Optional[str] = None
    title: Optional[str] = None


class RewriteRequest(BaseModel):
    style: str = "同款口播"
    product_info: str = ""
    target_audience: str = ""
    duration_seconds: Optional[int] = Field(default=None, ge=5, le=600)


class Asset(BaseModel):
    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str
    filename: str
    path: str


class OralVideoTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    title: Optional[str] = None
    douyin_url: Optional[str] = None
    status: TaskStatus = TaskStatus.created
    source_video: Optional[Asset] = None
    extracted_audio_path: Optional[str] = None
    original_script: str = ""
    rewritten_script: str = ""
    render_options: Optional[RenderOptions] = None
    subtitle_path: Optional[str] = None
    output_video_path: Optional[str] = None
    error_message: Optional[str] = None


class VoiceProfile(BaseModel):
    voice_id: str
    name: str
    description: str
    built_in: bool = True
    asset_id: Optional[str] = None


class BgmTrack(BaseModel):
    bgm_id: str
    name: str
    mood: str
    built_in: bool = True
    asset_id: Optional[str] = None


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def storage_dir(*parts: str) -> Path:
    path = project_root() / "storage" / Path(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
