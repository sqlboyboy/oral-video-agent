import json
import math
import re
import struct
import threading
import wave
from pathlib import Path
from typing import Dict, Optional

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .asset_store import asset_store, ensure_voice_reference_wav, save_upload
from .models import BgmTrack, CreateTaskRequest, DigitalHumanProfile, OralVideoTask, PublishContentSuggestion, PublishRequest, RenderOptions, RewriteRequest, SubtitlePreviewRequest, TaskStatus, TaskSummary, UpdateTaskRequest, VoiceProfile, storage_dir
from .mouth_quality import build_mouth_quality_report, collect_mouth_quality_signals
from .pipeline.cover import extract_first_frame_cover_png, generate_cover_png
from .pipeline.renderer import (
    Renderer,
    _ffmpeg_executable,
    is_playable_mp4,
    media_duration_seconds,
    prepare_video_for_audio_duration,
)
from .progress import complete_progress, fail_progress, start_progress
from .pipeline.subtitles import generate_srt, preview_subtitles
from .providers.asr import create_asr_provider
from .providers.catalog import BUILT_IN_BGM, BUILT_IN_VOICES
from .providers.digital_human import create_digital_human_provider
from .providers.rewrite import create_rewrite_provider
from .providers.rewrite_styles import REWRITE_STYLE_PRESETS
from .providers.tts import create_voice_provider
from .providers.video_importer import VideoImportError, VideoImporter
from .publisher import router as publisher_router
from .repository import repo
from .settings import get_settings
from tools.diagnose_mouth_naturalness import analyze_atlas_video

import sys
import asyncio

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
voice_provider = create_voice_provider(settings)
digital_human_provider = create_digital_human_provider(settings)
video_importer = VideoImporter()
renderer = Renderer()

DIGITAL_HUMAN_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
render_cancel_events: Dict[str, threading.Event] = {}


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


@app.get("/api/voices", tags=["assets"])
def list_voices():
    return build_voice_catalog()


def build_voice_catalog():
    assets = [
        asset
        for asset in asset_store.list("voice_reference")
        if Path(asset.path).exists() and Path(asset.path).stat().st_size > 1024
    ]
    assets.sort(key=lambda asset: Path(asset.path).stat().st_mtime, reverse=True)
    custom_voices = [
        VoiceProfile(
            voice_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的授权声音参考",
            built_in=False,
            asset_id=asset.asset_id,
        )
        for asset in assets[:12]
    ]
    return {"items": [*BUILT_IN_VOICES, *custom_voices]}


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
    return {
        "asset": asset,
        "voice": VoiceProfile(
            voice_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的授权声音参考",
            built_in=False,
            asset_id=asset.asset_id,
        ),
    }


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
    custom_humans = [
        DigitalHumanProfile(
            digital_human_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的真人出镜数字人参考视频",
            built_in=False,
            asset_id=asset.asset_id,
        )
        for asset in asset_store.list("digital_human_reference")
    ]
    return {"items": [*built_in_templates, *custom_humans]}


@app.post("/api/digital-humans/upload", tags=["assets"])
def upload_digital_human_reference(file: UploadFile = File(...)):
    try:
        asset = save_upload(file, "digital_humans", "digital_human_reference")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "asset": asset,
        "digital_human": DigitalHumanProfile(
            digital_human_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的真人出镜数字人参考视频",
            built_in=False,
            asset_id=asset.asset_id,
        ),
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
        return analyze_atlas_video(reference, sample_stride=2, max_frames=240)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"口型素材诊断失败：{exc}")


@app.get("/api/bgm", tags=["assets"])
def list_bgm():
    return build_bgm_catalog()


def build_bgm_catalog():
    custom_bgm = [
        BgmTrack(
            bgm_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            mood="custom",
            built_in=False,
            asset_id=asset.asset_id,
        )
        for asset in asset_store.list("bgm")
    ]
    return {"items": [*BUILT_IN_BGM, *custom_bgm]}


def resolve_bgm_audio(bgm_id: Optional[str]) -> Optional[Path]:
    if not bgm_id:
        return None
    if bgm_id in {"none", "off", "disabled"}:
        return None
    custom = custom_asset_path(bgm_id, "bgm")
    if custom is not None:
        return custom
    if any(track.bgm_id == bgm_id for track in BUILT_IN_BGM):
        return ensure_builtin_bgm_wav(bgm_id)
    return None


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
    return {
        "asset": asset,
        "bgm": BgmTrack(
            bgm_id=f"custom:{asset.asset_id}",
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


@app.delete("/api/assets/{asset_id}", tags=["assets"])
def delete_asset(asset_id: str):
    try:
        asset = asset_store.delete(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="素材不存在")
    Path(asset.path).unlink(missing_ok=True)
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


@app.post("/api/tasks", tags=["tasks"])
def create_task(req: CreateTaskRequest) -> OralVideoTask:
    task = OralVideoTask(title=req.title, douyin_url=req.douyin_url)
    repo.put(task)

    if req.douyin_url:
        # Run import + transcribe in a background thread so the HTTP response
        # returns immediately. Client should poll GET /api/tasks/{task_id}.
        def _run():
            start_progress(task, "extract")
            repo.put(task)
            try:
                source_video = video_importer.import_from_share_text(req.douyin_url)
            except VideoImportError as exc:
                task.status = TaskStatus.failed
                task.error_message = str(exc)
                repo.put(task)
                return
            task.source_video = source_video
            task.status = TaskStatus.imported
            repo.put(task)
            task.original_script = asr_provider.transcribe(
                Path(source_video.path), source_video.filename
            )
            task.status = TaskStatus.transcribed
            complete_progress(task, "extract")
            repo.put(task)

        threading.Thread(target=_run, daemon=True).start()

    return task


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


@app.post("/api/tasks/{task_id}/cover", tags=["tasks"])
def generate_task_cover(task_id: str) -> OralVideoTask:
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
    if task.output_video_path and Path(task.output_video_path).exists():
        try:
            extract_first_frame_cover_png(Path(task.output_video_path), cover_path)
        except Exception:
            generate_cover_png(task.video_title, script, cover_path)
    else:
        generate_cover_png(task.video_title, script, cover_path)
    task.cover_path = str(cover_path)
    complete_progress(task, "cover")
    return repo.put(task)


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
    selected_engine, active_digital_human_provider = selected_digital_human_provider(
        options.digital_human_engine
    )
    voice_ref = custom_asset_path(options.voice_id, "voice_reference")
    if voice_ref is None:
        voice_ref = custom_asset_id_path(options.voice_reference_asset_id, "voice_reference")
    bgm_audio = resolve_bgm_audio(options.bgm_id)
    digital_human_video = digital_human_reference_path(options.digital_human_id)
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
        audio_path = storage_dir("extracted_audio") / f"{task_id}_voice.wav"
        start_progress(task, "voice")
        repo.put(task)
        voice_provider.synthesize(script, options.voice_id, audio_path, reference_audio=voice_ref)
        ensure_not_cancelled(task, cancel_event)
        task.extracted_audio_path = str(audio_path)
        complete_progress(task, "voice")
        repo.put(task)

        audio_duration = media_duration_seconds(audio_path)
        digital_path = storage_dir("outputs") / f"{task_id}_digital.mp4"
        prepared_reference_video = source_video
        if source_video is not None:
            prepared_reference_video = prepare_video_for_audio_duration(
                source_video,
                audio_path,
                storage_dir("outputs") / f"{task_id}_reference_matched.mp4",
                cancel_event=cancel_event,
            )
            ensure_not_cancelled(task, cancel_event)

        subtitle_path = storage_dir("subtitles") / f"{task_id}.srt"
        start_progress(task, "subtitle")
        repo.put(task)
        generate_srt(script, options.subtitle_style, subtitle_path, duration_seconds=audio_duration)
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
            driving_audio=audio_path,
            script=script,
            options=options,
            output_path=digital_path,
            cancel_event=cancel_event,
        )
        ensure_not_cancelled(task, cancel_event)
        task.mouth_quality = collect_mouth_quality_signals(digital_path)
        repo.put(task)
        rendered_path = renderer.render(
            task_id,
            script,
            options,
            output_path,
            source_video=digital_path,
            voice_audio=audio_path,
            subtitle_file=subtitle_path,
            bgm_audio=bgm_audio,
            cancel_event=cancel_event,
        )

        ensure_not_cancelled(task, cancel_event)
        complete_progress(task, "digital_human")
        task.subtitle_path = str(subtitle_path)
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
        start_progress(task, "cover")
        repo.put(task)
        cover_path = storage_dir("covers") / f"{task_id}.png"
        try:
            extract_first_frame_cover_png(rendered_path, cover_path)
        except Exception:
            generate_cover_png(task.video_title, script, cover_path)
        task.cover_path = str(cover_path)
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

    voice_ref = custom_asset_path(options.voice_id, "voice_reference")
    if voice_ref is None:
        voice_ref = custom_asset_id_path(options.voice_reference_asset_id, "voice_reference")
    if voice_ref is None:
        raise HTTPException(status_code=400, detail="声音克隆需要先上传并选择参考音色")

    audio_path = storage_dir("extracted_audio") / f"{task_id}_voice.wav"
    start_progress(task, "voice")
    voice_provider.synthesize(script, options.voice_id, audio_path, reference_audio=voice_ref)
    task.extracted_audio_path = str(audio_path)
    complete_progress(task, "voice")
    task.render_options = options
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
    return FileResponse(task.extracted_audio_path, media_type="audio/wav")


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
