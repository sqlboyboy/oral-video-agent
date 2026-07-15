import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from ..models import RenderOptions


FALLBACK_OUTPUT_WIDTH = 1080
FALLBACK_OUTPUT_HEIGHT = 1920
PIP_MEDIA_ASPECT_RATIO = 16 / 9
PIP_MARGIN_X = 24
PIP_MARGIN_Y = 24


def _ffmpeg_preset() -> str:
    return os.getenv("FFMPEG_X264_PRESET", "veryfast").strip() or "veryfast"


def _ffmpeg_crf() -> str:
    return os.getenv("FFMPEG_X264_CRF", "18").strip() or "18"


def _output_fps() -> str:
    value = os.getenv("OUTPUT_FPS", "").strip()
    if not value:
        return ""
    try:
        fps = float(value)
    except ValueError:
        return ""
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


def media_video_dimensions(path: Path | str | None) -> tuple[int, int] | None:
    if path is None:
        return None
    media_path = Path(path)
    if not media_path.exists():
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
                    str(media_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            output = getattr(completed, "stdout", "") or ""
            match = re.fullmatch(r"\s*(\d+)x(\d+)\s*", output)
            if completed.returncode == 0 and match:
                width, height = int(match.group(1)), int(match.group(2))
                if width > 0 and height > 0:
                    return width, height
        except (OSError, subprocess.TimeoutExpired):
            pass

    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(media_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
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


def _normalized_frame_rate(value: str) -> str | None:
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


def media_video_frame_rate(path: Path | str | None) -> str | None:
    if path is None:
        return None
    media_path = Path(path)
    if not media_path.exists():
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
                    str(media_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if completed.returncode == 0:
                normalized = _normalized_frame_rate(getattr(completed, "stdout", "") or "")
                if normalized:
                    return normalized
        except (OSError, subprocess.TimeoutExpired):
            pass

    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(media_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = getattr(completed, "stdout", "") or ""
    for line in output.splitlines():
        if "Video:" not in line:
            continue
        match = re.search(r"\b(\d+(?:\.\d+)?)\s+fps\b", line)
        if match:
            return _normalized_frame_rate(match.group(1))
    return None


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
    # libass parses SRT files on its 384 x 288 logical canvas and then scales
    # that canvas to the output video. Product presets are authored against a
    # 1080 x 1920 portrait canvas, so vertical sizes must be converted first.
    scale = 288 / 1920
    font_size = max(1.0, style.font_size * scale)
    outline_width = max(0.0, style.outline_width * scale)
    margin_v = max(0, int(style.margin_v * scale + 0.5))

    def ass_number(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    return ",".join(
        [
            f"FontName={style.font_family}",
            f"FontSize={ass_number(font_size)}",
            "Bold=1",
            "BorderStyle=1",
            f"Outline={ass_number(outline_width)}",
            "Shadow=0",
            f"PrimaryColour={_ass_color(style.color, '#FFE600')}",
            f"OutlineColour={_ass_color(style.outline_color, '#000000')}",
            f"Alignment={_subtitle_alignment(style.position)}",
            f"MarginV={margin_v}",
        ]
    )


def _render_option_supplied(options: RenderOptions, field_name: str) -> bool:
    fields_set = getattr(options, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(options, "__fields_set__", set())
    return field_name in fields_set


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _canvas_dimensions(source_video: Path) -> tuple[int, int]:
    dimensions = media_video_dimensions(source_video)
    if dimensions is None:
        return FALLBACK_OUTPUT_WIDTH, FALLBACK_OUTPUT_HEIGHT
    width, height = dimensions
    # libx264 with yuv420p requires even dimensions. Normal camera and digital
    # human videos are already even, so this does not resize them in practice.
    return max(2, width - width % 2), max(2, height - height % 2)


def _portrait_main_video_filter(canvas_width: int, canvas_height: int) -> str:
    return (
        f"[0:v]scale={canvas_width}:{canvas_height}:flags=lanczos,"
        "setsar=1,setpts=PTS-STARTPTS[mainv]"
    )


def _pip_layout(
    options: RenderOptions,
    canvas_width: int = FALLBACK_OUTPUT_WIDTH,
    canvas_height: int = FALLBACK_OUTPUT_HEIGHT,
) -> tuple[int, int, int, int]:
    position = (options.pip_position or "top_right").strip().lower()
    if position == "fullscreen":
        return canvas_width, canvas_height, 0, 0

    width_norm = (
        options.pip_width
        if _render_option_supplied(options, "pip_width")
        else options.pip_scale
    )
    width_norm = _clamp_float(width_norm, 0.05, 0.95)
    if _render_option_supplied(options, "pip_height") and options.pip_height is not None:
        height_norm = _clamp_float(options.pip_height, 0.03, 0.95)
    else:
        height_norm = width_norm * canvas_width / canvas_height / PIP_MEDIA_ASPECT_RATIO
        height_norm = _clamp_float(height_norm, 0.03, 0.95)

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
        "custom": (options.pip_x * canvas_width, options.pip_y * canvas_height),
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
            _ffmpeg_preset(),
            "-crf",
            _ffmpeg_crf(),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
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
            _ffmpeg_preset(),
            "-crf",
            _ffmpeg_crf(),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
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
    def build_cover_first_frame_command(
        self,
        source_video: Path,
        cover_image: Path,
        output_path: Path,
    ) -> List[str]:
        ffmpeg = _ffmpeg_executable()
        if ffmpeg is None:
            raise ValueError("ffmpeg is required to apply the video cover")

        canvas_width, canvas_height = _canvas_dimensions(source_video)
        filter_complex = (
            "[0:v]setpts=PTS-STARTPTS[basev];"
            f"[1:v]scale={canvas_width}:{canvas_height}:force_original_aspect_ratio=increase,"
            f"crop={canvas_width}:{canvas_height},setsar=1[coverv];"
            "[basev][coverv]overlay=0:0:enable='eq(n\\,0)':eof_action=pass[vout]"
        )
        return [
            ffmpeg,
            "-y",
            "-i",
            str(source_video),
            "-loop",
            "1",
            "-i",
            str(cover_image),
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "0:a?",
            "-map_metadata",
            "0",
            "-c:v",
            "libx264",
            "-preset",
            _ffmpeg_preset(),
            "-crf",
            _ffmpeg_crf(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    def apply_cover_first_frame(
        self,
        source_video: Path,
        cover_image: Path,
        output_path: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        command = self.build_cover_first_frame_command(
            source_video,
            cover_image,
            output_path,
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
            output_path.unlink(missing_ok=True)
            raise subprocess.CalledProcessError(process.returncode, command)
        return output_path

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

        voice_filter = f"dynaudnorm=f=150:g=15:p=0.9,volume={options.voice_volume}"
        bgm_filter = (
            f"dynaudnorm=f=150:g=15:p=0.9,volume={options.bgm_volume},"
            "aloop=loop=-1:size=2147483647"
        )
        if bgm_audio is not None:
            command.extend(["-i", str(bgm_audio)])
            pip_input_index = 3
            filter_parts.append(f"[1:a]{voice_filter}[voice]")
            filter_parts.append(f"[2:a]{bgm_filter}[bgm]")
            filter_parts.append("[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]")
        else:
            filter_parts.append(f"[1:a]{voice_filter}[aout]")

        has_pip_filter = options.pip_enabled and pip_asset is not None
        has_subtitle_filter = options.subtitle_enabled and subtitle_file is not None
        has_video_filter = has_pip_filter or has_subtitle_filter
        video_output = "0:v:0"
        if has_video_filter:
            canvas_width, canvas_height = _canvas_dimensions(source_video)
            video_input = "[mainv]"
            filter_parts.append(_portrait_main_video_filter(canvas_width, canvas_height))
        if has_pip_filter:
            if pip_asset.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                command.extend(["-loop", "1", "-i", str(pip_asset)])
            else:
                command.extend(["-stream_loop", "-1", "-i", str(pip_asset)])
            pip_width, pip_height, pip_x, pip_y = _pip_layout(
                options,
                canvas_width,
                canvas_height,
            )
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

        if has_subtitle_filter:
            subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
            force_style = _subtitle_force_style(options)
            filter_parts.append(f"{video_input}subtitles='{subtitle_path}':force_style='{force_style}'[vout]")
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
            audio_inputs,
        ])
        if has_video_filter:
            command.extend([
                "-c:v",
                "libx264",
                "-preset",
                _ffmpeg_preset(),
                "-crf",
                _ffmpeg_crf(),
                "-pix_fmt",
                "yuv420p",
            ])
            fps = _output_fps() or media_video_frame_rate(source_video)
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

        voice_filter = f"dynaudnorm=f=150:g=15:p=0.9,volume={options.voice_volume}"
        bgm_filter = (
            f"dynaudnorm=f=150:g=15:p=0.9,volume={options.bgm_volume},"
            "aloop=loop=-1:size=2147483647"
        )
        if bgm_audio is not None:
            command.extend(["-i", str(bgm_audio)])
            pip_input_index = 2
            filter_parts.append(f"[0:a]{voice_filter}[voice]")
            filter_parts.append(f"[1:a]{bgm_filter}[bgm]")
            filter_parts.append("[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]")
        else:
            filter_parts.append(f"[0:a]{voice_filter}[aout]")

        has_pip_filter = options.pip_enabled and pip_asset is not None
        has_subtitle_filter = options.subtitle_enabled and subtitle_file is not None
        has_video_filter = has_pip_filter or has_subtitle_filter
        video_output = "0:v:0"
        if has_video_filter:
            canvas_width, canvas_height = _canvas_dimensions(source_video)
            video_input = "[mainv]"
            filter_parts.append(_portrait_main_video_filter(canvas_width, canvas_height))
        if has_pip_filter:
            if pip_asset.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                command.extend(["-loop", "1", "-i", str(pip_asset)])
            else:
                command.extend(["-stream_loop", "-1", "-i", str(pip_asset)])
            pip_width, pip_height, pip_x, pip_y = _pip_layout(
                options,
                canvas_width,
                canvas_height,
            )
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

        if has_subtitle_filter:
            subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
            force_style = _subtitle_force_style(options)
            filter_parts.append(f"{video_input}subtitles='{subtitle_path}':force_style='{force_style}'[vout]")
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
            audio_inputs,
        ])
        if has_video_filter:
            command.extend([
                "-c:v",
                "libx264",
                "-preset",
                _ffmpeg_preset(),
                "-crf",
                _ffmpeg_crf(),
                "-pix_fmt",
                "yuv420p",
            ])
            fps = _output_fps() or media_video_frame_rate(source_video)
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
            f"voice_volume={options.voice_volume}\n"
            f"bgm_id={options.bgm_id}\n"
            f"bgm_volume={options.bgm_volume}\n"
            f"script={script}\n",
            encoding="utf-8",
        )
        return placeholder_path
