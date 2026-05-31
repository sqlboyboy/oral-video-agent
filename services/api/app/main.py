from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .asset_store import asset_store, save_upload
from .models import BgmTrack, CreateTaskRequest, OralVideoTask, RenderOptions, RewriteRequest, SubtitlePreviewRequest, TaskStatus, TaskSummary, UpdateTaskRequest, VoiceProfile, storage_dir
from .pipeline.renderer import Renderer
from .progress import complete_progress, start_progress
from .pipeline.subtitles import generate_srt, preview_subtitles
from .providers.asr import create_asr_provider
from .providers.catalog import BUILT_IN_BGM, BUILT_IN_VOICES
from .providers.rewrite import create_rewrite_provider
from .providers.rewrite_styles import REWRITE_STYLE_PRESETS
from .providers.tts import create_voice_provider
from .providers.video_importer import VideoImportError, VideoImporter
from .repository import repo
from .settings import get_settings

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

settings = get_settings()
asr_provider = create_asr_provider(settings)
rewrite_provider = create_rewrite_provider(settings)
voice_provider = create_voice_provider(settings)
video_importer = VideoImporter(cookies_file=settings.douyin_cookies_file)
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


@app.get("/api/health", tags=["system"])
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/version", tags=["system"])
def version():
    return {"name": "oral-video-agent-api", "version": app.version}


@app.get("/api/providers", tags=["system"])
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


@app.get("/api/voices", tags=["assets"])
def list_voices():
    return build_voice_catalog()


def build_voice_catalog():
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


@app.post("/api/voices/upload", tags=["assets"])
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


@app.get("/api/tasks", tags=["tasks"])
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


@app.post("/api/tasks", tags=["tasks"])
def create_task(req: CreateTaskRequest) -> OralVideoTask:
    task = OralVideoTask(title=req.title, douyin_url=req.douyin_url)
    if req.douyin_url:
        start_progress(task, "import")
        try:
            source_video = video_importer.import_from_share_text(req.douyin_url)
        except VideoImportError as exc:
            task.status = TaskStatus.failed
            task.error_message = str(exc)
            repo.put(task)
            raise HTTPException(status_code=400, detail=str(exc))
        task.source_video = source_video
        complete_progress(task, "import")
        start_progress(task, "transcribe")
        task.status = TaskStatus.transcribed
        task.original_script = asr_provider.transcribe(Path(source_video.path), source_video.filename)
        complete_progress(task, "transcribe")
    return repo.put(task)


@app.post("/api/tasks/upload", tags=["tasks"])
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

    paths = [task.extracted_audio_path, task.subtitle_path, task.output_video_path]
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
    start_progress(task, "rewrite")
    task.rewritten_script = rewrite_provider.rewrite(task.original_script, req)
    task.status = TaskStatus.rewritten
    complete_progress(task, "rewrite")
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

    task.status = TaskStatus.rendering
    task.render_options = options
    repo.put(task)

    audio_path = storage_dir("extracted_audio") / f"{task_id}_voice.wav"
    start_progress(task, "voice")
    voice_provider.synthesize(script, options.voice_id, audio_path)
    task.extracted_audio_path = str(audio_path)
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


@app.get("/api/tasks/{task_id}/output", tags=["tasks"])
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


@app.get("/api/tasks/{task_id}/download", tags=["tasks"])
def download_task(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.output_video_path or not Path(task.output_video_path).exists():
        raise HTTPException(status_code=404, detail="成品还未生成")
    return FileResponse(task.output_video_path, filename=f"{task_id}.mp4")
