import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from ..models import RenderOptions


OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
PIP_MEDIA_ASPECT_RATIO = 16 / 9
PIP_MARGIN_X = 24
PIP_MARGIN_Y = 24


def _ffmpeg_preset() -> str:
    return os.getenv("FFMPEG_X264_PRESET", "veryfast").strip() or "veryfast"


def _ffmpeg_crf() -> str:
    return os.getenv("FFMPEG_X264_CRF", "24").strip() or "24"


def _output_fps() -> str:
    value = os.getenv("OUTPUT_FPS", "25").strip()
    try:
        fps = float(value)
    except ValueError:
        return "25"
    if fps <= 0:
        return ""
    return str(int(fps)) if fps.is_integer() else f"{fps:g}"


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


def _ass_color(hex_color: str, fallback: str) -> str:
    value = (hex_color or fallback).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6 or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = fallback.strip().lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"&H00{blue:02X}{green:02X}{red:02X}&"


def _subtitle_alignment(position: str) -> int:
    normalized = (position or "bottom").strip().lower()
    if normalized == "top":
        return 8
    if normalized in {"middle", "center", "centre"}:
        return 5
    return 2


def _subtitle_force_style(options: RenderOptions) -> str:
    style = options.subtitle_style
    return ",".join(
        [
            f"FontName={style.font_family}",
            f"FontSize={style.font_size}",
            "Bold=1",
            "BorderStyle=1",
            f"Outline={style.outline_width}",
            "Shadow=0",
            f"PrimaryColour={_ass_color(style.color, '#FFE600')}",
            f"OutlineColour={_ass_color(style.outline_color, '#000000')}",
            f"Alignment={_subtitle_alignment(style.position)}",
            f"MarginV={style.margin_v}",
        ]
    )


def _render_option_supplied(options: RenderOptions, field_name: str) -> bool:
    fields_set = getattr(options, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(options, "__fields_set__", set())
    return field_name in fields_set


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _portrait_main_video_filter() -> str:
    return (
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},setsar=1,setpts=PTS-STARTPTS[mainv]"
    )


def _pip_layout(options: RenderOptions) -> tuple[int, int, int, int]:
    position = (options.pip_position or "top_right").strip().lower()
    if position == "fullscreen":
        return OUTPUT_WIDTH, OUTPUT_HEIGHT, 0, 0

    width_norm = (
        options.pip_width
        if _render_option_supplied(options, "pip_width")
        else options.pip_scale
    )
    width_norm = _clamp_float(width_norm, 0.05, 0.95)
    if _render_option_supplied(options, "pip_height") and options.pip_height is not None:
        height_norm = _clamp_float(options.pip_height, 0.03, 0.95)
    else:
        height_norm = width_norm * OUTPUT_WIDTH / OUTPUT_HEIGHT / PIP_MEDIA_ASPECT_RATIO
        height_norm = _clamp_float(height_norm, 0.03, 0.95)

    width = max(54, min(OUTPUT_WIDTH, int(round(OUTPUT_WIDTH * width_norm))))
    height = max(54, min(OUTPUT_HEIGHT, int(round(OUTPUT_HEIGHT * height_norm))))
    max_x = max(0, OUTPUT_WIDTH - width)
    max_y = max(0, OUTPUT_HEIGHT - height)

    positions = {
        "top_left": (PIP_MARGIN_X, PIP_MARGIN_Y),
        "top_right": (max_x - PIP_MARGIN_X, PIP_MARGIN_Y),
        "bottom_left": (PIP_MARGIN_X, max_y - PIP_MARGIN_Y),
        "bottom_right": (max_x - PIP_MARGIN_X, max_y - PIP_MARGIN_Y),
        "center": (max_x / 2, max_y / 2),
        "custom": (options.pip_x * OUTPUT_WIDTH, options.pip_y * OUTPUT_HEIGHT),
    }
    raw_x, raw_y = positions.get(position, positions["top_right"])
    x = int(round(max(0, min(max_x, raw_x))))
    y = int(round(max(0, min(max_y, raw_y))))
    return width, height, x, y


def _pip_enable_expression(options: RenderOptions) -> str | None:
    if not options.pip_enabled:
        return None
    mode = (options.pip_timing_mode or "full").strip().lower()
    if mode not in {"time", "sentence"}:
        return None
    start = options.pip_start_seconds
    end = options.pip_end_seconds
    if start is None:
        return None
    start = max(0.0, float(start))
    if end is None or end <= start:
        return f"gte(t\\,{start:.3f})"
    return f"between(t\\,{start:.3f}\\,{float(end):.3f})"


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
        subtitle_file: Optional[Path],
        options: RenderOptions,
        output_path: Path,
        bgm_audio: Optional[Path] = None,
        pip_asset: Optional[Path] = None,
    ) -> List[str]:
        if source_video is None:
            raise ValueError("source_video is required for real FFmpeg rendering")

        ffmpeg = _ffmpeg_executable()
        if ffmpeg is None:
            raise ValueError("ffmpeg is required for real FFmpeg rendering")

        command = [ffmpeg, "-y", "-i", str(source_video), "-i", str(voice_audio)]
        filter_parts = []
        audio_inputs = "[aout]"
        pip_input_index = 2

        if bgm_audio is not None:
            command.extend(["-i", str(bgm_audio)])
            pip_input_index = 3
            filter_parts.append(f"[2:a]volume={options.bgm_volume},aloop=loop=-1:size=2147483647[bgm]")
            filter_parts.append("[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]")
        else:
            filter_parts.append("[1:a]anull[aout]")

        video_input = "[mainv]"
        filter_parts.append(_portrait_main_video_filter())
        if options.pip_enabled and pip_asset is not None:
            if pip_asset.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                command.extend(["-loop", "1", "-i", str(pip_asset)])
            else:
                command.extend(["-stream_loop", "-1", "-i", str(pip_asset)])
            pip_width, pip_height, pip_x, pip_y = _pip_layout(options)
            filter_parts.append(
                f"[{pip_input_index}:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=increase,"
                f"crop={pip_width}:{pip_height},setsar=1,setpts=PTS-STARTPTS[pip]"
            )
            enable_expr = _pip_enable_expression(options)
            enable_part = f":enable='{enable_expr}'" if enable_expr else ""
            filter_parts.append(
                f"{video_input}[pip]overlay={pip_x}:{pip_y}{enable_part}:eof_action=pass[basev]"
            )
            video_input = "[basev]"

        if options.subtitle_enabled and subtitle_file is not None:
            subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
            force_style = _subtitle_force_style(options)
            filter_parts.append(f"{video_input}subtitles='{subtitle_path}':force_style='{force_style}'[vout]")
        else:
            filter_parts.append(f"{video_input}null[vout]")

        command.extend([
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-map",
            audio_inputs,
            "-c:v",
            "libx264",
            "-preset",
            _ffmpeg_preset(),
            "-crf",
            _ffmpeg_crf(),
        ])
        fps = _output_fps()
        if fps:
            command.extend(["-r", fps])
        command.extend([
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ])
        return command

    def build_postprocess_command(
        self,
        source_video: Path,
        subtitle_file: Optional[Path],
        options: RenderOptions,
        output_path: Path,
        bgm_audio: Optional[Path] = None,
        pip_asset: Optional[Path] = None,
    ) -> List[str]:
        ffmpeg = _ffmpeg_executable()
        if ffmpeg is None:
            raise ValueError("ffmpeg is required for real FFmpeg rendering")

        command = [ffmpeg, "-y", "-i", str(source_video)]
        filter_parts = []
        audio_inputs = "[aout]"
        pip_input_index = 1

        if bgm_audio is not None:
            command.extend(["-i", str(bgm_audio)])
            pip_input_index = 2
            filter_parts.append("[0:a]anull[srca]")
            filter_parts.append(f"[1:a]volume={options.bgm_volume},aloop=loop=-1:size=2147483647[bgm]")
            filter_parts.append("[srca][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]")
        else:
            filter_parts.append("[0:a]anull[aout]")

        video_input = "[mainv]"
        filter_parts.append(_portrait_main_video_filter())
        if options.pip_enabled and pip_asset is not None:
            if pip_asset.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                command.extend(["-loop", "1", "-i", str(pip_asset)])
            else:
                command.extend(["-stream_loop", "-1", "-i", str(pip_asset)])
            pip_width, pip_height, pip_x, pip_y = _pip_layout(options)
            filter_parts.append(
                f"[{pip_input_index}:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=increase,"
                f"crop={pip_width}:{pip_height},setsar=1,setpts=PTS-STARTPTS[pip]"
            )
            enable_expr = _pip_enable_expression(options)
            enable_part = f":enable='{enable_expr}'" if enable_expr else ""
            filter_parts.append(
                f"{video_input}[pip]overlay={pip_x}:{pip_y}{enable_part}:eof_action=pass[basev]"
            )
            video_input = "[basev]"

        if options.subtitle_enabled and subtitle_file is not None:
            subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
            force_style = _subtitle_force_style(options)
            filter_parts.append(f"{video_input}subtitles='{subtitle_path}':force_style='{force_style}'[vout]")
        else:
            filter_parts.append(f"{video_input}null[vout]")

        command.extend([
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-map",
            audio_inputs,
            "-c:v",
            "libx264",
            "-preset",
            _ffmpeg_preset(),
            "-crf",
            _ffmpeg_crf(),
        ])
        fps = _output_fps()
        if fps:
            command.extend(["-r", fps])
        command.extend([
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ])
        return command

    def postprocess(
        self,
        source_video: Path,
        subtitle_file: Optional[Path],
        options: RenderOptions,
        output_path: Path,
        bgm_audio: Optional[Path] = None,
        pip_asset: Optional[Path] = None,
    ) -> Path:
        command = self.build_postprocess_command(
            source_video,
            subtitle_file,
            options,
            output_path,
            bgm_audio,
            pip_asset,
        )
        process = subprocess.Popen(command)
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)
        return output_path

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
        pip_asset: Optional[Path] = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        has_subtitle_input = subtitle_file is not None or not options.subtitle_enabled
        if source_video and voice_audio and has_subtitle_input and _ffmpeg_executable():
            command = self.build_ffmpeg_command(
                source_video,
                voice_audio,
                subtitle_file,
                options,
                output_path,
                bgm_audio,
                pip_asset,
            )
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
