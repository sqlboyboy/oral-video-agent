from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4


RENDER_OPTION_KEYS = {
    "script",
    "voice_id",
    "voice_reference_asset_id",
    "digital_human_id",
    "digital_human_engine",
    "mouth_aperture_enabled",
    "mouth_aperture_strength",
    "mouth_aperture_energy_threshold",
    "mouth_aperture_min_ratio",
    "mouth_aperture_max_ratio",
    "mouth_aperture_attack",
    "mouth_aperture_release",
    "motion_mode",
    "expression_mode",
    "voice_volume",
    "bgm_id",
    "bgm_volume",
    "subtitle_enabled",
    "subtitle_style",
    "pip_enabled",
    "pip_asset_id",
    "pip_position",
    "pip_scale",
    "pip_x",
    "pip_y",
    "pip_width",
    "pip_height",
    "pip_timing_mode",
    "pip_start_seconds",
    "pip_end_seconds",
    "pip_trigger_text",
}


MAX_REWRITE_CHARS = 300
DEFAULT_SUBTITLE_CHARS_PER_LINE = 12
DEFAULT_OUTPUT_FPS = ""
DEFAULT_HEYGEM_INPUT_FPS = "25"
DEFAULT_FFMPEG_PRESET = "veryfast"
DEFAULT_FFMPEG_CRF = "18"
DEFAULT_SUBTITLE_MARGIN_V = 70
DEFAULT_SUBTITLE_OUTLINE_WIDTH = 2
FALLBACK_OUTPUT_WIDTH = 1080
FALLBACK_OUTPUT_HEIGHT = 1920
PIP_MEDIA_ASPECT_RATIO = 16 / 9
PIP_MARGIN_X = 24
PIP_MARGIN_Y = 24

TRADITIONAL_PHRASE_REPLACEMENTS = (
    ("畫中畫", "画中画"),
    ("後臺", "后台"),
    ("前臺", "前台"),
    ("觀眾", "观众"),
    ("視頻", "视频"),
    ("音頻", "音频"),
    ("聲音", "声音"),
    ("雲端", "云端"),
    ("鏈接", "链接"),
    ("複製", "复制"),
    ("發布", "发布"),
    ("發佈", "发布"),
    ("預覽", "预览"),
    ("下載", "下载"),
    ("選擇", "选择"),
    ("設置", "设置"),
    ("啟用", "启用"),
    ("標題", "标题"),
    ("軟體", "软件"),
    ("檔案", "文件"),
    ("直播間", "直播间"),
)

TRADITIONAL_CHAR_MAP = str.maketrans(
    {
        "後": "后",
        "臺": "台",
        "開": "开",
        "關": "关",
        "觀": "观",
        "眾": "众",
        "視": "视",
        "頻": "频",
        "聲": "声",
        "雲": "云",
        "鏈": "链",
        "複": "复",
        "復": "复",
        "製": "制",
        "發": "发",
        "佈": "布",
        "預": "预",
        "覽": "览",
        "載": "载",
        "選": "选",
        "擇": "择",
        "設": "设",
        "啟": "启",
        "標": "标",
        "題": "题",
        "軟": "软",
        "體": "体",
        "檔": "档",
        "語": "语",
        "義": "义",
        "個": "个",
        "這": "这",
        "裡": "里",
        "裏": "里",
        "為": "为",
        "與": "与",
        "對": "对",
        "會": "会",
        "來": "来",
        "說": "说",
        "時": "时",
        "間": "间",
        "點": "点",
        "將": "将",
        "讓": "让",
        "還": "还",
        "過": "过",
        "應": "应",
        "該": "该",
        "幫": "帮",
        "刪": "删",
        "顯": "显",
        "圖": "图",
        "傳": "传",
        "導": "导",
        "獲": "获",
        "據": "据",
        "數": "数",
        "務": "务",
        "質": "质",
        "權": "权",
        "變": "变",
        "調": "调",
        "測": "测",
        "試": "试",
        "際": "际",
        "機": "机",
        "動": "动",
        "聽": "听",
        "寫": "写",
        "讀": "读",
        "區": "区",
        "號": "号",
        "頁": "页",
        "產": "产",
        "業": "业",
        "報": "报",
        "錯": "错",
        "處": "处",
        "長": "长",
        "萬": "万",
        "網": "网",
        "電": "电",
        "腦": "脑",
        "無": "无",
        "線": "线",
        "東": "东",
        "學": "学",
        "習": "习",
        "稱": "称",
        "職": "职",
        "實": "实",
        "驗": "验",
        "內": "内",
        "齣": "出",
    }
)


_OPENCC_NOT_LOADED = object()
_OPENCC_CONVERTER: Any = _OPENCC_NOT_LOADED


def opencc_converter() -> Any:
    global _OPENCC_CONVERTER
    if _OPENCC_CONVERTER is not _OPENCC_NOT_LOADED:
        return _OPENCC_CONVERTER
    try:
        from opencc import OpenCC  # type: ignore
        _OPENCC_CONVERTER = OpenCC("t2s")
    except Exception:
        _OPENCC_CONVERTER = None
    return _OPENCC_CONVERTER


def to_simplified_chinese(text: str) -> str:
    if not text:
        return text
    converter = opencc_converter()
    if converter is not None:
        return converter.convert(text)
    simplified = text
    for source, target in TRADITIONAL_PHRASE_REPLACEMENTS:
        simplified = simplified.replace(source, target)
    return simplified.translate(TRADITIONAL_CHAR_MAP)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def manage_gpu_services() -> bool:
    return env_bool("MANAGE_GPU_SERVICES", False)


def bounded_rewrite_chars(payload: dict[str, Any]) -> int:
    requested = payload.get("max_chars", os.getenv("MAX_REWRITE_CHARS", str(MAX_REWRITE_CHARS)))
    try:
        value = int(requested)
    except (TypeError, ValueError):
        value = MAX_REWRITE_CHARS
    return min(MAX_REWRITE_CHARS, max(20, value))


def ffmpeg_preset() -> str:
    return os.getenv("FFMPEG_X264_PRESET", DEFAULT_FFMPEG_PRESET).strip() or DEFAULT_FFMPEG_PRESET


def ffmpeg_crf() -> str:
    return os.getenv("FFMPEG_X264_CRF", DEFAULT_FFMPEG_CRF).strip() or DEFAULT_FFMPEG_CRF


def output_fps() -> str:
    value = os.getenv("OUTPUT_FPS", DEFAULT_OUTPUT_FPS).strip()
    if not value:
        return ""
    try:
        fps = float(value)
    except ValueError:
        return DEFAULT_OUTPUT_FPS
    if fps <= 0:
        return ""
    return str(int(fps)) if fps.is_integer() else f"{fps:g}"


def heygem_input_fps() -> str:
    value = os.getenv("HEYGEM_INPUT_FPS", DEFAULT_HEYGEM_INPUT_FPS).strip()
    try:
        fps = float(value)
    except ValueError:
        return DEFAULT_HEYGEM_INPUT_FPS
    if fps <= 0:
        return ""
    return str(int(fps)) if fps.is_integer() else f"{fps:g}"


def clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = minimum
    return max(minimum, min(maximum, numeric))


def portrait_main_video_filter(canvas_width: int, canvas_height: int) -> str:
    return (
        f"[0:v]scale={canvas_width}:{canvas_height}:flags=lanczos,"
        "setsar=1,setpts=PTS-STARTPTS[mainv]"
    )


def pip_layout(
    payload: dict[str, Any],
    canvas_width: int = FALLBACK_OUTPUT_WIDTH,
    canvas_height: int = FALLBACK_OUTPUT_HEIGHT,
) -> tuple[int, int, int, int]:
    position = str(payload.get("pip_position") or "top_right").strip().lower()
    if position == "fullscreen":
        return canvas_width, canvas_height, 0, 0

    width_source = payload["pip_width"] if "pip_width" in payload else payload.get("pip_scale", 0.28)
    width_norm = clamp_float(width_source, 0.05, 0.95)
    if payload.get("pip_height") is not None:
        height_norm = clamp_float(payload.get("pip_height"), 0.03, 0.95)
    else:
        height_norm = width_norm * canvas_width / canvas_height / PIP_MEDIA_ASPECT_RATIO
        height_norm = clamp_float(height_norm, 0.03, 0.95)

    width = max(2, min(canvas_width, int(round(canvas_width * width_norm))))
    height = max(2, min(canvas_height, int(round(canvas_height * height_norm))))
    width -= width % 2
    height -= height % 2
    max_x = max(0, canvas_width - width)
    max_y = max(0, canvas_height - height)
    margin_x = max(8, int(round(PIP_MARGIN_X * canvas_width / FALLBACK_OUTPUT_WIDTH)))
    margin_y = max(8, int(round(PIP_MARGIN_Y * canvas_height / FALLBACK_OUTPUT_HEIGHT)))
    positions = {
        "top_left": (margin_x, margin_y),
        "top_right": (max_x - margin_x, margin_y),
        "bottom_left": (margin_x, max_y - margin_y),
        "bottom_right": (max_x - margin_x, max_y - margin_y),
        "center": (max_x / 2, max_y / 2),
        "custom": (
            clamp_float(payload.get("pip_x", 0), 0, 1) * canvas_width,
            clamp_float(payload.get("pip_y", 0), 0, 1) * canvas_height,
        ),
    }
    raw_x, raw_y = positions.get(position, positions["top_right"])
    x = int(round(max(0, min(max_x, raw_x))))
    y = int(round(max(0, min(max_y, raw_y))))
    return width, height, x, y


def run_shell_command(command: str, *, label: str, timeout_seconds: int = 120) -> None:
    if not command.strip():
        return
    completed = subprocess.run(
        command,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{label} failed: {detail[-1000:]}")


def wait_for_health(url: str, *, label: str, timeout_seconds: int = 180) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            request_json(url, method="GET", timeout_seconds=5)
            return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"{label} did not become healthy: {last_error}")


def stop_heygem_service() -> None:
    command = os.getenv(
        "HEYGEM_STOP_COMMAND",
        "pids=$(lsof -t -i:6008 2>/dev/null || true); "
        "if [ -n \"$pids\" ]; then "
        "for pid in $pids; do pkill -TERM -P \"$pid\" 2>/dev/null || true; done; "
        "kill -TERM $pids 2>/dev/null || true; "
        "fi; "
        "sleep 3; "
        "if [ -n \"${pids:-}\" ]; then "
        "for pid in $pids; do pkill -KILL -P \"$pid\" 2>/dev/null || true; done; "
        "kill -KILL $pids 2>/dev/null || true; "
        "fi",
    )
    run_shell_command(command, label="stop HeyGem service")


def start_heygem_service() -> None:
    health_url = os.getenv("HEYGEM_HEALTH_URL", "http://127.0.0.1:6008/api/health")
    try:
        request_json(health_url, method="GET", timeout_seconds=5)
        return
    except Exception:
        pass
    command = os.getenv(
        "HEYGEM_START_COMMAND",
        "cd /root/HeyGem-Linux-Python-Hack && "
        "nohup ./start_api.sh >>/root/HeyGem-Linux-Python-Hack/api.log 2>&1 </dev/null &",
    )
    run_shell_command(command, label="start HeyGem service")
    wait_for_health(health_url, label="HeyGem service")


def stop_cosyvoice_service() -> None:
    command = os.getenv(
        "COSYVOICE_STOP_COMMAND",
        "pids=$(lsof -t -i:6010 2>/dev/null || true); "
        "if [ -n \"$pids\" ]; then "
        "for pid in $pids; do pkill -TERM -P \"$pid\" 2>/dev/null || true; done; "
        "kill -TERM $pids 2>/dev/null || true; "
        "fi; "
        "sleep 3; "
        "if [ -n \"${pids:-}\" ]; then "
        "for pid in $pids; do pkill -KILL -P \"$pid\" 2>/dev/null || true; done; "
        "kill -KILL $pids 2>/dev/null || true; "
        "fi",
    )
    run_shell_command(command, label="stop CosyVoice service")


def start_cosyvoice_service() -> None:
    health_url = os.getenv("COSYVOICE_HEALTH_URL", "http://127.0.0.1:6010/api/health")
    try:
        request_json(health_url, method="GET", timeout_seconds=5)
        return
    except Exception:
        pass
    command = os.getenv(
        "COSYVOICE_START_COMMAND",
        "cd /root/autodl-tmp/cosyvoice && "
        "nohup ./start_voice_api.sh >>/root/autodl-tmp/cosyvoice/voice_api.log 2>&1 </dev/null &",
    )
    run_shell_command(command, label="start CosyVoice service")
    wait_for_health(health_url, label="CosyVoice service")


def prepare_gpu_for_cosyvoice() -> None:
    if manage_gpu_services():
        stop_heygem_service()
        stop_cosyvoice_service()
    start_cosyvoice_service()


def prepare_gpu_for_heygem() -> None:
    if manage_gpu_services():
        stop_cosyvoice_service()
    start_heygem_service()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a cloud worker job through the local oral-video-agent API."
    )
    parser.add_argument(
        "job_json",
        nargs="?",
        default=os.getenv("ORAL_VIDEO_JOB_JSON"),
        help="Path to the worker-generated job JSON.",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=os.getenv("ORAL_VIDEO_OUTPUT_PATH"),
        help="Where the final MP4 must be written for the worker to upload.",
    )
    parser.add_argument(
        "--api-base",
        default=os.getenv("LOCAL_RENDER_API_BASE", "http://127.0.0.1:8000"),
        help="Local FastAPI render backend base URL.",
    )
    args = parser.parse_args()

    if not args.job_json:
        raise RuntimeError("job_json is required")
    if not args.output_path:
        raise RuntimeError("output_path is required")

    result = run_job(
        job_json=Path(args.job_json),
        output_path=Path(args.output_path),
        api_base=args.api_base,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def run_job(*, job_json: Path, output_path: Path, api_base: str) -> dict[str, Any]:
    job = json.loads(job_json.read_text(encoding="utf-8"))
    payload = dict(job.get("payload") or {})
    if is_preprocess_job(job):
        return run_preprocess_job(job=job, output_path=output_path)

    source_asset = find_source_asset(job)
    source_path = Path(source_asset["local_path"])
    if not source_path.exists():
        raise RuntimeError(f"source asset does not exist: {source_path}")

    render_payload = build_render_payload(payload)
    bgm_asset = find_bgm_audio_asset(job)
    pip_asset = find_pip_asset(job)
    voice_asset = find_voice_audio_asset(job)
    if voice_asset is not None:
        voice_path = Path(voice_asset["local_path"])
        if not voice_path.exists():
            raise RuntimeError(f"voice asset does not exist: {voice_path}")
        return render_direct_pipeline(
            source_video=source_path,
            voice_audio=voice_path,
            render_payload=render_payload,
            output_path=output_path,
            bgm_asset=bgm_asset,
            pip_asset=pip_asset,
            mode="heygem_direct",
        )

    voice_reference_asset = find_voice_reference_asset(job)
    if voice_reference_asset is not None:
        reference_path = Path(voice_reference_asset["local_path"])
        if not reference_path.exists():
            raise RuntimeError(f"voice reference asset does not exist: {reference_path}")
        voice_path = output_path.with_name(f"{output_path.stem}_voice.wav")
        prepare_gpu_for_cosyvoice()
        synthesize_voice_with_cosyvoice(
            reference_audio=reference_path,
            script=str(render_payload["script"]),
            output_path=voice_path,
        )
        prepare_gpu_for_heygem()
        result = render_direct_pipeline(
            source_video=source_path,
            voice_audio=voice_path,
            render_payload=render_payload,
            output_path=output_path,
            bgm_asset=bgm_asset,
            pip_asset=pip_asset,
            mode="cosyvoice_heygem_direct",
        )
        result["voice_reference_path"] = str(reference_path)
        return result

    api_base = api_base.rstrip("/")
    upload_response = upload_source_video(api_base=api_base, source_asset=source_asset)
    task_id = upload_response.get("task_id")
    if not task_id:
        raise RuntimeError(f"local API did not return task_id: {upload_response}")

    render_response = post_json(
        f"{api_base}/api/tasks/{task_id}/render",
        render_payload,
        timeout_seconds=timeout_seconds(),
    )
    if render_response.get("status") == "failed":
        detail = render_response.get("error_message") or "local render failed"
        raise RuntimeError(detail)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    local_output = render_response.get("output_video_path")
    if local_output and Path(local_output).exists():
        shutil.copyfile(local_output, output_path)
    else:
        download_file(
            url=f"{api_base}/api/tasks/{task_id}/download",
            dest=output_path,
            timeout_seconds=timeout_seconds(),
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"render output is empty: {output_path}")
    validate_render_output(output_path)

    return {
        "mode": "local_render_api",
        "task_id": task_id,
        "source_path": str(source_path),
        "output_path": str(output_path),
        "bytes": output_path.stat().st_size,
    }


def is_preprocess_job(job: dict[str, Any]) -> bool:
    payload = job.get("payload") or {}
    return job.get("job_type") == "preprocess" or payload.get("task_type") == "preprocess"


def run_preprocess_job(*, job: dict[str, Any], output_path: Path) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    operation = str(payload.get("operation") or "extract").strip().lower()
    if operation not in {"extract", "rewrite", "extract_rewrite", "voice"}:
        raise RuntimeError(f"unsupported preprocess operation: {operation}")
    if operation == "voice":
        return run_voice_preprocess_job(job=job, payload=payload, output_path=output_path)

    original_script = to_simplified_chinese(
        str(payload.get("source_script") or payload.get("original_script") or "").strip()
    )
    source_path: Path | None = None
    if operation in {"extract", "extract_rewrite"} and not original_script:
        source_asset = find_source_asset(job)
        source_path = Path(source_asset["local_path"])
        if not source_path.exists():
            raise RuntimeError(f"source asset does not exist: {source_path}")
        audio_path = output_path.with_name(f"{output_path.stem}_preprocess.wav")
        extract_audio_for_asr(source_path, audio_path)
        original_script = to_simplified_chinese(
            transcribe_audio(audio_path, source_hint=str(source_asset.get("file_name") or source_path.name))
        )

    if not original_script:
        raise RuntimeError("云端文案处理需要上传视频文件或提供原始文案")

    result: dict[str, Any] = {
        "mode": "preprocess",
        "operation": operation,
        "original_script": original_script,
    }
    if operation in {"rewrite", "extract_rewrite"}:
        result["rewritten_script"] = rewrite_script(original_script, payload)
    if source_path is not None:
        result["source_path"] = str(source_path)
    return result


def run_voice_preprocess_job(
    *,
    job: dict[str, Any],
    payload: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    script = to_simplified_chinese(
        str(
            payload.get("script")
            or payload.get("source_script")
            or payload.get("rewritten_script")
            or payload.get("original_script")
            or ""
        ).strip()
    )
    if not script:
        raise RuntimeError("voice preprocess requires script text")
    reference_asset = find_voice_reference_asset(job)
    if reference_asset is None:
        raise RuntimeError("voice preprocess requires a voice_reference asset")
    reference_path = Path(reference_asset["local_path"])
    if not reference_path.exists():
        raise RuntimeError(f"voice reference asset does not exist: {reference_path}")
    output_path = output_path.with_suffix(".wav")
    prepare_gpu_for_cosyvoice()
    synthesize_voice_with_cosyvoice(
        reference_audio=reference_path,
        script=script,
        output_path=output_path,
    )
    normalize_audio_loudness(output_path)
    result: dict[str, Any] = {
        "mode": "preprocess",
        "operation": "voice",
        "voice_audio_path": str(output_path),
        "bytes": output_path.stat().st_size,
        "output_file_name": str(payload.get("output_file_name") or output_path.name),
        "output_content_type": str(payload.get("output_content_type") or "audio/wav"),
    }
    output_cos_key = payload.get("output_cos_key")
    if output_cos_key:
        result["output_cos_key"] = str(output_cos_key)
    return result


def extract_audio_for_asr(source_video: Path, output_audio: Path) -> None:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for cloud transcript extraction")
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_audio),
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0 or not output_audio.exists() or output_audio.stat().st_size <= 44:
        detail = completed.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"ffmpeg audio extraction failed: {detail}")


def transcribe_audio(audio_path: Path, *, source_hint: str = "") -> str:
    provider = os.getenv("ASR_PROVIDER", "faster-whisper").strip().lower()
    if provider in {"placeholder", "mock"}:
        return f"这是从视频中识别出的口播内容示例。来源：{source_hint}。"
    model_name = os.getenv("WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "cuda")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "float16" if device == "cuda" else "int8")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("AutoDL 缺少 faster-whisper，请先安装云端 ASR 依赖") from exc

    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, _ = model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
    except Exception:
        if device == "cpu":
            raise
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
    text = post_process_transcript("".join(segment.text for segment in segments).strip())
    if not text:
        raise RuntimeError("云端 ASR 未识别到语音内容")
    return text


def post_process_transcript(text: str) -> str:
    text = to_simplified_chinese(text)
    chunks = [
        chunk.strip(" ，,。.!！?？")
        for chunk in re.split(r"[，,。.!！?？；;\n]+", text)
        if chunk.strip(" ，,。.!！?？")
    ]
    cleaned: list[str] = []
    for chunk in chunks:
        if cleaned and cleaned[-1] == chunk:
            continue
        cleaned.append(chunk)
    while len(cleaned) > 3 and cleaned[-1] == cleaned[-2] == cleaned[-3]:
        repeated = cleaned[-1]
        while len(cleaned) > 1 and cleaned[-2] == repeated:
            cleaned.pop()
    return "，".join(cleaned)


def rewrite_script(original_script: str, payload: dict[str, Any]) -> str:
    provider = os.getenv("REWRITE_PROVIDER", "deepseek").strip().lower()
    if provider in {"placeholder", "mock"}:
        return light_paraphrase(original_script)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("AutoDL 未配置 DEEPSEEK_API_KEY，无法云端仿写")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    prompt = build_rewrite_prompt(original_script, payload)
    response = post_json(
        f"{base_url}/chat/completions",
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是专业的中文短视频口播文案策划，只输出可直接口播的原创简体中文文案。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
            "stream": False,
        },
        timeout_seconds=int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120")),
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        rewritten = str(response["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"DeepSeek 文案改写失败：{response}") from exc
    if not rewritten:
        raise RuntimeError("DeepSeek 文案改写失败：API 返回了空内容")
    return format_spoken_lines(rewritten)


def build_rewrite_prompt(original_script: str, payload: dict[str, Any]) -> str:
    original_script = to_simplified_chinese(original_script)
    product = str(payload.get("product_info") or "不额外添加产品信息")
    audience = str(payload.get("target_audience") or "不额外指定人群")
    style = str(payload.get("style") or "同款口播")
    max_chars = bounded_rewrite_chars(payload)
    return (
        "你是中文短视频口播文案仿写助手。请做同主题原创仿写，而不是只加标点或营销扩写。\n"
        "必须保留原文的主题、表达顺序、情绪、语气和大致字数，但要重组句子并替换表达。\n"
        "不要新增原文没有的信息，不要输出标题、标签、解释或占位符。\n"
        f"最终文案不超过 {max_chars} 字，只使用中文简体，不要输出繁体字；不要包含任何中英文标点符号，只使用换行表示自然停顿。\n\n"
        f"仿写风格：{style}\n"
        f"产品/服务：{product}\n"
        f"目标人群：{audience}\n\n"
        f"原口播文本：\n{original_script}"
    )


def light_paraphrase(text: str) -> str:
    replacements = [
        ("Hello", "哈喽"),
        ("hello", "哈喽"),
        ("大家好", "大家好呀"),
        ("今天", "今天呢"),
        ("终于", "总算"),
        ("鼓足勇气", "攒够勇气"),
        ("第一条视频", "第一支视频"),
        ("希望你能", "希望大家可以"),
        ("给我点个关注", "点个关注支持一下"),
    ]
    result = to_simplified_chinese(text).strip()
    for source, target in replacements:
        result = result.replace(source, target)
    return format_spoken_lines(result)


def format_spoken_lines(text: str, max_line_chars: int = 28) -> str:
    text = to_simplified_chinese(text)
    cleaned = re.sub(r"\s+", "", text.strip())
    cleaned = re.sub(r"[，,。！？!?；;：:、\"“”'‘’（）()【】《》<>….\-—_~～]+", "\n", cleaned)
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = raw.strip()
        while len(line) > max_line_chars:
            lines.append(line[:max_line_chars])
            line = line[max_line_chars:]
        if line:
            lines.append(line)
    return "\n".join(lines) if lines else text.strip()


def find_source_asset(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") or {}
    assets = list(job.get("input_assets") or payload.get("input_assets") or [])
    if not assets:
        raise RuntimeError("job has no input assets")

    def is_video(asset: dict[str, Any]) -> bool:
        content_type = str(asset.get("content_type") or "").lower()
        file_name = str(asset.get("file_name") or asset.get("local_path") or "").lower()
        return (
            asset.get("kind") == "source_video"
            or content_type.startswith("video/")
            or file_name.endswith((".mp4", ".mov", ".m4v", ".avi", ".webm"))
        )

    for asset in assets:
        if is_video(asset):
            if not asset.get("local_path"):
                raise RuntimeError(f"source asset missing local_path: {asset.get('asset_id')}")
            return asset
    raise RuntimeError("job has no video input asset")


def find_voice_audio_asset(job: dict[str, Any]) -> dict[str, Any] | None:
    payload = job.get("payload") or {}
    assets = list(job.get("input_assets") or payload.get("input_assets") or [])

    def is_voice(asset: dict[str, Any]) -> bool:
        content_type = str(asset.get("content_type") or "").lower()
        file_name = str(asset.get("file_name") or asset.get("local_path") or "").lower()
        kind = str(asset.get("kind") or "")
        if kind in {
            "voice_reference",
            "bgm_audio",
            "background_music",
            "pip_asset",
            "picture_in_picture",
            "source_video",
            "thumbnail",
            "output",
        }:
            return False
        if kind:
            return kind in {"voice_audio", "generated_voice", "audio"}
        return (
            content_type.startswith("audio/")
            or file_name.endswith((".wav", ".mp3", ".m4a", ".aac"))
        )

    for asset in assets:
        if is_voice(asset):
            if not asset.get("local_path"):
                raise RuntimeError(f"voice asset missing local_path: {asset.get('asset_id')}")
            return asset
    return None


def find_voice_reference_asset(job: dict[str, Any]) -> dict[str, Any] | None:
    payload = job.get("payload") or {}
    assets = list(job.get("input_assets") or payload.get("input_assets") or [])
    for asset in assets:
        if asset.get("kind") == "voice_reference":
            if not asset.get("local_path"):
                raise RuntimeError(f"voice reference asset missing local_path: {asset.get('asset_id')}")
            return asset
    return None


def find_bgm_audio_asset(job: dict[str, Any]) -> dict[str, Any] | None:
    return find_asset_by_kind(job, {"bgm_audio", "background_music"})


def find_pip_asset(job: dict[str, Any]) -> dict[str, Any] | None:
    return find_asset_by_kind(job, {"pip_asset", "picture_in_picture"})


def find_asset_by_kind(job: dict[str, Any], kinds: set[str]) -> dict[str, Any] | None:
    payload = job.get("payload") or {}
    assets = list(job.get("input_assets") or payload.get("input_assets") or [])
    for asset in assets:
        if str(asset.get("kind") or "") in kinds:
            if not asset.get("local_path"):
                raise RuntimeError(f"{asset.get('kind')} asset missing local_path: {asset.get('asset_id')}")
            return asset
    return None


def build_render_payload(payload: dict[str, Any]) -> dict[str, Any]:
    render_payload = {
        key: value
        for key, value in payload.items()
        if key in RENDER_OPTION_KEYS and value is not None
    }
    script = (
        str(render_payload.get("script") or "").strip()
        or str(payload.get("rewritten_script") or "").strip()
        or str(payload.get("original_script") or "").strip()
    )
    if not script:
        raise RuntimeError("render script is required")
    render_payload["script"] = script
    return render_payload


def upload_source_video(*, api_base: str, source_asset: dict[str, Any]) -> dict[str, Any]:
    source_path = Path(source_asset["local_path"])
    file_name = str(source_asset.get("file_name") or source_path.name)
    content_type = str(
        source_asset.get("content_type")
        or mimetypes.guess_type(file_name)[0]
        or "video/mp4"
    )
    fields = {
        "file": {
            "filename": file_name,
            "content_type": content_type,
            "path": source_path,
        }
    }
    body, content_type_header = encode_multipart(fields)
    return request_json(
        f"{api_base}/api/tasks/upload",
        method="POST",
        body=body,
        headers={"Content-Type": content_type_header},
        timeout_seconds=timeout_seconds(),
    )


def prepare_heygem_source_video(source_video: Path, output_path: Path) -> Path:
    fps = heygem_input_fps()
    ffmpeg = ffmpeg_executable()
    if not fps or ffmpeg is None:
        return source_video
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video),
        "-an",
        "-vf",
        f"fps={fps}",
        "-c:v",
        "libx264",
        "-preset",
        ffmpeg_preset(),
        "-crf",
        ffmpeg_crf(),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
        output_path.unlink(missing_ok=True)
        return source_video
    return output_path


def render_with_heygem(*, source_video: Path, voice_audio: Path, output_path: Path) -> None:
    prepare_gpu_for_heygem()
    base_url = os.getenv("HEYGEM_BASE_URL", "http://127.0.0.1:6008").rstrip("/")
    timeout = int(os.getenv("HEYGEM_TIMEOUT_SECONDS", "3600") or "3600")
    with voice_audio.open("rb") as audio_file, source_video.open("rb") as video_file:
        response = post_multipart(
            f"{base_url}/api/jobs",
            fields={"short_video_mode": os.getenv("HEYGEM_SHORT_VIDEO_MODE", "repeat")},
            files={
                "audio_file": (voice_audio.name, audio_file.read(), "audio/wav"),
                "video_file": (source_video.name, video_file.read(), "video/mp4"),
            },
            timeout_seconds=timeout,
        )
    job_id = str(response.get("job_id") or "")
    if not job_id:
        raise RuntimeError(f"HeyGem did not return job_id: {response}")

    deadline = time.time() + timeout
    last_response = response
    while time.time() < deadline:
        time.sleep(2)
        try:
            last_response = request_json(
                f"{base_url}/api/jobs/{job_id}",
                method="GET",
                timeout_seconds=30,
            )
        except Exception:
            continue

        status = str(last_response.get("status") or "").lower()
        if status == "failed":
            raise RuntimeError(f"HeyGem render failed: {last_response.get('error') or last_response}")
        if status == "succeeded":
            result_url = str(last_response.get("result_url") or "")
            if not result_url:
                raise RuntimeError(f"HeyGem succeeded without result_url: {last_response}")
            download_file(
                url=f"{base_url}{result_url}",
                dest=output_path,
                timeout_seconds=180,
            )
            try:
                request_json(
                    f"{base_url}/api/jobs/{job_id}",
                    method="DELETE",
                    timeout_seconds=20,
                )
            except Exception:
                pass
            return

    raise RuntimeError(f"HeyGem render timed out: {last_response}")


def render_direct_pipeline(
    *,
    source_video: Path,
    voice_audio: Path,
    render_payload: dict[str, Any],
    output_path: Path,
    bgm_asset: dict[str, Any] | None,
    pip_asset: dict[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    validate_direct_composition_assets(
        render_payload=render_payload,
        bgm_asset=bgm_asset,
        pip_asset=pip_asset,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    digital_path = output_path.with_name(f"{output_path.stem}_digital.mp4")
    heygem_source_path = prepare_heygem_source_video(
        source_video,
        output_path.with_name(f"{output_path.stem}_heygem_source.mp4"),
    )
    render_with_heygem(
        source_video=heygem_source_path,
        voice_audio=voice_audio,
        output_path=digital_path,
    )
    validate_render_output(digital_path)

    bgm_audio = Path(bgm_asset["local_path"]) if bgm_asset is not None else None
    pip_media = Path(pip_asset["local_path"]) if pip_asset is not None else None
    composition_diagnostics: dict[str, Any] = {}
    if should_compose_final(render_payload, bgm_audio, pip_media):
        compose_final_video(
            source_video=digital_path,
            voice_audio=voice_audio,
            render_payload=render_payload,
            output_path=output_path,
            bgm_audio=bgm_audio,
            pip_asset=pip_media,
        )
        composition_diagnostics = dict(
            getattr(compose_final_video, "last_diagnostics", {}) or {}
        )
    else:
        shutil.copyfile(digital_path, output_path)
    validate_render_output(output_path)
    return {
        "mode": mode,
        "source_path": str(source_video),
        "heygem_source_path": str(heygem_source_path),
        "voice_audio_path": str(voice_audio),
        "digital_path": str(digital_path),
        "output_path": str(output_path),
        "bytes": output_path.stat().st_size,
        "composed": output_path != digital_path,
        "pip_requested": render_payload.get("pip_enabled") is True,
        "pip_asset_path": str(pip_media) if pip_media is not None else None,
        "pip_composed": bool(composition_diagnostics.get("pip_composed")),
        "composition": composition_diagnostics,
    }


def should_compose_final(
    render_payload: dict[str, Any],
    bgm_audio: Path | None,
    pip_asset: Path | None,
) -> bool:
    return (
        render_payload.get("subtitle_enabled") is not False
        or bgm_audio is not None
        or (render_payload.get("pip_enabled") is True and pip_asset is not None)
        or render_payload.get("voice_volume") is not None
    )


def validate_direct_composition_assets(
    *,
    render_payload: dict[str, Any],
    bgm_asset: dict[str, Any] | None,
    pip_asset: dict[str, Any] | None,
) -> None:
    if is_bgm_requested(render_payload) and bgm_asset is None:
        raise RuntimeError("云端生成需要上传 BGM 音频素材，请重新选择 BGM 后再生成。")
    if render_payload.get("pip_enabled") is True and pip_asset is None:
        raise RuntimeError("云端生成需要上传画中画素材，请先上传画中画后再生成。")


def is_bgm_requested(render_payload: dict[str, Any]) -> bool:
    bgm_id = str(render_payload.get("bgm_id") or "").strip().lower()
    return bool(bgm_id) and bgm_id not in {"none", "off", "disabled"}


def compose_final_video(
    *,
    source_video: Path,
    voice_audio: Path,
    render_payload: dict[str, Any],
    output_path: Path,
    bgm_audio: Path | None,
    pip_asset: Path | None,
) -> None:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for subtitle/BGM/PIP composition")

    voice_duration = media_duration_seconds(voice_audio)
    command = [ffmpeg, "-y", "-i", str(source_video), "-i", str(voice_audio)]
    filter_parts: list[str] = []
    audio_output = "[aout]"
    pip_input_index = 2

    raw_voice_volume = render_payload.get("voice_volume")
    voice_volume = 0.45 if raw_voice_volume is None else float(raw_voice_volume)
    voice_filter = f"dynaudnorm=f=150:g=15:p=0.9,volume={voice_volume}"
    if bgm_audio is not None:
        command.extend(["-i", str(bgm_audio)])
        pip_input_index = 3
        raw_bgm_volume = render_payload.get("bgm_volume")
        bgm_volume = 0.35 if raw_bgm_volume is None else float(raw_bgm_volume)
        bgm_filter = (
            f"dynaudnorm=f=150:g=15:p=0.9,volume={bgm_volume},"
            "aloop=loop=-1:size=2147483647"
        )
        filter_parts.append(f"[1:a]{voice_filter}[voice]")
        filter_parts.append(f"[2:a]{bgm_filter}[bgm]")
        filter_parts.append("[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]")
    else:
        filter_parts.append(f"[1:a]{voice_filter}[aout]")

    has_pip_filter = render_payload.get("pip_enabled") is True and pip_asset is not None
    has_subtitle_filter = render_payload.get("subtitle_enabled") is not False
    has_video_filter = has_pip_filter or has_subtitle_filter
    video_output = "0:v:0"
    if has_video_filter:
        canvas_width, canvas_height = canvas_dimensions(source_video)
        video_input = "[mainv]"
        filter_parts.append(portrait_main_video_filter(canvas_width, canvas_height))
    pip_composed = False
    if has_pip_filter:
        if pip_asset.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            command.extend(["-loop", "1", "-i", str(pip_asset)])
        else:
            command.extend(["-stream_loop", "-1", "-i", str(pip_asset)])
        pip_width, pip_height, pip_x, pip_y = pip_layout(
            render_payload,
            canvas_width,
            canvas_height,
        )
        filter_parts.append(
            f"[{pip_input_index}:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=increase,"
            f"crop={pip_width}:{pip_height},setsar=1,setpts=PTS-STARTPTS[pip]"
        )
        enable_expr = pip_enable_expression(render_payload, voice_duration)
        enable_part = f":enable='{enable_expr}'" if enable_expr else ""
        filter_parts.append(
            f"{video_input}[pip]overlay={pip_x}:{pip_y}{enable_part}:eof_action=pass[basev]"
        )
        video_input = "[basev]"
        pip_composed = True

    subtitle_file: Path | None = None
    if has_subtitle_filter:
        script = str(render_payload.get("script") or "")
        style = dict(render_payload.get("subtitle_style") or {})
        subtitle_file = output_path.with_suffix(".srt")
        generate_srt_file(script, style, subtitle_file, voice_duration)
        subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(
            f"{video_input}subtitles='{subtitle_path}':force_style='{subtitle_force_style(style)}'[vout]"
        )
        video_output = "[vout]"
    elif has_video_filter:
        filter_parts.append(f"{video_input}null[vout]")
        video_output = "[vout]"

    command.extend([
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        video_output,
        "-map",
        audio_output,
    ])
    if has_video_filter:
        command.extend([
            "-c:v",
            "libx264",
            "-preset",
            ffmpeg_preset(),
            "-crf",
            ffmpeg_crf(),
            "-pix_fmt",
            "yuv420p",
        ])
        fps = output_fps() or media_video_frame_rate(source_video)
        if fps:
            command.extend(["-r", fps])
    else:
        command.extend(["-c:v", "copy"])
    command.extend([
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg final composition failed: {completed.returncode}")
    compose_final_video.last_diagnostics = {
        "pip_composed": pip_composed,
        "pip_asset": str(pip_asset) if pip_asset is not None else None,
        "filter_complex": ";".join(filter_parts),
    }


def synthesize_voice_with_cosyvoice(
    *,
    reference_audio: Path,
    script: str,
    output_path: Path,
) -> None:
    start_cosyvoice_service()
    max_chars = int(os.getenv("COSYVOICE_MAX_CHARS_PER_REQUEST", "120") or "120")
    chunks = split_tts_script(script, max_chars=max_chars)
    if len(chunks) > 1:
        part_paths: list[Path] = []
        for index, chunk in enumerate(chunks, start=1):
            part_path = output_path.with_name(
                f"{output_path.stem}_part_{index:03d}{output_path.suffix}"
            )
            synthesize_cosyvoice_chunk_with_retry(
                reference_audio=reference_audio,
                script=chunk,
                output_path=part_path,
            )
            part_paths.append(part_path)
        concatenate_wav_files(part_paths, output_path)
        validate_wav_output(output_path)
        return

    synthesize_cosyvoice_chunk_with_retry(
        reference_audio=reference_audio,
        script=chunks[0] if chunks else script,
        output_path=output_path,
    )


def synthesize_cosyvoice_chunk_with_retry(
    *,
    reference_audio: Path,
    script: str,
    output_path: Path,
) -> None:
    attempts = 2 if manage_gpu_services() else 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            synthesize_cosyvoice_chunk(
                reference_audio=reference_audio,
                script=script,
                output_path=output_path,
            )
            return
        except RuntimeError as exc:
            last_error = exc
            if "out of memory" not in str(exc).lower() or attempt + 1 >= attempts:
                break
            stop_cosyvoice_service()
            start_cosyvoice_service()
    raise last_error or RuntimeError("CosyVoice synthesis failed")


def synthesize_cosyvoice_chunk(
    *,
    reference_audio: Path,
    script: str,
    output_path: Path,
) -> None:
    base_url = os.getenv("COSYVOICE_BASE_URL", "http://127.0.0.1:6010").rstrip("/")
    timeout = int(os.getenv("COSYVOICE_TIMEOUT_SECONDS", "1800") or "1800")
    with reference_audio.open("rb") as reference_file:
        body, content_type = encode_multipart_request(
            fields={"text": script},
            files={
                "reference_file": (
                    reference_audio.name,
                    reference_file.read(),
                    mimetypes.guess_type(reference_audio.name)[0] or "audio/wav",
                )
            },
        )
    request = urllib.request.Request(
        f"{base_url}/api/voice",
        data=body,
        method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_bytes = response.read()
            response_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CosyVoice API failed: {exc.code} {detail}") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if "json" not in response_type.lower():
        output_path.write_bytes(response_bytes)
    else:
        response_json = json.loads(response_bytes.decode("utf-8"))
        audio_url = str(response_json.get("audio_url") or response_json.get("result_url") or "")
        if audio_url:
            download_file(
                url=f"{base_url}{audio_url}" if audio_url.startswith("/") else audio_url,
                dest=output_path,
                timeout_seconds=180,
            )
            validate_wav_output(output_path)
            return
        audio_base64 = response_json.get("audio_base64")
        if audio_base64:
            import base64

            output_path.write_bytes(base64.b64decode(str(audio_base64)))
        else:
            raise RuntimeError(f"CosyVoice did not return audio output: {response_json}")
    validate_wav_output(output_path)


def split_tts_script(script: str, *, max_chars: int) -> list[str]:
    text = re.sub(r"\s+", "", script or "").strip()
    if not text:
        return [""]
    max_chars = max(40, max_chars)
    chunks: list[str] = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars or (
            len(current) >= max_chars * 0.6 and char in "。！？!?；;，,"
        ):
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def concatenate_wav_files(parts: list[Path], output_path: Path) -> None:
    if not parts:
        raise RuntimeError("no CosyVoice audio parts were generated")
    if len(parts) == 1:
        shutil.copyfile(parts[0], output_path)
        return
    params = None
    frames: list[bytes] = []
    for part in parts:
        with wave.open(str(part), "rb") as wav:
            current_params = wav.getparams()
            if params is None:
                params = current_params
            elif current_params[:3] != params[:3]:
                concatenate_wav_files_with_ffmpeg(parts, output_path)
                return
            frames.append(wav.readframes(wav.getnframes()))
    if params is None:
        raise RuntimeError("CosyVoice audio parts are invalid")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out:
        out.setparams(params)
        for frame_bytes in frames:
            out.writeframes(frame_bytes)


def concatenate_wav_files_with_ffmpeg(parts: list[Path], output_path: Path) -> None:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to concatenate CosyVoice audio parts")
    concat_file = output_path.with_suffix(".concat.txt")
    concat_file.write_text(
        "\n".join(f"file '{escape_ffmpeg_concat_path(part)}'" for part in parts),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output_path)],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg audio concat failed: {completed.returncode}")


def escape_ffmpeg_concat_path(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def validate_wav_output(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 44:
        raise RuntimeError(f"voice output is empty: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnframes() <= 0 or wav.getframerate() <= 0:
                raise RuntimeError(f"voice output has no frames: {path}")
    except wave.Error as exc:
        raise RuntimeError(f"voice output is not a valid WAV: {path}") from exc


def ffmpeg_executable() -> str | None:
    return os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")


def normalize_audio_loudness(path: Path) -> None:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for voice loudness normalization")
    normalized_path = path.with_name(f"{path.stem}_normalized.wav")
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-vn",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "44100",
            str(normalized_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if (
        completed.returncode != 0
        or not normalized_path.exists()
        or normalized_path.stat().st_size <= 44
    ):
        normalized_path.unlink(missing_ok=True)
        detail = completed.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"voice loudness normalization failed: {detail}")
    normalized_path.replace(path)


def media_video_dimensions(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "csv=p=0:s=x",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            output = getattr(completed, "stdout", "") or ""
            match = re.fullmatch(r"\s*(\d+)x(\d+)\s*", output)
            if completed.returncode == 0 and match:
                width, height = int(match.group(1)), int(match.group(2))
                if width > 0 and height > 0:
                    return width, height
        except (OSError, subprocess.TimeoutExpired):
            pass

    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = getattr(completed, "stdout", "") or ""
    for line in output.splitlines():
        if "Video:" not in line:
            continue
        match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def normalized_frame_rate(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if "/" in raw:
            numerator_text, denominator_text = raw.split("/", 1)
            denominator = float(denominator_text)
            if denominator == 0:
                return None
            fps = float(numerator_text) / denominator
        else:
            fps = float(raw)
    except ValueError:
        return None
    if fps <= 0 or fps > 240:
        return None
    return str(int(fps)) if fps.is_integer() else f"{fps:.6f}".rstrip("0").rstrip(".")


def media_video_frame_rate(path: Path) -> str | None:
    if not path.exists():
        return None
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=avg_frame_rate",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            if completed.returncode == 0:
                normalized = normalized_frame_rate(getattr(completed, "stdout", "") or "")
                if normalized:
                    return normalized
        except (OSError, subprocess.TimeoutExpired):
            pass

    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = getattr(completed, "stdout", "") or ""
    for line in output.splitlines():
        if "Video:" not in line:
            continue
        match = re.search(r"\b(\d+(?:\.\d+)?)\s+fps\b", line)
        if match:
            return normalized_frame_rate(match.group(1))
    return None


def canvas_dimensions(source_video: Path) -> tuple[int, int]:
    dimensions = media_video_dimensions(source_video)
    if dimensions is None:
        return FALLBACK_OUTPUT_WIDTH, FALLBACK_OUTPUT_HEIGHT
    width, height = dimensions
    return max(2, width - width % 2), max(2, height - height % 2)


def media_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        duration = float(completed.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


_SUBTITLE_BREAK_CHARS = "。！？!?；;"
_SUBTITLE_LINES_PER_CAPTION = 2


def subtitle_sentence_units(paragraph: str) -> list[str]:
    units: list[str] = []
    current = ""
    for char in paragraph:
        current += char
        if char in _SUBTITLE_BREAK_CHARS:
            units.append(current.strip())
            current = ""
    if current.strip():
        units.append(current.strip())
    return units


def split_subtitle_unit(unit: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in unit:
        current += char
        if len(current) >= max_chars:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def group_subtitle_lines(lines: list[str]) -> list[str]:
    captions: list[str] = []
    for index in range(0, len(lines), _SUBTITLE_LINES_PER_CAPTION):
        captions.append("\n".join(lines[index:index + _SUBTITLE_LINES_PER_CAPTION]))
    return captions


def wrap_text(text: str, max_chars: int) -> list[str]:
    max_chars = max(1, int(max_chars or DEFAULT_SUBTITLE_CHARS_PER_LINE))
    captions: list[str] = []
    text = to_simplified_chinese(text)
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()] or [text.strip()]
    for paragraph in paragraphs:
        for unit in subtitle_sentence_units(paragraph):
            captions.extend(group_subtitle_lines(split_subtitle_unit(unit, max_chars)))
    return captions or [text]


def generate_srt_file(
    script: str,
    style: dict[str, Any],
    output_path: Path,
    duration_seconds: float | None,
) -> None:
    lines = wrap_text(script, int(style.get("max_chars_per_line") or DEFAULT_SUBTITLE_CHARS_PER_LINE))
    seconds_per_line = 1.0 if not duration_seconds else max(0.8, duration_seconds / max(1, len(lines)))
    blocks = []
    for index, line in enumerate(lines, start=1):
        start = (index - 1) * seconds_per_line
        end = index * seconds_per_line
        if duration_seconds is not None and index == len(lines):
            end = max(end, duration_seconds)
        blocks.append(f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{line}\n")
    output_path.write_text("\n".join(blocks), encoding="utf-8")


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000
    minutes = milliseconds // 60_000
    milliseconds %= 60_000
    secs = milliseconds // 1000
    millis = milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def subtitle_force_style(style: dict[str, Any]) -> str:
    return ",".join(
        [
            f"FontName={style.get('font_family') or 'Microsoft YaHei'}",
            f"FontSize={int(style.get('font_size') or 12)}",
            "Bold=1",
            "BorderStyle=1",
            f"Outline={int(style.get('outline_width') or DEFAULT_SUBTITLE_OUTLINE_WIDTH)}",
            "Shadow=0",
            f"PrimaryColour={ass_color(str(style.get('color') or '#FFE600'), '#FFE600')}",
            f"OutlineColour={ass_color(str(style.get('outline_color') or '#000000'), '#000000')}",
            "Alignment=2",
            f"MarginV={int(style.get('margin_v') or DEFAULT_SUBTITLE_MARGIN_V)}",
        ]
    )


def ass_color(hex_color: str, fallback: str) -> str:
    value = (hex_color or fallback).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6 or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = fallback.strip().lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"&H00{blue:02X}{green:02X}{red:02X}&"


def pip_overlay_position(position: str) -> str:
    _, _, x, y = pip_layout({"pip_position": position})
    return f"{x}:{y}"


def pip_enable_expression(
    payload: dict[str, Any],
    duration_seconds: float | None = None,
) -> str | None:
    mode = str(payload.get("pip_timing_mode") or "full").lower()
    start = payload.get("pip_start_seconds")
    end = payload.get("pip_end_seconds")
    if mode == "sentence":
        range_text = str(payload.get("pip_trigger_text") or "").strip()
        if start is None and range_text:
            duration = duration_seconds
            if duration is None:
                duration = float(payload.get("duration_seconds") or 0) or None
            match = subtitle_time_range_for_text(payload, range_text, duration)
            if match:
                start, end = match
    if mode not in {"time", "sentence"} or start is None:
        return None
    start_float = max(0.0, float(start))
    if end is None or float(end) <= start_float:
        return f"gte(t\\,{start_float:.3f})"
    return f"between(t\\,{start_float:.3f}\\,{float(end):.3f})"


def subtitle_time_range_for_text(
    payload: dict[str, Any],
    query: str,
    duration_seconds: float | None,
) -> tuple[float, float] | None:
    needle = "".join(query.split())
    if not needle:
        return None
    style = dict(payload.get("subtitle_style") or {})
    lines = wrap_text(str(payload.get("script") or ""), int(style.get("max_chars_per_line") or DEFAULT_SUBTITLE_CHARS_PER_LINE))
    seconds_per_line = 1.0 if not duration_seconds else max(0.8, duration_seconds / max(1, len(lines)))
    for index, line in enumerate(lines):
        compact_line = "".join(line.split())
        if needle in compact_line or compact_line in needle:
            start = index * seconds_per_line
            end = (index + 1) * seconds_per_line
            if duration_seconds is not None:
                end = min(max(end, start + 0.8), duration_seconds)
            return start, end
    return None


def encode_multipart(fields: dict[str, dict[str, Any]]) -> tuple[bytes, str]:
    boundary = f"----oral-video-agent-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        path = Path(value["path"])
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{value["filename"]}"\r\n'
                f'Content-Type: {value["content_type"]}\r\n\r\n'
            ).encode("utf-8")
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def encode_multipart_request(
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----oral-video-agent-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode(
                "utf-8"
            )
        )
    for name, (file_name, data, content_type) in files.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{file_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post_multipart(
    url: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    timeout_seconds: int,
) -> dict[str, Any]:
    body, content_type = encode_multipart_request(fields=fields, files=files)
    return request_json(
        url,
        method="POST",
        body=body,
        headers={"Content-Type": content_type},
        timeout_seconds=timeout_seconds,
    )


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    return request_json(
        url,
        method="POST",
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        timeout_seconds=timeout_seconds,
    )


def request_json(
    url: str,
    *,
    method: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"local API {method} {url} failed: {exc.code} {detail}") from exc
    return json.loads(raw) if raw else {}


def validate_render_output(path: Path) -> None:
    size = path.stat().st_size if path.exists() else 0
    if not path.exists() or size < 1024:
        raise RuntimeError(f"render output is too small or missing: {path} ({size} bytes)")
    header = path.read_bytes()[:32]
    if path.suffix.lower() != ".mp4" or b"ftyp" not in header[4:16]:
        raise RuntimeError(f"render output is not a valid MP4: {path}")


def download_file(*, url: str, dest: Path, timeout_seconds: int) -> None:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response, open(dest, "wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)


def timeout_seconds() -> int:
    value = os.getenv("LOCAL_RENDER_API_TIMEOUT_SECONDS", "7200").strip()
    return int(value or "7200")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"run_render failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
