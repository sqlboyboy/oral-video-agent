import os
import sys
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
    template_id: str = "renovation_pitfall_yellow"
    font_size: int = Field(default=64, ge=8, le=96)
    color: str = "#FFFFFF"
    keyword_color: Optional[str] = "#FFE23B"
    outline_color: str = "#111111"
    outline_width: int = Field(default=5, ge=0, le=8)
    font_family: str = "Microsoft YaHei"
    position: str = "bottom"
    margin_v: int = Field(default=510, ge=0, le=1200)
    position_x: float = Field(default=0.5, ge=0, le=1)
    position_y: float = Field(default=0.62, ge=0, le=1)
    max_chars_per_line: int = Field(default=9, ge=6, le=40)


class SubtitlePreviewRequest(BaseModel):
    script: str
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class RenderOptions(BaseModel):
    script: Optional[str] = None
    voice_id: str = "default-female"
    voice_volume: float = Field(default=0.45, ge=0, le=1)
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
    bgm_volume: float = Field(default=0.35, ge=0, le=1)
    subtitle_enabled: bool = True
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    pip_enabled: bool = False
    pip_asset_id: Optional[str] = None
    pip_position: str = "top_right"
    pip_scale: float = Field(default=0.28, ge=0.1, le=0.95)
    pip_x: float = Field(default=0.70, ge=0, le=1)
    pip_y: float = Field(default=0.03, ge=0, le=1)
    pip_width: float = Field(default=0.28, ge=0.05, le=1)
    pip_height: Optional[float] = Field(default=None, ge=0.03, le=1)
    pip_timing_mode: str = "full"
    pip_start_seconds: Optional[float] = Field(default=None, ge=0)
    pip_end_seconds: Optional[float] = Field(default=None, ge=0)
    pip_trigger_text: Optional[str] = None
    cover_path: Optional[str] = None
    defer_packaging: bool = False


class CreateTaskRequest(BaseModel):
    douyin_url: Optional[str] = None
    title: Optional[str] = None


class CreateScriptTaskRequest(BaseModel):
    title: Optional[str] = None
    original_script: str = ""
    rewritten_script: str = Field(min_length=1)


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None


class PostprocessVideoRequest(BaseModel):
    source_video_path: str
    options: RenderOptions


class RewriteRequest(BaseModel):
    style: str = "同款口播"
    source_script: Optional[str] = None
    product_info: str = ""
    target_audience: str = ""
    duration_seconds: Optional[int] = Field(default=None, ge=5, le=600)


class CreatorStyleProfile(BaseModel):
    creator_name: str = ""
    summary: str = ""
    tone: List[str] = Field(default_factory=list)
    hook_patterns: List[str] = Field(default_factory=list)
    structure_patterns: List[str] = Field(default_factory=list)
    language_features: List[str] = Field(default_factory=list)
    audience: str = ""
    cta_patterns: List[str] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    sec_uid: Optional[str] = None


class CreatorScriptCandidate(BaseModel):
    candidate_id: str
    title: str
    angle: str
    script: str
    reason: str = ""


class CreatorScriptGenerateRequest(BaseModel):
    share_text: str = Field(default="", max_length=5000)
    keyword: str = Field(min_length=1, max_length=100)
    count: int = Field(default=8, ge=8, le=8)
    duration_seconds: int = Field(default=60, ge=15, le=300)
    style_profile: Optional[CreatorStyleProfile] = None
    generation_round: int = Field(default=1, ge=1, le=100)
    exclude_titles: List[str] = Field(default_factory=list, max_length=100)
    exclude_scripts: List[str] = Field(default_factory=list, max_length=100)


class CreatorScriptBatchResponse(BaseModel):
    batch_id: str
    creator_name: str
    keyword: str
    generation_round: int
    style_profile: CreatorStyleProfile
    items: List[CreatorScriptCandidate]


class PublishRequest(BaseModel):
    platforms: List[str] = Field(default_factory=list)


class PublishContentSuggestion(BaseModel):
    title: str
    body: str
    topics: List[str] = Field(default_factory=list)


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
    ProgressStep(key="subtitle", label="4. 添加字幕/画中画"),
    ProgressStep(key="bgm", label="5. 添加背景音乐"),
    ProgressStep(key="digital_human", label="6. 数字人口播与成片合成"),
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
    cover_template_id: str = "bold-yellow-white"
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
    last_used_at: Optional[str] = None


class DigitalHumanProfile(BaseModel):
    digital_human_id: str
    name: str
    description: str
    built_in: bool = True
    asset_id: Optional[str] = None
    last_used_at: Optional[str] = None
    thumbnail_url: Optional[str] = None


class BgmTrack(BaseModel):
    bgm_id: str
    name: str
    mood: str
    built_in: bool = True
    asset_id: Optional[str] = None


def project_root() -> Path:
    configured = os.getenv("ORAL_VIDEO_AGENT_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def storage_dir(*parts: str) -> Path:
    path = project_root() / "storage" / Path(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
