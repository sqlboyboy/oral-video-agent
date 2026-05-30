from pathlib import Path
from shutil import copyfileobj
from typing import Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .models import Asset, CreateTaskRequest, OralVideoTask, RenderOptions, RewriteRequest, TaskStatus, storage_dir
from .pipeline.renderer import Renderer
from .pipeline.subtitles import generate_srt
from .providers.asr import AsrProvider
from .providers.catalog import BUILT_IN_BGM, BUILT_IN_VOICES
from .providers.rewrite import RewriteProvider
from .providers.tts import VoiceProvider
from .repository import repo

app = FastAPI(title="智能口播智能体 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

asr_provider = AsrProvider()
rewrite_provider = RewriteProvider()
voice_provider = VoiceProvider()
renderer = Renderer()


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/voices")
def list_voices():
    return {"items": BUILT_IN_VOICES}


@app.get("/api/bgm")
def list_bgm():
    return {"items": BUILT_IN_BGM}


@app.get("/api/tasks")
def list_tasks():
    return {"items": repo.list()}


@app.post("/api/tasks")
def create_task(req: CreateTaskRequest) -> OralVideoTask:
    task = OralVideoTask(title=req.title, douyin_url=req.douyin_url)
    if req.douyin_url:
        task.status = TaskStatus.transcribed
        task.original_script = asr_provider.transcribe(None, req.douyin_url)
    return repo.put(task)


@app.post("/api/tasks/upload")
def upload_video(file: UploadFile = File(...)) -> OralVideoTask:
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    suffix = Path(file.filename).suffix or ".mp4"
    task = OralVideoTask(title=Path(file.filename).stem)
    upload_path = storage_dir("uploads") / f"{task.task_id}{suffix}"
    with upload_path.open("wb") as out:
        copyfileobj(file.file, out)
    task.source_video = Asset(kind="source_video", filename=file.filename, path=str(upload_path))
    task.status = TaskStatus.transcribed
    task.original_script = asr_provider.transcribe(None, file.filename)
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
    task.rewritten_script = rewrite_provider.rewrite(task.original_script, req)
    task.status = TaskStatus.rewritten
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
    voice_provider.synthesize(script, options.voice_id, audio_path)

    subtitle_path = storage_dir("subtitles") / f"{task_id}.srt"
    generate_srt(script, options.subtitle_style, subtitle_path)

    output_path = storage_dir("outputs") / f"{task_id}.mp4.txt"
    renderer.render(task_id, script, options, output_path)

    task.subtitle_path = str(subtitle_path)
    task.output_video_path = str(output_path)
    task.status = TaskStatus.completed
    return repo.put(task)


@app.get("/api/tasks/{task_id}/download")
def download_task(task_id: str):
    try:
        task = repo.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.output_video_path or not Path(task.output_video_path).exists():
        raise HTTPException(status_code=404, detail="成品还未生成")
    return FileResponse(task.output_video_path, filename=f"{task_id}.mp4")
