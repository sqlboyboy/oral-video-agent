import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from ..models import RenderOptions


def _ffmpeg_executable() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def is_playable_mp4(path: Path | str | None) -> bool:
    if path is None:
        return False
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return False
    try:
        header = file_path.read_bytes()[:32]
    except OSError:
        return False
    return file_path.suffix.lower() == ".mp4" and b"ftyp" in header[4:16]


def media_duration_seconds(path: Path | str | None) -> float | None:
    if path is None:
        return None
    media_path = Path(path)
    if not media_path.exists():
        return None
    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        return None
    system_ffprobe = shutil.which("ffprobe")
    ffprobe = (
        Path(system_ffprobe)
        if system_ffprobe
        else Path(ffmpeg).with_name("ffprobe.exe" if Path(ffmpeg).suffix.lower() == ".exe" else "ffprobe")
    )
    command = [
        str(ffprobe if ffprobe.exists() else "ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _media_duration_from_ffmpeg(ffmpeg, media_path)
    if completed.returncode != 0:
        return _media_duration_from_ffmpeg(ffmpeg, media_path)
    try:
        duration = float(completed.stdout.strip())
    except ValueError:
        return _media_duration_from_ffmpeg(ffmpeg, media_path)
    return duration if duration > 0 else None


def _media_duration_from_ffmpeg(ffmpeg: str, media_path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [ffmpeg, "-i", str(media_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", completed.stdout)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    duration = hours * 3600 + minutes * 60 + seconds
    return duration if duration > 0 else None


def prepare_video_for_audio_duration(
    source_video: Path,
    voice_audio: Path,
    output_path: Path,
    *,
    cancel_event: threading.Event | None = None,
) -> Path:
    audio_duration = media_duration_seconds(voice_audio)
    video_duration = media_duration_seconds(source_video)
    if audio_duration is None or video_duration is None:
        return source_video

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        return source_video

    tolerance = 0.25
    if video_duration > audio_duration + tolerance:
        command = [
            ffmpeg,
            "-y",
            "-i",
            str(source_video),
            "-t",
            f"{audio_duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(output_path),
        ]
    elif video_duration + tolerance < audio_duration:
        command = [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(source_video),
            "-t",
            f"{audio_duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(output_path),
        ]
    else:
        return source_video

    process = subprocess.Popen(command)
    while process.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            time.sleep(0.5)
            if process.poll() is None:
                process.kill()
            output_path.unlink(missing_ok=True)
            raise RuntimeError("用户已停止生成")
        time.sleep(0.2)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    return output_path


class Renderer:
    def build_ffmpeg_command(
        self,
        source_video: Optional[Path],
        voice_audio: Path,
        subtitle_file: Path,
        options: RenderOptions,
        output_path: Path,
        bgm_audio: Optional[Path] = None,
    ) -> List[str]:
        if source_video is None:
            raise ValueError("source_video is required for real FFmpeg rendering")

        ffmpeg = _ffmpeg_executable()
        if ffmpeg is None:
            raise ValueError("ffmpeg is required for real FFmpeg rendering")

        command = [ffmpeg, "-y", "-i", str(source_video), "-i", str(voice_audio)]
        filter_parts = []
        audio_inputs = "[aout]"

        if bgm_audio is not None:
            command.extend(["-i", str(bgm_audio)])
            filter_parts.append(f"[2:a]volume={options.bgm_volume},aloop=loop=-1:size=2e+09[bgm]")
            filter_parts.append("[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        else:
            filter_parts.append("[1:a]anull[aout]")

        subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(f"[0:v]subtitles='{subtitle_path}'[vout]")

        command.extend([
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-map",
            audio_inputs,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(output_path),
        ])
        return command

    def render(
        self,
        task_id: str,
        script: str,
        options: RenderOptions,
        output_path: Path,
        source_video: Optional[Path] = None,
        voice_audio: Optional[Path] = None,
        subtitle_file: Optional[Path] = None,
        bgm_audio: Optional[Path] = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if source_video and voice_audio and subtitle_file and _ffmpeg_executable():
            command = self.build_ffmpeg_command(source_video, voice_audio, subtitle_file, options, output_path, bgm_audio)
            process = subprocess.Popen(command)
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    time.sleep(0.5)
                    if process.poll() is None:
                        process.kill()
                    output_path.unlink(missing_ok=True)
                    raise RuntimeError("用户已停止生成")
                time.sleep(0.2)
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
            return output_path

        placeholder_path = output_path if output_path.suffix.lower() == ".txt" else output_path.with_suffix(output_path.suffix + ".txt")
        placeholder_path.write_text(
            "This placeholder represents the rendered MP4.\n"
            "Real FFmpeg rendering is skipped until source video, generated voice audio, subtitles, and ffmpeg are available.\n"
            f"task_id={task_id}\n"
            f"voice_id={options.voice_id}\n"
            f"bgm_id={options.bgm_id}\n"
            f"bgm_volume={options.bgm_volume}\n"
            f"script={script}\n",
            encoding="utf-8",
        )
        return placeholder_path
