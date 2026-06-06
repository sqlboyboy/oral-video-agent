from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
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


class SubtitlePreviewRequest(BaseModel):
    script: str
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class RenderOptions(BaseModel):
    script: Optional[str] = None
    voice_id: str = "default-female"
    voice_reference_asset_id: Optional[str] = None
    digital_human_id: Optional[str] = None
    digital_human_engine: Optional[str] = None
    mouth_aperture_enabled: Optional[bool] = None
    mouth_aperture_strength: Optional[float] = Field(default=None, ge=0, le=1)
    mouth_aperture_energy_threshold: Optional[float] = Field(default=None, ge=0, le=0.85)
    mouth_aperture_min_ratio: Optional[float] = Field(default=None, ge=0, le=0.8)
    mouth_aperture_max_ratio: Optional[float] = Field(default=None, ge=0, le=0.8)
    mouth_aperture_attack: Optional[float] = Field(default=None, ge=0, le=1)
    mouth_aperture_release: Optional[float] = Field(default=None, ge=0, le=1)
    motion_mode: str = "auto"
    expression_mode: str = "auto"
    bgm_id: Optional[str] = "default-light"
    bgm_volume: float = Field(default=0.18, ge=0, le=1)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class CreateTaskRequest(BaseModel):
    douyin_url: Optional[str] = None
    title: Optional[str] = None


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None


class RewriteRequest(BaseModel):
    style: str = "同款口播"
    source_script: Optional[str] = None
    product_info: str = ""
    target_audience: str = ""
    duration_seconds: Optional[int] = Field(default=None, ge=5, le=600)


class PublishRequest(BaseModel):
    platforms: List[str] = Field(default_factory=list)


class Asset(BaseModel):
    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str
    filename: str
    path: str


class ProgressStep(BaseModel):
    key: str
    label: str
    status: str = "pending"


DEFAULT_PROGRESS_STEPS = [
    ProgressStep(key="extract", label="1. 对标文案提取"),
    ProgressStep(key="rewrite", label="2. 文案仿写"),
    ProgressStep(key="voice", label="3. 声音克隆/合成"),
    ProgressStep(key="digital_human", label="4. 数字人口播"),
    ProgressStep(key="subtitle", label="5. 添加字幕"),
    ProgressStep(key="bgm", label="6. 添加背景音乐"),
    ProgressStep(key="title", label="7. 生成标题"),
    ProgressStep(key="cover", label="8. 生成封面"),
    ProgressStep(key="publish", label="9. 多平台发布"),
]


def initial_progress_steps() -> List[ProgressStep]:
    return [step.model_copy() for step in DEFAULT_PROGRESS_STEPS]


class TaskSummary(BaseModel):
    task_id: str
    title: Optional[str]
    status: TaskStatus
    douyin_url: Optional[str]
    output_ready: bool = False


class MouthQualitySignals(BaseModel):
    mouth_state_path: Optional[str] = None
    mouth_diagnosis_path: Optional[str] = None
    verdict: Optional[str] = None
    mouth_state_alignment_verdict: Optional[str] = None
    low_energy_visible_gap_ratio: Optional[float] = None
    high_energy_muted_open_ratio: Optional[float] = None
    high_energy_mean_ratio: Optional[float] = None
    vowel_muted_ratio: Optional[float] = None
    vowel_mean_ratio: Optional[float] = None


class OralVideoTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    title: Optional[str] = None
    douyin_url: Optional[str] = None
    status: TaskStatus = TaskStatus.created
    progress_steps: List[ProgressStep] = Field(default_factory=initial_progress_steps)
    source_video: Optional[Asset] = None
    extracted_audio_path: Optional[str] = None
    original_script: str = ""
    rewritten_script: str = ""
    render_options: Optional[RenderOptions] = None
    subtitle_path: Optional[str] = None
    video_title: Optional[str] = None
    cover_path: Optional[str] = None
    publish_results: Dict[str, str] = Field(default_factory=dict)
    output_video_path: Optional[str] = None
    mouth_quality: Optional[MouthQualitySignals] = None
    error_message: Optional[str] = None


class VoiceProfile(BaseModel):
    voice_id: str
    name: str
    description: str
    built_in: bool = True
    asset_id: Optional[str] = None


class DigitalHumanProfile(BaseModel):
    digital_human_id: str
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
