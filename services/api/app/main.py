from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .asset_store import asset_store, save_upload
from .models import BgmTrack, CreateTaskRequest, OralVideoTask, RenderOptions, RewriteRequest, SubtitlePreviewRequest, TaskStatus, TaskSummary, VoiceProfile, storage_dir
from .pipeline.renderer import Renderer
from .progress import complete_progress, start_progress
from .pipeline.subtitles import generate_srt, preview_subtitles
from .providers.asr import create_asr_provider
from .providers.catalog import BUILT_IN_BGM, BUILT_IN_VOICES
from .providers.rewrite import create_rewrite_provider
from .providers.tts import create_voice_provider
from .repository import repo
from .settings import get_settings

app = FastAPI(title="智能口播智能体 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
asr_provider = create_asr_provider(settings)
rewrite_provider = create_rewrite_provider(settings)
voice_provider = create_voice_provider(settings)
renderer = Renderer()


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
    return Path(asset.path)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/providers")
def provider_status():
    return {
        "rewrite_provider": settings.rewrite_provider,
        "anthropic_model": settings.anthropic_model if settings.rewrite_provider == "anthropic" else None,
        "anthropic_configured": bool(settings.anthropic_api_key),
        "asr_provider": settings.asr_provider,
        "whisper_model": settings.whisper_model if settings.asr_provider == "faster-whisper" else None,
        "voice_provider": settings.voice_provider,
        "voice_configured": settings.voice_provider == "placeholder" or bool(settings.tts_api_key),
    }


@app.get("/api/voices")
def list_voices():
    custom_voices = [
        VoiceProfile(
            voice_id=f"custom:{asset.asset_id}",
            name=Path(asset.filename).stem,
            description="用户上传的授权声音参考",
            built_in=False,
            asset_id=asset.asset_id,
        )
        for asset in asset_store.list("voice_reference")
    ]
    return {"items": [*BUILT_IN_VOICES, *custom_voices]}


@app.post("/api/voices/upload")
def upload_voice_reference(file: UploadFile = File(...)):
    try:
        asset = save_upload(file, "voice_refs", "voice_reference")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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


@app.get("/api/bgm")
def list_bgm():
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


@app.post("/api/bgm/upload")
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


@app.post("/api/subtitles/preview")
def subtitle_preview(req: SubtitlePreviewRequest):
    return {
        "lines": preview_subtitles(req.script, req.style),
        "style": req.style,
    }


@app.get("/api/tasks")
def list_tasks():
    summaries = [
        TaskSummary(
            task_id=task.task_id,
            title=task.title,
            status=task.status,
            douyin_url=task.douyin_url,
            output_ready=bool(task.output_video_path and Path(task.output_video_path).exists()),
        )
        for task in repo.list()
    ]
    return {"items": summaries}


@app.post("/api/tasks")
def create_task(req: CreateTaskRequest) -> OralVideoTask:
    task = OralVideoTask(title=req.title, douyin_url=req.douyin_url)
    if req.douyin_url:
        complete_progress(task, "import")
        start_progress(task, "transcribe")
        task.status = TaskStatus.transcribed
        task.original_script = asr_provider.transcribe(None, req.douyin_url)
        complete_progress(task, "transcribe")
    return repo.put(task)


@app.post("/api/tasks/upload")
def upload_video(file: UploadFile = File(...)) -> OralVideoTask:
    try:
        source_video = save_upload(file, "uploads", "source_video")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    task = OralVideoTask(title=Path(source_video.filename).stem)
    task.source_video = source_video
    complete_progress(task, "import")
    start_progress(task, "transcribe")
    task.status = TaskStatus.transcribed
    task.original_script = asr_provider.transcribe(None, source_video.filename)
    complete_progress(task, "transcribe")
    return repo.put(task)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> OralVideoTask:
    try:
        return repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")


@app.post("/api/tasks/{task_id}/rewrite")
def rewrite_task(task_id: str, req: RewriteRequest) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    start_progress(task, "rewrite")
    task.rewritten_script = rewrite_provider.rewrite(task.original_script, req)
    task.status = TaskStatus.rewritten
    complete_progress(task, "rewrite")
    return repo.put(task)


@app.post("/api/tasks/{task_id}/render")
def render_task(task_id: str, options: RenderOptions) -> OralVideoTask:
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")

    script = options.script or task.rewritten_script or task.original_script
    if not script:
        raise HTTPException(status_code=400, detail="没有可合成的文案")

    task.status = TaskStatus.rendering
    task.render_options = options
    repo.put(task)

    audio_path = storage_dir("extracted_audio") / f"{task_id}_voice.wav"
    start_progress(task, "voice")
    voice_provider.synthesize(script, options.voice_id, audio_path)
    complete_progress(task, "voice")

    subtitle_path = storage_dir("subtitles") / f"{task_id}.srt"
    start_progress(task, "subtitle")
    generate_srt(script, options.subtitle_style, subtitle_path)
    complete_progress(task, "subtitle")

    output_path = storage_dir("outputs") / f"{task_id}.mp4.txt"
    start_progress(task, "render")
    source_video = Path(task.source_video.path) if task.source_video else None
    bgm_audio = custom_asset_path(options.bgm_id, "bgm")
    renderer.render(
        task_id,
        script,
        options,
        output_path,
        source_video=source_video,
        voice_audio=audio_path,
        subtitle_file=subtitle_path,
        bgm_audio=bgm_audio,
    )

    complete_progress(task, "render")
    task.subtitle_path = str(subtitle_path)
    task.output_video_path = str(output_path)
    task.status = TaskStatus.completed
    return repo.put(task)


@app.get("/api/tasks/{task_id}/output")
def task_output(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.output_video_path:
        return {"ready": False, "path": None, "size_bytes": 0}
    output_path = Path(task.output_video_path)
    return {
        "ready": output_path.exists(),
        "path": task.output_video_path,
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
    }


@app.get("/api/tasks/{task_id}/download")
def download_task(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.output_video_path or not Path(task.output_video_path).exists():
        raise HTTPException(status_code=404, detail="成品还未生成")
    return FileResponse(task.output_video_path, filename=f"{task_id}.mp4")
