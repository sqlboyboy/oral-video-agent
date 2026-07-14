from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable


URL_RE = re.compile(
    r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
    re.IGNORECASE,
)
DOUYIN_URL_RE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9-]+\.)?douyin\.com/"
    r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
    re.IGNORECASE,
)
TRAILING_URL_CHARS = ".,;:!?，。；：！？、)]}）】》\"'"

_BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Mobile Safari/537.36"
)
_BROWSER_ARGS = [
    "--disable-background-networking",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--no-sandbox",
]

ProgressCallback = Callable[[int, str], None]
_PIPELINE_LOCK = threading.Lock()
_MODEL = None
_MODEL_NAME = ""


class DouyinTranscriptionError(RuntimeError):
    pass


def _clean_url_candidate(url: str) -> str:
    return url.strip().rstrip(TRAILING_URL_CHARS)


def _normalize_share_url(url: str) -> str:
    value = _clean_url_candidate(url)
    if value and not re.match(r"^https?://", value, flags=re.IGNORECASE):
        return f"https://{value}"
    return value


def _is_douyin_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (
        host == "douyin.com" or host.endswith(".douyin.com")
    )


def extract_douyin_share_url(text: str) -> str | None:
    for pattern in (DOUYIN_URL_RE, URL_RE):
        for match in pattern.finditer(text or ""):
            url = _normalize_share_url(match.group(0))
            if url and _is_douyin_url(url):
                return url
    return None


def _select_video_url(data: dict) -> str | None:
    aweme = data.get("aweme_detail") or {}
    if not aweme and isinstance(data.get("aweme_list"), list) and data["aweme_list"]:
        aweme = data["aweme_list"][0] or {}
    video = aweme.get("video") or {}
    for key in ("play_addr", "download_addr"):
        urls = (video.get(key) or {}).get("url_list") or []
        trusted = [
            str(url)
            for url in urls
            if "douyinvod.com" in str(url) or "amemv.com" in str(url)
        ]
        candidates = trusted or [str(url) for url in urls]
        for candidate in candidates:
            if urllib.parse.urlparse(candidate).scheme in {"http", "https"}:
                return candidate
    return None


def _extract_video_url_via_browser(
    share_url: str,
    *,
    chromium_executable: str,
    timeout_seconds: int,
) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise DouyinTranscriptionError("服务器缺少抖音解析浏览器组件") from exc

    detail_bodies: list[bytes] = []
    timeout_ms = max(10, timeout_seconds) * 1000
    try:
        with sync_playwright() as playwright:
            launch_options = {
                "headless": True,
                "args": _BROWSER_ARGS,
            }
            if chromium_executable:
                executable = Path(chromium_executable)
                if not executable.exists():
                    raise DouyinTranscriptionError(
                        f"服务器 Chromium 不存在：{chromium_executable}"
                    )
                launch_options["executable_path"] = str(executable)
            browser = playwright.chromium.launch(**launch_options)
            try:
                context = browser.new_context(
                    user_agent=_BROWSER_UA,
                    locale="zh-CN",
                    viewport={"width": 430, "height": 932},
                )
                page = context.new_page()

                def on_response(response) -> None:
                    if "aweme/detail" not in response.url or detail_bodies:
                        return
                    try:
                        detail_bodies.append(response.body())
                    except Exception:
                        return

                page.on("response", on_response)
                try:
                    page.goto(
                        share_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                except Exception:
                    pass
                page.wait_for_timeout(8000)
            finally:
                browser.close()
    except DouyinTranscriptionError:
        raise
    except Exception as exc:
        raise DouyinTranscriptionError(f"抖音分享页解析失败：{exc}") from exc

    for body in detail_bodies:
        try:
            video_url = _select_video_url(json.loads(body))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if video_url:
            return video_url
    raise DouyinTranscriptionError(
        "没有从抖音分享页解析到视频，链接可能已失效、需要登录或页面结构已变化"
    )


def _download_video(video_url: str, destination: Path, *, max_bytes: int) -> None:
    request = urllib.request.Request(
        video_url,
        headers={
            "User-Agent": _BROWSER_UA,
            "Referer": "https://www.douyin.com/",
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open(
            "wb"
        ) as output:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise DouyinTranscriptionError("抖音视频超过服务器允许的 500MB 上限")
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise DouyinTranscriptionError("抖音视频超过服务器允许的 500MB 上限")
                output.write(chunk)
    except DouyinTranscriptionError:
        raise
    except Exception as exc:
        raise DouyinTranscriptionError(f"抖音视频下载失败：{exc}") from exc
    if downloaded == 0:
        raise DouyinTranscriptionError("抖音视频下载失败：文件为空")


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise DouyinTranscriptionError("服务器缺少 FFmpeg 音频处理组件")
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DouyinTranscriptionError("视频音频提取超时") from exc
    if result.returncode != 0 or not audio_path.exists() or audio_path.stat().st_size == 0:
        detail = (result.stderr or "未知错误").strip()[-400:]
        raise DouyinTranscriptionError(f"视频音频提取失败：{detail}")


def _post_process_transcript(text: str) -> str:
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
    return "，".join(cleaned)


def _get_whisper_model(*, model_name: str, model_cache_dir: Path):
    global _MODEL, _MODEL_NAME
    if _MODEL is not None and _MODEL_NAME == model_name:
        return _MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise DouyinTranscriptionError("服务器缺少语音识别组件") from exc

    model_cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        _MODEL = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=max(1, min(os.cpu_count() or 1, 4)),
            num_workers=1,
            download_root=str(model_cache_dir),
        )
    except Exception as exc:
        raise DouyinTranscriptionError(f"语音识别模型加载失败：{exc}") from exc
    _MODEL_NAME = model_name
    return _MODEL


def _transcribe_audio(
    audio_path: Path,
    *,
    model_name: str,
    model_cache_dir: Path,
) -> str:
    model = _get_whisper_model(
        model_name=model_name,
        model_cache_dir=model_cache_dir,
    )
    try:
        segments, _ = model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        transcript = _post_process_transcript(
            "".join(segment.text for segment in segments).strip()
        )
    except Exception as exc:
        raise DouyinTranscriptionError(f"视频口播识别失败：{exc}") from exc
    if not transcript:
        raise DouyinTranscriptionError("没有在视频中识别到清晰口播内容")
    return transcript


def transcribe_douyin_share(
    share_text: str,
    *,
    work_dir: Path,
    model_name: str,
    model_cache_dir: Path,
    chromium_executable: str,
    browser_timeout_seconds: int,
    max_video_bytes: int,
    on_progress: ProgressCallback,
) -> str:
    share_url = extract_douyin_share_url(share_text)
    if not share_url:
        raise DouyinTranscriptionError("没有识别到有效的抖音分享链接")

    work_dir.mkdir(parents=True, exist_ok=True)
    video_path = work_dir / "source.mp4"
    audio_path = work_dir / "audio.wav"
    try:
        on_progress(2, "任务已进入服务器处理队列")
        with _PIPELINE_LOCK:
            on_progress(8, "正在解析抖音分享链接")
            video_url = _extract_video_url_via_browser(
                share_url,
                chromium_executable=chromium_executable,
                timeout_seconds=browser_timeout_seconds,
            )
            on_progress(25, "链接解析成功，正在下载视频")
            _download_video(video_url, video_path, max_bytes=max_video_bytes)
            on_progress(45, "视频下载完成，正在提取音频")
            _extract_audio(video_path, audio_path)
            on_progress(58, "音频提取完成，正在加载语音识别模型")
            model = _get_whisper_model(
                model_name=model_name,
                model_cache_dir=model_cache_dir,
            )
            del model
            on_progress(68, "正在识别视频中的口播文案")
            transcript = _transcribe_audio(
                audio_path,
                model_name=model_name,
                model_cache_dir=model_cache_dir,
            )
            on_progress(96, "口播识别完成，正在整理文案")
            return transcript
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
