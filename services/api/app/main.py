import json
import math
import re
import shutil
import struct
import subprocess
import threading
import wave
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .asset_store import asset_store, ensure_voice_reference_wav, save_upload
from .models import BgmTrack, CreateScriptTaskRequest, CreateTaskRequest, CreatorScriptBatchResponse, CreatorScriptGenerateRequest, DigitalHumanProfile, OralVideoTask, PostprocessVideoRequest, PublishContentSuggestion, PublishRequest, RenderOptions, RewriteRequest, SubtitlePreviewRequest, TaskStatus, TaskSummary, UpdateTaskRequest, VoiceProfile, project_root, storage_dir
from .mouth_quality import build_mouth_quality_report, collect_mouth_quality_signals
from .pipeline.cover import (
    COVER_TEMPLATES,
    DEFAULT_COVER_TEMPLATE,
    extract_first_frame_cover_png,
    generate_cover_png,
)
from .pipeline.renderer import (
    LOUDNESS_NORMALIZATION_FILTER,
    Renderer,
    _ffmpeg_executable,
    is_playable_mp4,
    media_duration_seconds,
    prepare_video_for_audio_duration,
)
from .progress import complete_progress, fail_progress, start_progress
from .pipeline.subtitles import generate_ass, preview_subtitles, subtitle_time_range_for_text
from .pipeline.subtitle_templates import SUBTITLE_TEMPLATES
from .providers.asr import create_asr_provider
from .providers.catalog import BUILT_IN_BGM, BUILT_IN_VOICES
from .providers.creator_scripts import create_creator_script_provider, format_spoken_script
from .providers.digital_human import create_digital_human_provider
from .providers.douyin_creator import (
    DouyinCreatorCollector,
    DouyinCreatorFetchError,
    DouyinCreatorInputError,
)
from .providers.rewrite import create_rewrite_provider
from .providers.rewrite_styles import REWRITE_STYLE_PRESETS
from .providers.tts import create_voice_provider
from .providers.video_importer import VideoImportError, VideoImporter, extract_first_url
from .publisher import router as publisher_router
from .repository import repo
from .settings import get_settings
import sys
import asyncio
import mimetypes
import os
from urllib.parse import urlencode

# 修复 Windows 下 Python 3.13+ 运行 Playwright 报错 NotImplementedError 的问题
if sys.platform == 'win32':
    # 强制设置事件循环策略
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(
    title="智能口播智能体 API",
    version="0.1.0",
    openapi_tags=[
        {"name": "system", "description": "服务健康和 provider 配置"},
        {"name": "assets", "description": "声音、BGM、源视频等素材管理"},
        {"name": "subtitles", "description": "字幕预览和样式能力"},
        {"name": "tasks", "description": "口播视频任务创建、仿写、合成和下载"},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(publisher_router)

settings = get_settings()
asr_provider = create_asr_provider(settings)
rewrite_provider = create_rewrite_provider(settings)
creator_script_provider = create_creator_script_provider(settings)
voice_provider = create_voice_provider(settings)
digital_human_provider = create_digital_human_provider(settings)
video_importer = VideoImporter()
douyin_creator_collector = DouyinCreatorCollector()
renderer = Renderer()

DIGITAL_HUMAN_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_TEMPLATE_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".mkv", ".webm"}
render_cancel_events: Dict[str, threading.Event] = {}
RECENT_USAGE_PATH = Path(
    os.getenv("RECENT_USAGE_PATH", storage_dir("assets") / "recent_asset_usage.json")
)
SYSTEM_OPTION_LIMIT = 4
RECENT_USER_OPTION_LIMIT = 10
MIN_DIGITAL_HUMAN_REFERENCE_BYTES = 1024
VOICE_TEMPLATE_ORDER = {
    "标准女生": 0,
    "标准男声": 1,
    "温和男声": 2,
    "元气女生": 3,
}


def _subtitle_timing_tokens(audio_path: str | Path | None):
    """Best-effort word timing; final rendering still works if ASR is unavailable."""

    if audio_path is None:
        return []
    try:
        return asr_provider.transcribe_timed(Path(audio_path))
    except Exception:
        return []
BGM_TEMPLATE_ORDER = {
    "宣传类口播": 0,
    "通用类口播": 1,
}


def limit_title(value: str, max_chars: int = 20) -> str:
    return "".join(list(value.strip())[:max_chars])


def generate_title(script: str) -> str:
    cleaned = script.replace("\n", "，").strip(" ，。")
    if not cleaned:
        return "爆款口播视频"
    first = cleaned.split("，")[0].strip()
    if len(first) >= 8:
        return limit_title(first)
    return limit_title(f"{first}，一起见证成长")


def _fallback_publish_content(script: str) -> PublishContentSuggestion:
    cleaned = re.sub(r"\s+", "", script).strip()
    body = script.strip()
    return PublishContentSuggestion(
        title=generate_title(cleaned),
        body=body[:220],
        topics=_fallback_topics(cleaned),
    )


def _fallback_topics(script: str) -> list[str]:
    candidates = ["口播", "短视频", "情绪价值"]
    if any(word in script for word in ["成长", "努力", "坚持"]):
        candidates.append("成长")
    if any(word in script for word in ["别人", "自己", "人生", "人家"]):
        candidates.append("人生感悟")
    if any(word in script for word in ["产品", "服务", "客户", "转化"]):
        candidates.append("创业")
    result: list[str] = []
    for topic in candidates:
        if topic not in result:
            result.append(topic)
    return result[:5]


def _extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("LLM response content is empty")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if match:
        cleaned = match.group(0)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return data


def generate_publish_content(script: str) -> PublishContentSuggestion:
    if settings.rewrite_provider.strip().lower() not in {"deepseek", "deepseek-api"}:
        return _fallback_publish_content(script)
    if not settings.deepseek_api_key:
        return _fallback_publish_content(script)

    prompt = (
        "你是中文短视频发布运营助手。请基于口播文案生成适合抖音、快手、小红书的视频发布信息。\n"
        "必须只输出 JSON，不要输出解释、Markdown 或代码块。\n"
        "JSON 格式：{\"title\":\"...\",\"body\":\"...\",\"topics\":[\"...\"]}\n\n"
        "要求：\n"
        "1. title 是视频标题，12-20 个中文字符，绝对不能超过20个字，不要使用夸张违规词，不要带 #。\n"
        "2. body 是发布正文，保留原文核心观点，口语化，80-160 个中文字符，可适当换行。\n"
        "3. topics 生成 4-6 个中文话题词，不带 #，不要重复，不要过长。\n"
        "4. 不要编造产品、人物、承诺、疗效、收益或平台数据。\n\n"
        f"口播文案：\n{script.strip()}"
    )
    response = requests.post(
        f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你只输出严格 JSON，用于短视频平台发布表单。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 800,
            "stream": False,
        },
        timeout=settings.deepseek_timeout_seconds,
    )
    response.raise_for_status()
    response_data = response.json()
    message = response_data["choices"][0]["message"]
    content = message.get("content") or ""
    if not content.strip():
        content = json.dumps(message, ensure_ascii=False)
    data = _extract_json_object(content)
    title = str(data.get("title") or "").strip().strip("#")
    body = str(data.get("body") or "").strip()
    raw_topics = data.get("topics") or []
    if isinstance(raw_topics, str):
        raw_topics = re.split(r"[\s,#，、]+", raw_topics)
    topics = [
        str(topic).strip().lstrip("#")
        for topic in raw_topics
        if str(topic).strip().lstrip("#")
    ]
    deduped_topics: list[str] = []
    for topic in topics:
        if topic not in deduped_topics:
            deduped_topics.append(topic)
    for topic in _fallback_topics(script):
        if len(deduped_topics) >= 4:
            break
        if topic not in deduped_topics:
            deduped_topics.append(topic)
    return PublishContentSuggestion(
        title=limit_title(title) or generate_title(script),
        body=body[:260] or script.strip()[:220],
        topics=deduped_topics[:6] or _fallback_topics(script),
    )


def custom_asset_path(value: Optional[str], expected_kind: str) -> Optional[Path]:
    if not value or not value.startswith("custom:"):
        return None
    asset_id = value.removeprefix("custom:")
    try:
        asset = asset_store.get(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="自定义素材不存在")
    if asset.kind != expected_kind:
        raise HTTPException(status_code=400, detail="自定义素材类型不匹配")
    if expected_kind == "voice_reference":
        try:
            asset = ensure_voice_reference_wav(asset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return Path(asset.path)


def custom_asset_id_path(asset_id: Optional[str], expected_kind: str) -> Optional[Path]:
    if not asset_id:
        return None
    try:
        asset = asset_store.get(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="自定义素材不存在")
    if asset.kind != expected_kind:
        raise HTTPException(status_code=400, detail="自定义素材类型不匹配")
    if expected_kind == "voice_reference":
        try:
            asset = ensure_voice_reference_wav(asset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return Path(asset.path)


def ensure_not_cancelled(task: OralVideoTask, cancel_event: threading.Event) -> None:
    if cancel_event.is_set():
        task.status = TaskStatus.failed
        task.error_message = "用户已停止生成"
        repo.put(task)
        raise RuntimeError("用户已停止生成")


def selected_digital_human_provider(engine: Optional[str]):
    configured = settings.digital_human_provider.strip().lower()
    if configured in {"heygem", "heygem-local", "duix-heygem"}:
        return "heygem-local", digital_human_provider
    return configured or "heygem-local", digital_human_provider


def preset_assets_dir(name: str) -> Path:
    configured = os.getenv("ORAL_VIDEO_AGENT_PRESET_ROOT")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser().resolve() / name)
    root = project_root()
    candidates.extend([root / name, root.parent / name])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else root / name


def clone_voice_templates_dir() -> Path:
    return preset_assets_dir("clone")


def bgm_templates_dir() -> Path:
    return preset_assets_dir("bgm")


def _template_sort_key(path: Path, order: Dict[str, int]) -> tuple[int, str]:
    return (order.get(path.stem, len(order)), path.stem)


def voice_reference_path(
    voice_id: Optional[str],
    voice_reference_asset_id: Optional[str] = None,
) -> Optional[Path]:
    if voice_id and voice_id.startswith("clone:"):
        filename = voice_id.removeprefix("clone:")
        candidate = clone_voice_templates_dir() / filename
        if not candidate.exists() or candidate.suffix.lower() not in AUDIO_TEMPLATE_EXTS:
            raise HTTPException(status_code=404, detail="克隆声音模板不存在")
        return candidate
    reference = custom_asset_path(voice_id, "voice_reference")
    if reference is not None:
        return reference
    return custom_asset_id_path(voice_reference_asset_id, "voice_reference")


def _safe_cache_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "preview"


def _write_builtin_voice_preview(path: Path, voice_id: str) -> None:
    presets = {
        "classic-female": 440.0,
        "classic-male": 220.0,
        "warm-narrator": 330.0,
        "energetic-host": 520.0,
    }
    sample_rate = 16000
    duration_seconds = 1.2
    total_samples = int(sample_rate * duration_seconds)
    frequency = presets.get(voice_id, 330.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(total_samples):
            t = index / sample_rate
            envelope = min(1.0, index / (sample_rate * 0.08))
            envelope *= min(1.0, (total_samples - index) / (sample_rate * 0.12))
            value = 0.22 * math.sin(2 * math.pi * frequency * t) * envelope
            wav.writeframesraw(struct.pack("<h", int(value * 32767)))


def resolve_voice_preview_audio(voice_id: Optional[str]) -> Path:
    if not voice_id:
        raise HTTPException(status_code=400, detail="请选择声音")
    reference = voice_reference_path(voice_id)
    if reference is not None:
        if not reference.exists():
            raise HTTPException(status_code=404, detail="声音文件不存在")
        return reference
    if any(voice.voice_id == voice_id for voice in BUILT_IN_VOICES):
        output = storage_dir("voice_previews") / f"{_safe_cache_name(voice_id)}.wav"
        if output.exists() and output.stat().st_size > 44:
            return output
        try:
            voice_provider.synthesize("你好，这是一段声音试听。", voice_id, output)
            if output.exists() and output.stat().st_size > 44:
                return output
        except Exception:
            pass
        _write_builtin_voice_preview(output, voice_id)
        return output
    raise HTTPException(status_code=404, detail="声音不存在")


def ensure_voice_preview_wav(path: Path, voice_id: str) -> Path:
    return ensure_loudness_preview_wav(path, "voice_previews", voice_id)


def ensure_loudness_preview_wav(
    path: Path,
    cache_group: str,
    cache_id: str,
    *,
    required: bool = False,
) -> Path:
    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        if required:
            raise RuntimeError("FFmpeg 未配置，无法统一试听与成片的音频响度")
        return path
    try:
        stat = path.stat()
        stamp = f"{stat.st_mtime_ns}_{stat.st_size}"
    except OSError:
        stamp = "0_0"
    output = storage_dir(cache_group) / (
        f"{_safe_cache_name(cache_id)}_{stamp}_lufs16.wav"
    )
    if output.exists() and output.stat().st_size > 44:
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-vn",
                "-af",
                LOUDNESS_NORMALIZATION_FILTER,
                "-ar",
                "44100",
                str(output),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        output.unlink(missing_ok=True)
        if required:
            raise RuntimeError(f"音频响度归一化失败：{exc}") from exc
        return path
    if completed.returncode == 0 and output.exists() and output.stat().st_size > 44:
        return output
    output.unlink(missing_ok=True)
    if required:
        detail = completed.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"音频响度归一化失败：{detail or completed.returncode}")
    return path


def digital_human_templates_dir() -> Path:
    if settings.digital_human_templates_dir:
        path = Path(settings.digital_human_templates_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return storage_dir("digital_humans", "templates")


def digital_human_reference_path(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    if value.startswith("template:"):
        filename = value.removeprefix("template:")
        candidate = digital_human_templates_dir() / filename
        if not candidate.exists() or candidate.suffix.lower() not in DIGITAL_HUMAN_VIDEO_EXTS:
            raise HTTPException(status_code=404, detail="数字人动作模板不存在")
        return candidate
    return custom_asset_path(value, "digital_human_reference")


@app.get("/api/health", tags=["system"])
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/version", tags=["system"])
def version():
    return {"name": "oral-video-agent-api", "version": app.version}


@app.get("/api/providers", tags=["system"])
def provider_status():
    ffmpeg_configured = bool(_ffmpeg_executable())
    wav2lip_model = Path(settings.wav2lip_onnx_model)
    wav2lip_available = wav2lip_model.exists() and wav2lip_model.is_file()
    aperture_atlas_source = (settings.wav2lip_aperture_atlas_source or "").strip()
    aperture_atlas_enabled = (
        settings.wav2lip_blend_enabled
        and settings.wav2lip_aperture_atlas_strength > 0
        and (bool(aperture_atlas_source) or wav2lip_available)
    )
    heygem_online = False
    if settings.digital_human_provider.strip().lower() in {"heygem", "heygem-local", "duix-heygem"}:
        try:
            response = requests.get(f"{settings.heygem_base_url.rstrip('/')}/api/health", timeout=2)
            heygem_online = response.ok and response.json().get("gpu_available") is True
        except Exception:
            heygem_online = False
    voice_online = False
    if settings.voice_provider.strip().lower() in {"remote-cosyvoice", "cosyvoice-remote"}:
        try:
            response = requests.get(f"{settings.voice_base_url.rstrip('/')}/api/health", timeout=2)
            voice_online = response.ok and response.json().get("gpu_available") is True
        except Exception:
            voice_online = False
    return {
        "rewrite_provider": settings.rewrite_provider,
        "deepseek_model": settings.deepseek_model if settings.rewrite_provider == "deepseek" else None,
        "deepseek_configured": settings.rewrite_provider == "deepseek" and bool(settings.deepseek_api_key),
        "deepseek_base_url": settings.deepseek_base_url if settings.rewrite_provider == "deepseek" else None,
        "asr_provider": settings.asr_provider,
        "whisper_model": settings.whisper_model if settings.asr_provider == "faster-whisper" else None,
        "voice_provider": settings.voice_provider,
        "voice_configured": settings.voice_provider == "placeholder"
        or (
            settings.voice_provider.strip().lower() in {"remote-cosyvoice", "cosyvoice-remote"}
            and voice_online
        )
        or bool(settings.tts_api_key)
        or bool(settings.voice_clone_command),
        "voice_online": voice_online,
        "voice_base_url": settings.voice_base_url
        if settings.voice_provider.strip().lower() in {"remote-cosyvoice", "cosyvoice-remote"}
        else None,
        "digital_human_provider": settings.digital_human_provider,
        "digital_human_configured": ffmpeg_configured and (
            heygem_online
            if settings.digital_human_provider.strip().lower() in {"heygem", "heygem-local", "duix-heygem"}
            else True
        ),
        "digital_human_mode": "heygem-local",
        "liveportrait_configured": False,
        "liveportrait_detector": settings.liveportrait_detector,
        "heygem_online": heygem_online,
        "heygem_base_url": settings.heygem_base_url,
        "wav2lip_onnx_configured": wav2lip_available,
        "wav2lip_onnx_model": str(wav2lip_model),
        "wav2lip_blend_enabled": settings.wav2lip_blend_enabled,
        "wav2lip_blend_preset": settings.wav2lip_blend_preset,
        "wav2lip_aperture_atlas_enabled": aperture_atlas_enabled,
        "wav2lip_aperture_atlas_source": aperture_atlas_source or None,
        "wav2lip_aperture_atlas_source_mode": "explicit" if aperture_atlas_source else "reference-video",
        "wav2lip_aperture_atlas_strength": settings.wav2lip_aperture_atlas_strength,
        "wav2lip_aperture_energy_threshold": settings.wav2lip_aperture_energy_threshold,
        "wav2lip_aperture_min_ratio": settings.wav2lip_aperture_min_ratio,
        "wav2lip_aperture_max_ratio": settings.wav2lip_aperture_max_ratio,
        "wav2lip_aperture_attack": settings.wav2lip_aperture_attack,
        "wav2lip_aperture_release": settings.wav2lip_aperture_release,
        "wav2lip_quality_diagnostics_enabled": settings.wav2lip_quality_diagnostics_enabled,
        "wav2lip_quality_diagnostics_sample_stride": settings.wav2lip_quality_diagnostics_sample_stride,
        "wav2lip_quality_diagnostics_max_frames": settings.wav2lip_quality_diagnostics_max_frames,
        "ffmpeg_configured": bool(_ffmpeg_executable()),
    }


@app.get("/api/digital-human/health", tags=["system"])
def digital_human_health():
    provider = provider_status()
    return {
        "provider": provider["digital_human_provider"],
        "configured": provider["digital_human_configured"],
        "ffmpeg_path": _ffmpeg_executable(),
        "high_quality": {
            "mode": provider["digital_human_mode"],
            "heygem_online": provider["heygem_online"],
            "heygem_base_url": settings.heygem_base_url,
            "heygem_data_dir": settings.heygem_data_dir,
            "wav2lip_onnx_model": settings.wav2lip_onnx_model,
            "wav2lip_onnx_configured": provider["wav2lip_onnx_configured"],
            "mouth_aperture": {
                "blend_enabled": provider["wav2lip_blend_enabled"],
                "blend_preset": provider["wav2lip_blend_preset"],
                "atlas_enabled": provider["wav2lip_aperture_atlas_enabled"],
                "atlas_source": provider["wav2lip_aperture_atlas_source"],
                "atlas_source_mode": provider["wav2lip_aperture_atlas_source_mode"],
                "atlas_strength": provider["wav2lip_aperture_atlas_strength"],
                "energy_threshold": provider["wav2lip_aperture_energy_threshold"],
                "min_ratio": provider["wav2lip_aperture_min_ratio"],
                "max_ratio": provider["wav2lip_aperture_max_ratio"],
                "attack": provider["wav2lip_aperture_attack"],
                "release": provider["wav2lip_aperture_release"],
                "quality_diagnostics": {
                    "enabled": provider["wav2lip_quality_diagnostics_enabled"],
                    "sample_stride": provider["wav2lip_quality_diagnostics_sample_stride"],
                    "max_frames": provider["wav2lip_quality_diagnostics_max_frames"],
                },
            },
            "fallback": "simple-mouth-sync",
            "description": "Uses a local Wav2Lip ONNX model when present. No Wav2Lip weights are bundled.",
        },
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_recent_usage() -> Dict[str, List[Dict[str, str]]]:
    if not RECENT_USAGE_PATH.exists():
        return {}
    try:
        data = json.loads(RECENT_USAGE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    usage: Dict[str, List[Dict[str, str]]] = {}
    for kind in ("voice", "digital_human", "bgm"):
        raw_items = data.get(kind, [])
        if not isinstance(raw_items, list):
            continue
        usage[kind] = [
            item
            for item in raw_items
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("used_at"), str)
        ]
    return usage


def _save_recent_usage(usage: Dict[str, List[Dict[str, str]]]) -> None:
    RECENT_USAGE_PATH.write_text(
        json.dumps(usage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _record_recent_usage(kind: str, item_id: Optional[str]) -> None:
    if not item_id or not item_id.startswith("custom:"):
        return
    usage = _load_recent_usage()
    current = [item for item in usage.get(kind, []) if item.get("id") != item_id]
    current.insert(0, {"id": item_id, "used_at": _utc_now_iso()})
    usage[kind] = current[:50]
    _save_recent_usage(usage)


def _remove_recent_usage(kind: str, item_id: Optional[str]) -> None:
    if not item_id:
        return
    usage = _load_recent_usage()
    current = usage.get(kind, [])
    filtered = [item for item in current if item.get("id") != item_id]
    if len(filtered) != len(current):
        usage[kind] = filtered
        _save_recent_usage(usage)


def _fallback_usage_order(kind: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for index, task in enumerate(repo.list()):
        options = task.render_options
        if options is None:
            continue
        if kind == "voice":
            item_id = options.voice_id
        elif kind == "digital_human":
            item_id = options.digital_human_id
        elif kind == "bgm":
            item_id = options.bgm_id
        else:
            item_id = None
        if item_id and item_id.startswith("custom:"):
            values[item_id] = f"task-order:{index:08d}"
    return values


def _recent_custom_items(
    kind: str,
    items: List[VoiceProfile] | List[DigitalHumanProfile],
) -> List[VoiceProfile] | List[DigitalHumanProfile]:
    usage_by_id = {
        item["id"]: item["used_at"]
        for item in _load_recent_usage().get(kind, [])
        if item.get("id")
    }

    def item_id(item: VoiceProfile | DigitalHumanProfile) -> str:
        if isinstance(item, VoiceProfile):
            return item.voice_id
        return item.digital_human_id

    deduped: Dict[str, VoiceProfile | DigitalHumanProfile] = {}
    for item in items:
        key = item_id(item)
        if key in deduped:
            continue
        used_at = usage_by_id.get(key)
        if used_at is None:
            continue
        item.last_used_at = used_at
        deduped[key] = item

    ordered = list(deduped.values())
    ordered.sort(key=_custom_usage_sort_key, reverse=True)
    result: List[VoiceProfile] | List[DigitalHumanProfile] = []
    seen_names: set[str] = set()
    for item in ordered:
        name_key = item.name.strip().lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        result.append(item)
        if len(result) >= RECENT_USER_OPTION_LIMIT:
            break
    return result


def _dedupe_recent_profiles(
    items: List[VoiceProfile] | List[DigitalHumanProfile],
) -> List[VoiceProfile] | List[DigitalHumanProfile]:
    result: List[VoiceProfile] | List[DigitalHumanProfile] = []
    seen_names: set[str] = set()
    for item in items:
        name_key = item.name.strip().lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        result.append(item)
        if len(result) >= RECENT_USER_OPTION_LIMIT:
            break
    return result


def _custom_usage_sort_key(item: VoiceProfile | DigitalHumanProfile) -> tuple[int, float, str]:
    value = item.last_used_at or ""
    if value.startswith("task-order:"):
        try:
            return (1, float(value.removeprefix("task-order:")), "")
        except ValueError:
            return (1, 0.0, value)
    try:
        return (2, float(value), "")
    except ValueError:
        pass
    if value:
        return (3, 0.0, value)
    return (0, 0.0, "")


def _custom_usage_value(kind: str, item_id: str) -> Optional[str]:
    usage_by_id = {
        item["id"]: item["used_at"]
        for item in _load_recent_usage().get(kind, [])
        if item.get("id")
    }
    used_at = usage_by_id.get(item_id)
    if used_at is not None:
        return used_at
    return None


def _usage_sort_key(value: Optional[str]) -> tuple[int, float, str]:
    if not value:
        return (0, 0.0, "")
    if value.startswith("task-order:"):
        try:
            return (1, float(value.removeprefix("task-order:")), "")
        except ValueError:
            return (1, 0.0, value)
    try:
        return (2, float(value), "")
    except ValueError:
        return (3, 0.0, value)


@app.get("/api/voices", tags=["assets"])
def list_voices():
    return build_voice_catalog()


@app.get("/api/voices/preview", tags=["assets"])
def preview_voice(voice_id: str):
    path = resolve_voice_preview_audio(voice_id)
    path = ensure_voice_preview_wav(path, voice_id)
    _record_recent_usage("voice", voice_id)
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "audio/wav",
    )


def build_voice_catalog():
    clone_templates = (
        sorted(
            (
                path
                for path in clone_voice_templates_dir().iterdir()
                if path.is_file() and path.suffix.lower() in AUDIO_TEMPLATE_EXTS
            ),
            key=lambda path: _template_sort_key(path, VOICE_TEMPLATE_ORDER),
        )
        if clone_voice_templates_dir().exists()
        else []
    )
    template_voices = [
        VoiceProfile(
            voice_id=f"clone:{path.name}",
            name=path.stem,
            description="系统克隆声音模板",
            built_in=True,
        )
        for path in clone_templates
    ]
    assets = [
        asset
        for asset in asset_store.list("voice_reference")
        if Path(asset.path).exists() and Path(asset.path).stat().st_size > 1024
    ]
    custom_voices = [
        VoiceProfile(
            voice_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的授权声音参考",
            built_in=False,
            asset_id=asset.asset_id,
        )
        for asset in assets
    ]
    return {
        "items": [
            *template_voices,
            *BUILT_IN_VOICES[: max(0, SYSTEM_OPTION_LIMIT - len(template_voices))],
            *_recent_custom_items("voice", custom_voices),
        ]
    }


@app.post("/api/voices/upload", tags=["assets"])
def upload_voice_reference(file: UploadFile = File(...)):
    try:
        asset = save_upload(file, "voice_refs", "voice_reference")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        asset = ensure_voice_reference_wav(asset)
    except ValueError:
        # Keep upload permissive for files that need manual inspection; preview
        # and synthesis will report a clear decode error if the audio is invalid.
        pass
    duration_seconds = media_duration_seconds(Path(asset.path))
    if duration_seconds is not None and duration_seconds > 300:
        try:
            Path(asset.path).unlink(missing_ok=True)
        finally:
            asset_store.delete(asset.asset_id)
        raise HTTPException(status_code=400, detail="声音参考文件最长不能超过 5 分钟")
    voice_id = f"custom:{asset.asset_id}"
    _record_recent_usage("voice", voice_id)
    return {
        "asset": asset,
        "voice": VoiceProfile(
            voice_id=voice_id,
            name=Path(asset.filename).stem,
            description="用户上传的授权声音参考",
            built_in=False,
            asset_id=asset.asset_id,
        ),
    }


@app.post("/api/pip/upload", tags=["assets"])
def upload_pip_asset(file: UploadFile = File(...)):
    try:
        asset = save_upload(file, "pip", "pip")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"asset": asset}


@app.get("/api/pip/{asset_id}/preview", tags=["assets"])
def preview_pip_asset(asset_id: str):
    try:
        asset = asset_store.get(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="画中画素材不存在")
    if asset.kind != "pip":
        raise HTTPException(status_code=400, detail="画中画素材类型不匹配")
    path = Path(asset.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="画中画素材文件不存在")
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


@app.get("/api/digital-humans", tags=["assets"])
def list_digital_humans():
    return build_digital_human_catalog()


def build_digital_human_catalog():
    templates = sorted(
        path
        for path in digital_human_templates_dir().iterdir()
        if path.is_file() and path.suffix.lower() in DIGITAL_HUMAN_VIDEO_EXTS
    )
    built_in_templates = [
        DigitalHumanProfile(
            digital_human_id=f"template:{path.name}",
            name=path.stem,
            description="本地真人参考视频，用于高清模式生成",
            built_in=True,
        )
        for path in templates
    ]
    for profile, path in zip(built_in_templates, templates):
        profile.last_used_at = datetime.fromtimestamp(
            path.stat().st_mtime, timezone.utc
        ).isoformat()
        try:
            digital_human_thumbnail_path(profile.digital_human_id)
        except Exception:
            pass
        profile.thumbnail_url = digital_human_thumbnail_url(
            profile.digital_human_id,
            profile.last_used_at,
        )
    custom_humans = []
    for asset in asset_store.list("digital_human_reference"):
        path = Path(asset.path)
        if not path.exists() or path.stat().st_size <= MIN_DIGITAL_HUMAN_REFERENCE_BYTES:
            continue
        digital_human_id = f"custom:{asset.asset_id}"
        profile = DigitalHumanProfile(
            digital_human_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的真人出镜数字人参考视频",
            built_in=False,
            asset_id=asset.asset_id,
        )
        profile.last_used_at = _custom_usage_value("digital_human", digital_human_id)
        if profile.last_used_at is None:
            profile.last_used_at = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat()
        try:
            digital_human_thumbnail_path(digital_human_id)
        except Exception:
            pass
        profile.thumbnail_url = digital_human_thumbnail_url(
            digital_human_id,
            profile.last_used_at,
        )
        custom_humans.append(profile)
    custom_humans.sort(key=_custom_usage_sort_key, reverse=True)
    return {
        "items": [
            *_dedupe_recent_profiles(custom_humans),
        ]
    }


def _safe_thumbnail_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "digital_human"


def digital_human_thumbnail_url(
    digital_human_id: str,
    version: Optional[str] = None,
) -> str:
    query = {"digital_human_id": digital_human_id}
    if version:
        query["v"] = version
    return f"/api/digital-humans/thumbnail?{urlencode(query)}"


def digital_human_thumbnail_path(digital_human_id: str) -> Path:
    reference = digital_human_reference_path(digital_human_id)
    if reference is None:
        raise HTTPException(status_code=400, detail="请选择数字人")
    output = storage_dir("thumbnails", "digital_humans") / f"{_safe_thumbnail_name(digital_human_id)}.png"
    if output.exists() and output.stat().st_mtime >= reference.stat().st_mtime:
        return output
    try:
        extract_first_frame_cover_png(reference, output)
    except Exception:
        generate_cover_png(reference.stem, "", output)
    return output


@app.get("/api/digital-humans/thumbnail", tags=["assets"])
def digital_human_thumbnail(digital_human_id: str):
    if not digital_human_id:
        raise HTTPException(status_code=400, detail="请选择数字人")
    return FileResponse(
        digital_human_thumbnail_path(digital_human_id),
        media_type="image/png",
    )


@app.get("/api/digital-humans/reference", tags=["assets"])
def download_digital_human_reference(digital_human_id: str):
    if not digital_human_id:
        raise HTTPException(status_code=400, detail="请选择数字人")
    reference = digital_human_reference_path(digital_human_id)
    if reference is None or not reference.exists():
        raise HTTPException(status_code=404, detail="数字人视频不存在")
    return FileResponse(
        reference,
        filename=reference.name,
        media_type=mimetypes.guess_type(reference.name)[0] or "video/mp4",
    )


@app.post("/api/digital-humans/upload", tags=["assets"])
def upload_digital_human_reference(file: UploadFile = File(...)):
    try:
        asset = save_upload(file, "digital_humans", "digital_human_reference")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    digital_human_id = f"custom:{asset.asset_id}"
    _record_recent_usage("digital_human", digital_human_id)
    used_at = _utc_now_iso()
    try:
        digital_human_thumbnail_path(digital_human_id)
    except Exception:
        pass
    profile = DigitalHumanProfile(
        digital_human_id=digital_human_id,
        name=Path(asset.filename).stem,
        description="用户上传的真人出镜数字人参考视频",
        built_in=False,
        asset_id=asset.asset_id,
        last_used_at=used_at,
        thumbnail_url=digital_human_thumbnail_url(digital_human_id, used_at),
    )
    return {
        "asset": asset,
        "digital_human": profile,
    }


@app.get("/api/digital-humans/atlas-diagnosis", tags=["assets"])
def digital_human_atlas_diagnosis(digital_human_id: str):
    try:
        reference = digital_human_reference_path(digital_human_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if reference is None:
        raise HTTPException(status_code=400, detail="请先选择数字人参考视频")
    if not reference.exists():
        raise HTTPException(status_code=404, detail="数字人参考视频文件不存在")
    try:
        from tools.diagnose_mouth_naturalness import analyze_atlas_video

        return analyze_atlas_video(reference, sample_stride=2, max_frames=240)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"口型素材诊断失败：{exc}")


@app.get("/api/bgm", tags=["assets"])
def list_bgm():
    return build_bgm_catalog()


def build_bgm_catalog():
    template_files = (
        sorted(
            (
                path
                for path in bgm_templates_dir().iterdir()
                if path.is_file() and path.suffix.lower() in AUDIO_TEMPLATE_EXTS
            ),
            key=lambda path: _template_sort_key(path, BGM_TEMPLATE_ORDER),
        )
        if bgm_templates_dir().exists()
        else []
    )
    template_bgm = [
        BgmTrack(
            bgm_id=f"template:{path.name}",
            name=path.stem,
            mood="template",
            built_in=True,
        )
        for path in template_files
    ]
    bgm_assets = [
        asset
        for asset in asset_store.list("bgm")
        if Path(asset.path).exists()
    ]
    custom_candidates = []
    for asset in bgm_assets:
        bgm_id = f"custom:{asset.asset_id}"
        used_at = _custom_usage_value("bgm", bgm_id)
        if used_at is None:
            continue
        name = Path(asset.filename).stem
        custom_candidates.append(
            (
                _usage_sort_key(used_at),
                BgmTrack(
                    bgm_id=bgm_id,
                    name=name,
                    mood="custom",
                    built_in=False,
                    asset_id=asset.asset_id,
                ),
            )
        )
    custom_candidates.sort(key=lambda item: item[0], reverse=True)
    custom_bgm = []
    seen_custom_names: set[str] = set()
    for _, track in custom_candidates:
        name = track.name
        name_key = name.strip().lower()
        if name_key in seen_custom_names:
            continue
        seen_custom_names.add(name_key)
        custom_bgm.append(track)
        if len(custom_bgm) >= RECENT_USER_OPTION_LIMIT:
            break
    built_in_fallback = [] if template_bgm else BUILT_IN_BGM
    return {"items": [*template_bgm, *built_in_fallback, *custom_bgm]}


def resolve_bgm_audio(bgm_id: Optional[str]) -> Optional[Path]:
    if not bgm_id:
        return None
    if bgm_id in {"none", "off", "disabled"}:
        return None
    if bgm_id.startswith("template:"):
        filename = bgm_id.removeprefix("template:")
        candidate = bgm_templates_dir() / filename
        if candidate.exists() and candidate.suffix.lower() in AUDIO_TEMPLATE_EXTS:
            return candidate
        raise HTTPException(status_code=404, detail="BGM 模板不存在")
    custom = custom_asset_path(bgm_id, "bgm")
    if custom is not None:
        return custom
    if any(track.bgm_id == bgm_id for track in BUILT_IN_BGM):
        return ensure_builtin_bgm_wav(bgm_id)
    return None


def resolve_pip_asset(options: RenderOptions) -> Optional[Path]:
    if not options.pip_enabled:
        return None
    if not options.pip_asset_id:
        raise HTTPException(status_code=400, detail="请先上传画中画素材")
    try:
        asset = asset_store.get(options.pip_asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="画中画素材不存在")
    if asset.kind != "pip":
        raise HTTPException(status_code=400, detail="画中画素材类型不匹配")
    path = Path(asset.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="画中画素材文件不存在")
    return path


@app.get("/api/bgm/preview", tags=["assets"])
def preview_bgm(bgm_id: str):
    path = resolve_bgm_audio(bgm_id)
    if path is None:
        raise HTTPException(status_code=400, detail="请选择背景音乐")
    path = ensure_loudness_preview_wav(path, "bgm_previews", bgm_id)
    _record_recent_usage("bgm", bgm_id)
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def ensure_builtin_bgm_wav(bgm_id: str) -> Path:
    output = storage_dir("bgm") / f"{bgm_id}.wav"
    if output.exists() and output.stat().st_size > 44:
        return output

    presets = {
        "default-light": [(261.63, 0.20), (329.63, 0.16), (392.00, 0.12)],
        "default-tech": [(130.81, 0.18), (196.00, 0.14), (261.63, 0.10)],
        "default-warm": [(220.00, 0.18), (277.18, 0.14), (329.63, 0.10)],
    }
    tones = presets.get(bgm_id, presets["default-light"])
    sample_rate = 44100
    duration_seconds = 16
    fade_samples = int(sample_rate * 0.08)
    total_samples = sample_rate * duration_seconds

    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(total_samples):
            t = index / sample_rate
            beat = 0.55 + 0.45 * math.sin(2 * math.pi * 2 * t) ** 2
            value = 0.0
            for freq, amp in tones:
                value += amp * math.sin(2 * math.pi * freq * t)
            value *= beat
            if index < fade_samples:
                value *= index / fade_samples
            elif total_samples - index < fade_samples:
                value *= (total_samples - index) / fade_samples
            packed = struct.pack("<h", int(max(-1, min(1, value)) * 32767))
            wav.writeframesraw(packed + packed)
    return output


@app.post("/api/bgm/upload", tags=["assets"])
def upload_bgm(file: UploadFile = File(...)):
    try:
        asset = save_upload(file, "bgm", "bgm")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    bgm_id = f"custom:{asset.asset_id}"
    _record_recent_usage("bgm", bgm_id)
    return {
        "asset": asset,
        "bgm": BgmTrack(
            bgm_id=bgm_id,
            name=Path(asset.filename).stem,
            mood="custom",
            built_in=False,
            asset_id=asset.asset_id,
        ),
    }


@app.get("/api/rewrite/styles", tags=["tasks"])
def list_rewrite_styles():
    return {"items": REWRITE_STYLE_PRESETS}


@app.get("/api/bootstrap", tags=["system"])
def bootstrap_catalog():
    return {
        "features": {
            "creator_style_scripts": True,
        },
        "providers": provider_status(),
        "voices": build_voice_catalog()["items"],
        "digital_humans": build_digital_human_catalog()["items"],
        "bgm": build_bgm_catalog()["items"],
        "rewrite_styles": REWRITE_STYLE_PRESETS,
    }


@app.post("/api/subtitles/preview", tags=["subtitles"])
def subtitle_preview(req: SubtitlePreviewRequest):
    return {
        "lines": preview_subtitles(req.script, req.style),
        "style": req.style,
    }


def _render_subtitle_preview_png(req: SubtitlePreviewRequest) -> Path:
    """Render a transparent subtitle frame with the same ASS/libass path as export."""
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("FFmpeg 未配置，无法生成真实字幕预览")

    cache_payload = json.dumps(
        {
            "render_version": 1,
            **req.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    cache_key = sha256(cache_payload.encode("utf-8")).hexdigest()
    preview_dir = storage_dir("subtitle_previews")
    output_path = preview_dir / f"{cache_key}.png"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    subtitle_path = preview_dir / f"{cache_key}.ass"
    generate_ass(req.script, req.style, subtitle_path, duration_seconds=1.0)
    escaped_subtitle_path = (
        str(subtitle_path).replace("\\", "/").replace(":", "\\:")
    )
    temporary_path = preview_dir / f"{cache_key}-{uuid4().hex}.tmp.png"
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black@0.0:s=1080x1920:r=10:d=1,format=rgba",
                "-vf",
                f"subtitles='{escaped_subtitle_path}':alpha=1",
                "-ss",
                "0.1",
                "-frames:v",
                "1",
                "-update",
                "1",
                str(temporary_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "FFmpeg 字幕预览渲染失败"
            raise RuntimeError(detail)
        temporary_path.replace(output_path)
        return output_path
    finally:
        temporary_path.unlink(missing_ok=True)


@app.post("/api/subtitles/render-preview", tags=["subtitles"])
def rendered_subtitle_preview(req: SubtitlePreviewRequest):
    try:
        output_path = _render_subtitle_preview_png(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        output_path,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/subtitles/templates", tags=["subtitles"])
def list_subtitle_templates():
    return {
        "items": [
            {"template_id": template_id, **metadata}
            for template_id, metadata in SUBTITLE_TEMPLATES.items()
        ]
    }


@app.delete("/api/assets/{asset_id}", tags=["assets"])
def delete_asset(asset_id: str):
    try:
        asset = asset_store.delete(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="素材不存在")
    Path(asset.path).unlink(missing_ok=True)
    if asset.kind == "digital_human_reference":
        digital_human_id = f"custom:{asset.asset_id}"
        _remove_recent_usage("digital_human", digital_human_id)
        thumbnail = storage_dir("thumbnails", "digital_humans") / (
            f"{_safe_thumbnail_name(digital_human_id)}.png"
        )
        thumbnail.unlink(missing_ok=True)
    elif asset.kind == "voice_reference":
        _remove_recent_usage("voice", f"custom:{asset.asset_id}")
    elif asset.kind == "bgm":
        _remove_recent_usage("bgm", f"custom:{asset.asset_id}")
    return {"ok": True}


@app.get("/api/assets/{asset_id}/download", tags=["assets"])
def download_asset(asset_id: str):
    try:
        asset = asset_store.get(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="素材不存在")
    if not Path(asset.path).exists():
        raise HTTPException(status_code=404, detail="素材文件不存在")
    return FileResponse(asset.path, filename=asset.filename)


@app.get("/api/assets/{asset_id}/preview", tags=["assets"])
def preview_asset(asset_id: str):
    try:
        asset = asset_store.get(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="asset not found")
    path = Path(asset.path)
    if asset.kind == "voice_reference":
        try:
            asset = ensure_voice_reference_wav(asset)
            path = Path(asset.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if not path.exists():
        raise HTTPException(status_code=404, detail="asset file not found")
    media_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    return FileResponse(
        path,
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
    )


@app.get("/api/tasks", tags=["tasks"])
def list_tasks():
    summaries = [
        TaskSummary(
            task_id=task.task_id,
            title=task.title,
            status=task.status,
            douyin_url=task.douyin_url,
            output_ready=is_playable_mp4(task.output_video_path),
        )
        for task in reversed(repo.list())
    ]
    return {"items": summaries}


@app.get("/api/tasks/mouth-quality", tags=["tasks"])
def task_mouth_quality_report(include_missing: bool = True):
    return build_mouth_quality_report(repo.list(), include_missing=include_missing)


def _normalized_share_key(share_text: Optional[str]) -> str:
    if not share_text:
        return ""
    return (extract_first_url(share_text) or share_text).strip()


def _is_placeholder_transcript(text: str) -> bool:
    cleaned = text.strip()
    return "口播内容示例" in cleaned and "来源" in cleaned


def _find_cached_link_task(share_text: str) -> Optional[OralVideoTask]:
    target = _normalized_share_key(share_text)
    if not target:
        return None
    for existing in reversed(repo.list()):
        if _normalized_share_key(existing.douyin_url) != target:
            continue
        if existing.status not in {
            TaskStatus.transcribed,
            TaskStatus.rewritten,
            TaskStatus.completed,
        }:
            continue
        if not existing.original_script.strip() or not existing.source_video:
            continue
        if _is_placeholder_transcript(existing.original_script):
            continue
        if not Path(existing.source_video.path).exists():
            continue
        return existing
    return None


def _mark_stage(task: OralVideoTask, key: str, status: str) -> None:
    if status == "running":
        start_progress(task, key)
    elif status == "completed":
        complete_progress(task, key)
    elif status == "failed":
        fail_progress(task, key)
    repo.put(task)


@app.post("/api/tasks", tags=["tasks"])
def create_task(req: CreateTaskRequest) -> OralVideoTask:
    task = OralVideoTask(title=req.title, douyin_url=req.douyin_url)
    repo.put(task)

    if req.douyin_url:
        cached_task = _find_cached_link_task(req.douyin_url)
        if cached_task:
            task.source_video = cached_task.source_video.model_copy(deep=True)
            task.original_script = cached_task.original_script
            task.status = TaskStatus.transcribed
            complete_progress(
                task, "resolve_link", "download_video", "transcribe", "extract"
            )
            repo.put(task)
            return task

        # Run import + transcribe in a background thread so the HTTP response
        # returns immediately. Client should poll GET /api/tasks/{task_id}.
        def _run():
            active_stage = "extract"

            def _on_import_stage(key: str, status: str) -> None:
                nonlocal active_stage
                if status == "running":
                    active_stage = key
                _mark_stage(task, key, status)

            start_progress(task, "extract")
            repo.put(task)
            try:
                source_video = video_importer.import_from_share_text(
                    req.douyin_url, on_stage=_on_import_stage
                )
            except VideoImportError as exc:
                fail_progress(task, active_stage)
                fail_progress(task, "extract")
                task.status = TaskStatus.failed
                task.error_message = str(exc)
                repo.put(task)
                return
            task.source_video = source_video
            task.status = TaskStatus.imported
            active_stage = "transcribe"
            start_progress(task, "transcribe")
            repo.put(task)
            try:
                task.original_script = asr_provider.transcribe(
                    Path(source_video.path), source_video.filename
                )
            except Exception as exc:
                fail_progress(task, "transcribe")
                fail_progress(task, "extract")
                task.status = TaskStatus.failed
                task.error_message = f"视频文案识别失败：{exc}"
                repo.put(task)
                return
            task.status = TaskStatus.transcribed
            complete_progress(task, "transcribe", "extract")
            repo.put(task)

        threading.Thread(target=_run, daemon=True).start()

    return task


@app.post("/api/tasks/from-script", tags=["tasks"])
def create_task_from_script(req: CreateScriptTaskRequest) -> OralVideoTask:
    rewritten_script = req.rewritten_script.strip()
    if not rewritten_script:
        raise HTTPException(status_code=400, detail="请选择一篇有效文案")
    task = OralVideoTask(
        task_id=f"cloud-deep-{uuid4()}",
        title=(req.title or "").strip() or generate_title(rewritten_script),
        original_script=req.original_script.strip(),
        rewritten_script=rewritten_script,
        status=TaskStatus.rewritten,
    )
    complete_progress(task, "extract", "rewrite")
    return repo.put(task)


@app.post("/api/tasks/upload", tags=["tasks"])
def upload_video(file: UploadFile = File(...)) -> OralVideoTask:
    try:
        source_video = save_upload(file, "uploads", "source_video")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    task = OralVideoTask(title=Path(source_video.filename).stem)
    task.source_video = source_video
    task.status = TaskStatus.imported
    start_progress(task, "extract")
    task.original_script = asr_provider.transcribe(
        Path(source_video.path), source_video.filename
    )
    task.status = TaskStatus.transcribed
    complete_progress(task, "extract")
    return repo.put(task)


@app.get("/api/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: str) -> OralVideoTask:
    try:
        return repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")


@app.patch("/api/tasks/{task_id}", tags=["tasks"])
def update_task(task_id: str, req: UpdateTaskRequest) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if req.title is not None:
        task.title = req.title.strip() or None
    return repo.put(task)


@app.delete("/api/tasks/{task_id}", tags=["tasks"])
def delete_task(task_id: str):
    try:
        task = repo.get(task_id)
        repo.delete(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")

    paths = [
        task.extracted_audio_path,
        task.subtitle_path,
        task.output_video_path,
        task.cover_path,
    ]
    if task.output_video_path:
        paths.append(str(_cover_source_video_path(Path(task.output_video_path))))
    if task.mouth_quality:
        paths.extend([
            task.mouth_quality.mouth_state_path,
            task.mouth_quality.mouth_diagnosis_path,
        ])
    if task.source_video:
        paths.append(task.source_video.path)
    for path in paths:
        if path:
            Path(path).unlink(missing_ok=True)
    return {"ok": True}


@app.post(
    "/api/creator-scripts/generate",
    response_model=CreatorScriptBatchResponse,
    tags=["tasks"],
)
def generate_creator_scripts(
    req: CreatorScriptGenerateRequest,
) -> CreatorScriptBatchResponse:
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="请输入创作关键词")

    try:
        style_profile = req.style_profile
        if style_profile is None:
            if not req.share_text.strip():
                raise DouyinCreatorInputError("请粘贴包含抖音主页链接的完整分享文案")
            snapshot = douyin_creator_collector.collect(req.share_text)
            style_profile = creator_script_provider.analyze_style(snapshot)

        items = creator_script_provider.generate_scripts(
            style_profile,
            keyword=keyword,
            count=req.count,
            duration_seconds=req.duration_seconds,
            generation_round=req.generation_round,
            exclude_titles=req.exclude_titles,
            exclude_scripts=req.exclude_scripts,
        )
        items = [
            item.model_copy(update={"script": format_spoken_script(item.script)})
            for item in items
        ]
    except DouyinCreatorInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (DouyinCreatorFetchError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if len(items) != req.count:
        raise HTTPException(
            status_code=502,
            detail=f"文案生成结果数量异常：期望 {req.count} 篇，实际 {len(items)} 篇",
        )
    return CreatorScriptBatchResponse(
        batch_id=str(uuid4()),
        creator_name=style_profile.creator_name or "抖音创作者",
        keyword=keyword,
        generation_round=req.generation_round,
        style_profile=style_profile,
        items=items,
    )


@app.post("/api/tasks/{task_id}/rewrite", tags=["tasks"])
def rewrite_task(task_id: str, req: RewriteRequest) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    source_script = (req.source_script or task.original_script).strip()
    if not source_script:
        raise HTTPException(status_code=409, detail="请先等待解析口播完成再进行仿写")
    task.original_script = source_script
    start_progress(task, "rewrite")
    task.rewritten_script = rewrite_provider.rewrite(source_script, req)
    task.status = TaskStatus.rewritten
    complete_progress(task, "rewrite")
    return repo.put(task)


@app.post("/api/tasks/{task_id}/title", tags=["tasks"])
def generate_task_title(task_id: str) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    script = task.rewritten_script or task.original_script
    if not script:
        raise HTTPException(status_code=400, detail="没有可生成标题的文案")
    start_progress(task, "title")
    task.video_title = generate_title(script)
    task.title = task.video_title
    complete_progress(task, "title")
    return repo.put(task)


@app.post("/api/tasks/{task_id}/publish-content", tags=["tasks"])
def generate_task_publish_content(task_id: str) -> PublishContentSuggestion:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    script = (task.rewritten_script or task.original_script).strip()
    if not script:
        raise HTTPException(status_code=400, detail="没有可生成发布内容的文案")
    try:
        suggestion = generate_publish_content(script)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"大模型生成发布内容失败：{exc}") from exc
    task.video_title = suggestion.title
    task.title = suggestion.title
    repo.put(task)
    return suggestion


def _cover_source_video_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_cover_source{video_path.suffix}")


def _cover_background_video_path(video_path: Path) -> Path:
    source_path = _cover_source_video_path(video_path)
    return source_path if source_path.exists() else video_path


def _apply_cover_to_video_first_frame(
    video_path: Path,
    cover_path: Path,
    *,
    refresh_source: bool = False,
    cancel_event: threading.Event | None = None,
) -> Path:
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if not cover_path.exists():
        raise FileNotFoundError(cover_path)

    source_path = _cover_source_video_path(video_path)
    if refresh_source or not source_path.exists():
        source_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video_path, source_path)

    temporary_path = video_path.with_name(f"{video_path.stem}_covering{video_path.suffix}")
    temporary_path.unlink(missing_ok=True)
    try:
        renderer.apply_cover_first_frame(
            source_path,
            cover_path,
            temporary_path,
            cancel_event=cancel_event,
        )
        temporary_path.replace(video_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return video_path


def _generate_task_cover_file(
    task: OralVideoTask,
    script: str,
    cover_path: Path,
    *,
    template_id: str | None = None,
) -> Path:
    frame_path: Path | None = None
    if task.output_video_path and Path(task.output_video_path).exists():
        frame_path = cover_path.with_name(f"{cover_path.stem}_frame.png")
        try:
            output_path = Path(task.output_video_path)
            extract_first_frame_cover_png(_cover_background_video_path(output_path), frame_path)
        except Exception:
            frame_path = None
    try:
        return generate_cover_png(
            task.video_title or task.title or "",
            script,
            cover_path,
            background_image_path=frame_path,
            template_id=template_id or task.cover_template_id or DEFAULT_COVER_TEMPLATE,
        )
    finally:
        if frame_path is not None:
            frame_path.unlink(missing_ok=True)


@app.get("/api/covers/templates", tags=["tasks"])
def list_cover_templates():
    return {
        "items": [
            {"template_id": template_id, **metadata}
            for template_id, metadata in COVER_TEMPLATES.items()
        ]
    }


@app.post("/api/covers/generate", tags=["tasks"])
def generate_standalone_cover(payload: dict) -> Dict[str, str]:
    title = str(payload.get("title") or "").strip()
    script = str(payload.get("script") or "").strip()
    background = str(payload.get("background_path") or "").strip()
    template_id = str(payload.get("template_id") or DEFAULT_COVER_TEMPLATE).strip()
    if not title and not script:
        raise HTTPException(status_code=400, detail="没有可生成封面的标题或文案")
    cover_path = storage_dir("covers") / f"{uuid4()}.png"
    frame_path: Path | None = None
    background_path: Path | None = None
    if background:
        candidate = Path(background)
        if candidate.exists():
            if candidate.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
                frame_path = cover_path.with_name(f"{cover_path.stem}_frame.png")
                try:
                    extract_first_frame_cover_png(_cover_background_video_path(candidate), frame_path)
                    background_path = frame_path
                except Exception:
                    background_path = None
            elif candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                background_path = candidate
    try:
        generate_cover_png(
            title,
            script,
            cover_path,
            background_image_path=background_path,
            template_id=template_id,
        )
    finally:
        if frame_path is not None:
            frame_path.unlink(missing_ok=True)
    return {
        "cover_path": str(cover_path),
        "template_id": template_id if template_id in COVER_TEMPLATES else DEFAULT_COVER_TEMPLATE,
    }


@app.post("/api/tasks/{task_id}/cover", tags=["tasks"])
def generate_task_cover(
    task_id: str,
    template_id: str = DEFAULT_COVER_TEMPLATE,
) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    script = task.rewritten_script or task.original_script
    if not script and not task.output_video_path:
        raise HTTPException(status_code=400, detail="没有可生成封面的文案或视频")
    start_progress(task, "cover")
    if not task.video_title:
        task.video_title = generate_title(script)
        task.title = task.video_title
        complete_progress(task, "title")
    cover_path = storage_dir("covers") / f"{task_id}.png"
    task.cover_template_id = template_id if template_id in COVER_TEMPLATES else DEFAULT_COVER_TEMPLATE
    _generate_task_cover_file(
        task,
        script,
        cover_path,
        template_id=task.cover_template_id,
    )
    task.cover_path = str(cover_path)
    complete_progress(task, "cover")
    return repo.put(task)


@app.post("/api/tasks/{task_id}/cover/upload", tags=["tasks"])
def upload_task_cover(task_id: str, file: UploadFile = File(...)) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        asset = save_upload(file, "covers", "cover")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    start_progress(task, "cover")
    task.cover_path = str(Path(asset.path))
    task.cover_template_id = "custom"
    if not task.video_title:
        script = task.rewritten_script or task.original_script
        if script:
            task.video_title = task.title or generate_title(script)
            task.title = task.video_title
    complete_progress(task, "cover")
    return repo.put(task)


@app.post("/api/videos/cover-first-frame", tags=["tasks"])
def apply_video_cover_first_frame(payload: dict):
    video_path = Path(str(payload.get("source_video_path") or "")).expanduser()
    cover_path = Path(str(payload.get("cover_path") or "")).expanduser()
    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="待设置封面的视频不存在")
    if not is_playable_mp4(video_path):
        raise HTTPException(status_code=400, detail="待设置封面的视频不是可播放的 MP4")
    if not cover_path.exists() or not cover_path.is_file():
        raise HTTPException(status_code=404, detail="封面图片不存在")
    if cover_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="封面图片格式不受支持")
    try:
        rendered_path = _apply_cover_to_video_first_frame(video_path, cover_path)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"封面写入视频失败：{exc.returncode}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"封面写入视频失败：{exc}") from exc
    return {
        "ready": is_playable_mp4(rendered_path),
        "path": str(rendered_path),
        "size_bytes": rendered_path.stat().st_size,
    }


@app.post("/api/tasks/{task_id}/publish", tags=["tasks"])
def publish_task(task_id: str, req: PublishRequest) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    platforms = req.platforms or ["douyin", "shipinhao", "kuaishou", "xiaohongshu"]
    start_progress(task, "publish")
    task.publish_results = {
        platform: "本地记录成功，真实发布待接入平台账号/API" for platform in platforms
    }
    complete_progress(task, "publish")
    return repo.put(task)


@app.post("/api/tasks/{task_id}/render", tags=["tasks"])
def render_task(task_id: str, options: RenderOptions) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")

    script = options.script or task.rewritten_script or task.original_script
    if not script:
        raise HTTPException(status_code=400, detail="没有可合成的文案")
    if options.defer_packaging:
        options = options.model_copy(
            update={
                "bgm_id": "none",
                "bgm_volume": 0,
                "voice_volume": 1.0,
                "subtitle_enabled": False,
                "pip_enabled": False,
                "pip_asset_id": None,
                "cover_path": None,
            }
        )
    selected_engine, active_digital_human_provider = selected_digital_human_provider(
        options.digital_human_engine
    )
    voice_ref = voice_reference_path(options.voice_id, options.voice_reference_asset_id)
    bgm_audio = resolve_bgm_audio(options.bgm_id)
    if bgm_audio is not None:
        bgm_audio = ensure_loudness_preview_wav(
            bgm_audio,
            "bgm_previews",
            options.bgm_id or bgm_audio.name,
            required=True,
        )
    pip_asset = resolve_pip_asset(options)
    digital_human_video = digital_human_reference_path(options.digital_human_id)
    _record_recent_usage("voice", options.voice_id)
    _record_recent_usage("digital_human", options.digital_human_id)
    _record_recent_usage("bgm", options.bgm_id)
    source_video = digital_human_video or (Path(task.source_video.path) if task.source_video else None)
    cancel_event = threading.Event()
    render_cancel_events[task_id] = cancel_event
    task.status = TaskStatus.rendering
    task.error_message = None
    task.render_options = options
    task.mouth_quality = None
    repo.put(task)

    try:
        ensure_not_cancelled(task, cancel_event)
        generated_audio_path = storage_dir("extracted_audio") / f"{task_id}_voice.wav"
        existing_audio_path = (
            Path(task.extracted_audio_path)
            if options.defer_packaging and task.extracted_audio_path
            else None
        )
        audio_path = (
            existing_audio_path
            if existing_audio_path is not None and existing_audio_path.exists()
            else generated_audio_path
        )
        start_progress(task, "voice")
        repo.put(task)
        if audio_path == generated_audio_path:
            voice_provider.synthesize(
                script,
                options.voice_id,
                audio_path,
                reference_audio=voice_ref,
            )
        ensure_not_cancelled(task, cancel_event)
        task.extracted_audio_path = str(audio_path)
        render_voice_audio = ensure_loudness_preview_wav(
            audio_path,
            "generated_voice_previews",
            task_id,
            required=True,
        )
        complete_progress(task, "voice")
        repo.put(task)

        audio_duration = media_duration_seconds(render_voice_audio)
        subtitle_timing_tokens = (
            _subtitle_timing_tokens(render_voice_audio)
            if options.subtitle_enabled
            or (
                options.pip_enabled
                and (options.pip_timing_mode or "").strip().lower()
                == "sentence"
            )
            else []
        )
        if options.pip_enabled and (options.pip_timing_mode or "").strip().lower() == "sentence":
            range_text = (options.pip_trigger_text or "").strip()
            time_range = subtitle_time_range_for_text(
                script,
                options.subtitle_style,
                range_text,
                duration_seconds=audio_duration,
                timed_tokens=subtitle_timing_tokens,
            )
            if time_range is None:
                raise RuntimeError("没有在文案字幕中找到画中画触发句，请换一句更完整的话或改用按秒显示。")
            options = options.model_copy(
                update={
                    "pip_start_seconds": time_range[0],
                    "pip_end_seconds": time_range[1],
                }
            )
            task.render_options = options
            repo.put(task)
        digital_path = storage_dir("outputs") / f"{task_id}_digital.mp4"
        prepared_reference_video = source_video
        if source_video is not None:
            prepared_reference_video = prepare_video_for_audio_duration(
                source_video,
                render_voice_audio,
                storage_dir("outputs") / f"{task_id}_reference_matched.mp4",
                cancel_event=cancel_event,
            )
            ensure_not_cancelled(task, cancel_event)

        subtitle_path: Optional[Path] = None
        start_progress(task, "subtitle")
        repo.put(task)
        if options.subtitle_enabled:
            subtitle_path = storage_dir("subtitles") / f"{task_id}.ass"
            generate_ass(
                script,
                options.subtitle_style,
                subtitle_path,
                duration_seconds=audio_duration,
                timed_tokens=subtitle_timing_tokens,
            )
            task.subtitle_path = str(subtitle_path)
        else:
            task.subtitle_path = None
        ensure_not_cancelled(task, cancel_event)
        complete_progress(task, "subtitle")
        repo.put(task)
        start_progress(task, "bgm")
        complete_progress(task, "bgm")
        repo.put(task)

        output_path = storage_dir("outputs") / f"{task_id}.mp4"
        start_progress(task, "digital_human")
        repo.put(task)
        active_digital_human_provider.render(
            reference_video=prepared_reference_video,
            driving_audio=render_voice_audio,
            script=script,
            options=options,
            output_path=digital_path,
            cancel_event=cancel_event,
        )
        ensure_not_cancelled(task, cancel_event)
        task.mouth_quality = collect_mouth_quality_signals(digital_path)
        repo.put(task)
        render_kwargs = {
            "source_video": digital_path,
            "voice_audio": render_voice_audio,
            "subtitle_file": subtitle_path,
            "bgm_audio": bgm_audio,
            "cancel_event": cancel_event,
        }
        if pip_asset is not None:
            render_kwargs["pip_asset"] = pip_asset
        rendered_path = renderer.render(
            task_id,
            script,
            options,
            output_path,
            **render_kwargs,
        )

        ensure_not_cancelled(task, cancel_event)
        complete_progress(task, "digital_human")
        task.output_video_path = str(rendered_path)
        repo.put(task)
        if not is_playable_mp4(rendered_path):
            task.error_message = "成品视频未生成：未检测到 ffmpeg，或缺少可合成的源视频、音频、字幕文件。"
            fail_progress(task, "digital_human")
            task.status = TaskStatus.failed
            return repo.put(task)
        start_progress(task, "title")
        repo.put(task)
        task.video_title = task.video_title or generate_title(script)
        task.title = task.video_title
        complete_progress(task, "title")
        repo.put(task)
        if options.defer_packaging:
            task.status = TaskStatus.completed
            return repo.put(task)
        start_progress(task, "cover")
        repo.put(task)
        existing_cover = Path(task.cover_path) if task.cover_path else None
        if (
            task.cover_template_id == "custom"
            and existing_cover is not None
            and existing_cover.exists()
        ):
            cover_path = existing_cover
        else:
            cover_path = storage_dir("covers") / f"{task_id}.png"
            _generate_task_cover_file(
                task,
                script,
                cover_path,
                template_id=task.cover_template_id,
            )
        task.cover_path = str(cover_path)
        _apply_cover_to_video_first_frame(
            Path(task.output_video_path),
            cover_path,
            refresh_source=True,
            cancel_event=cancel_event,
        )
        complete_progress(task, "cover")
        repo.put(task)
        task.status = TaskStatus.completed
        return repo.put(task)
    except RuntimeError as exc:
        if str(exc) == "用户已停止生成":
            fail_progress(task, "digital_human")
            task.status = TaskStatus.failed
            task.error_message = "用户已停止生成"
            return repo.put(task)
        fail_progress(task, "digital_human")
        task.status = TaskStatus.failed
        task.error_message = str(exc)
        return repo.put(task)
    except HTTPException:
        raise
    except Exception as exc:
        fail_progress(task, "digital_human")
        task.status = TaskStatus.failed
        task.error_message = str(exc)
        return repo.put(task)
    finally:
        render_cancel_events.pop(task_id, None)


@app.post("/api/tasks/{task_id}/cancel-render", tags=["tasks"])
def cancel_render_task(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    event = render_cancel_events.get(task_id)
    if event is not None:
        event.set()
    task.status = TaskStatus.failed
    task.error_message = "用户已停止生成"
    fail_progress(task, "digital_human")
    repo.put(task)
    return {"ok": True, "detail": "已请求停止生成"}


@app.post("/api/tasks/{task_id}/voice", tags=["tasks"])
def clone_task_voice(task_id: str, options: RenderOptions) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")

    script = options.script or task.rewritten_script or task.original_script
    if not script:
        raise HTTPException(status_code=400, detail="没有可合成的文案")

    voice_ref = voice_reference_path(options.voice_id, options.voice_reference_asset_id)
    if voice_ref is None:
        raise HTTPException(status_code=400, detail="声音克隆需要先上传并选择参考音色")

    _record_recent_usage("voice", options.voice_id)
    audio_path = storage_dir("extracted_audio") / f"{task_id}_voice.wav"
    start_progress(task, "voice")
    try:
        voice_provider.synthesize(script, options.voice_id, audio_path, reference_audio=voice_ref)
        task.extracted_audio_path = str(audio_path)
        complete_progress(task, "voice")
        task.render_options = options
        return repo.put(task)
    except Exception as exc:
        fail_progress(task, "voice")
        task.error_message = str(exc)
        repo.put(task)
        detail = str(exc)
        lower_detail = detail.lower()
        status_code = 503 if (
            "connection" in lower_detail
            or "连接" in detail
            or "10061" in detail
            or "refused" in lower_detail
        ) else 500
        if status_code == 503:
            detail = (
                "本地声音克隆服务未启动。云端生成会在云端克隆声音，可直接点击“生成视频”；"
                "如需本地生成，请先启动本机声音服务。"
            )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/api/tasks/{task_id}/subtitles", tags=["tasks"])
def generate_task_subtitles(task_id: str, options: RenderOptions) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")

    script = options.script or task.rewritten_script or task.original_script
    if not script:
        raise HTTPException(status_code=400, detail="没有可生成的字幕文案")

    task.render_options = options
    start_progress(task, "subtitle")
    if options.subtitle_enabled:
        subtitle_path = storage_dir("subtitles") / f"{task_id}.ass"
        duration = media_duration_seconds(task.extracted_audio_path)
        if duration is None and task.source_video:
            duration = media_duration_seconds(task.source_video.path)
        timing_source = task.extracted_audio_path
        if not timing_source and task.source_video:
            timing_source = task.source_video.path
        generate_ass(
            script,
            options.subtitle_style,
            subtitle_path,
            duration_seconds=duration,
            timed_tokens=_subtitle_timing_tokens(timing_source),
        )
        task.subtitle_path = str(subtitle_path)
    else:
        task.subtitle_path = None
    complete_progress(task, "subtitle")
    return repo.put(task)


@app.get("/api/tasks/{task_id}/output", tags=["tasks"])
def task_output(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.output_video_path:
        return {"ready": False, "path": None, "size_bytes": 0, "detail": "成品还未生成"}
    output_path = Path(task.output_video_path)
    ready = is_playable_mp4(output_path)
    return {
        "ready": ready,
        "path": task.output_video_path,
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "detail": None if ready else (task.error_message or "成品视频不是可播放的 MP4"),
    }


@app.get("/api/tasks/{task_id}/voice", tags=["tasks"])
def task_voice_audio(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")
    if not task.extracted_audio_path or not Path(task.extracted_audio_path).exists():
        raise HTTPException(status_code=404, detail="voice audio not generated")
    path = ensure_loudness_preview_wav(
        Path(task.extracted_audio_path),
        "generated_voice_previews",
        task_id,
    )
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/tasks/{task_id}/source", tags=["tasks"])
def task_source_video(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.source_video or not Path(task.source_video.path).exists():
        raise HTTPException(status_code=404, detail="源视频不存在")
    return FileResponse(task.source_video.path, media_type="video/mp4")


@app.get("/api/tasks/{task_id}/cover", tags=["tasks"])
def task_cover(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.cover_path or not Path(task.cover_path).exists():
        raise HTTPException(status_code=404, detail="封面还未生成")
    return FileResponse(task.cover_path, media_type="image/png")


@app.get("/api/tasks/{task_id}/download", tags=["tasks"])
def download_task(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.output_video_path or not is_playable_mp4(task.output_video_path):
        raise HTTPException(status_code=404, detail="成品还未生成")
    return FileResponse(task.output_video_path, filename=f"{task_id}.mp4", media_type="video/mp4")


@app.post("/api/videos/postprocess", tags=["tasks"])
def postprocess_video(request: PostprocessVideoRequest):
    source_path = Path(request.source_video_path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="待合成视频不存在")
    if not is_playable_mp4(source_path):
        raise HTTPException(status_code=400, detail="待合成视频不是可播放的 MP4")

    options = request.options
    script = (options.script or "").strip()
    bgm_audio = resolve_bgm_audio(options.bgm_id)
    if bgm_audio is not None:
        bgm_audio = ensure_loudness_preview_wav(
            bgm_audio,
            "bgm_previews",
            options.bgm_id or bgm_audio.name,
            required=True,
        )
    pip_asset = resolve_pip_asset(options)
    duration = media_duration_seconds(source_path)
    voice_audio = ensure_loudness_preview_wav(
        source_path,
        "postprocess_voice",
        source_path.stem,
        required=True,
    )
    subtitle_timing_tokens = (
        _subtitle_timing_tokens(voice_audio)
        if options.subtitle_enabled
        or (
            options.pip_enabled
            and (options.pip_timing_mode or "").strip().lower() == "sentence"
        )
        else []
    )

    if options.pip_enabled and (options.pip_timing_mode or "").strip().lower() == "sentence":
        range_text = (options.pip_trigger_text or "").strip()
        time_range = subtitle_time_range_for_text(
            script,
            options.subtitle_style,
            range_text,
            duration_seconds=duration,
            timed_tokens=subtitle_timing_tokens,
        )
        if time_range is None:
            raise HTTPException(status_code=400, detail="没有在文案字幕中找到画中画触发句，请换一句更完整的话或改用按秒显示。")
        options = options.model_copy(
            update={
                "pip_start_seconds": time_range[0],
                "pip_end_seconds": time_range[1],
            }
        )

    postprocess_id = f"postprocess-{uuid4()}"
    subtitle_path: Path | None = None
    if options.subtitle_enabled:
        subtitle_path = storage_dir("subtitles") / f"{postprocess_id}.ass"
        generate_ass(
            script,
            options.subtitle_style,
            subtitle_path,
            duration_seconds=duration,
            timed_tokens=subtitle_timing_tokens,
        )

    output_path = storage_dir("outputs") / f"{postprocess_id}.mp4"
    try:
        rendered_path = renderer.postprocess(
            source_path,
            subtitle_path,
            options,
            output_path,
            bgm_audio=bgm_audio,
            pip_asset=pip_asset,
            voice_audio=voice_audio,
        )
        cover_path = Path(options.cover_path).expanduser() if options.cover_path else None
        if cover_path is not None and cover_path.exists():
            _apply_cover_to_video_first_frame(
                rendered_path,
                cover_path,
                refresh_source=True,
            )
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"本地后处理合成失败：{exc.returncode}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"本地后处理合成失败：{exc}") from exc

    return {
        "ready": is_playable_mp4(rendered_path),
        "path": str(rendered_path),
        "size_bytes": rendered_path.stat().st_size if rendered_path.exists() else 0,
    }
