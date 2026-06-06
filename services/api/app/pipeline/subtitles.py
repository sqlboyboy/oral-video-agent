from pathlib import Path
from typing import List

from ..models import SubtitleStyle


def wrap_text(text: str, max_chars: int) -> List[str]:
    lines: List[str] = []
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    for paragraph in paragraphs:
        current = ""
        for char in paragraph:
            current += char
            if len(current) >= max_chars or char in "。！？!?；;":
                lines.append(current.strip())
                current = ""
        if current.strip():
            lines.append(current.strip())
    return lines or [text]


def preview_subtitles(script: str, style: SubtitleStyle) -> List[str]:
    return wrap_text(script, style.max_chars_per_line)


def _format_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000
    minutes = milliseconds // 60_000
    milliseconds %= 60_000
    secs = milliseconds // 1000
    millis = milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(
    script: str,
    style: SubtitleStyle,
    output_path: Path,
    duration_seconds: float | None = None,
) -> Path:
    lines = preview_subtitles(script, style)
    blocks = []
    if duration_seconds is None or duration_seconds <= 0:
        seconds_per_line = 1.0
    else:
        seconds_per_line = max(0.8, duration_seconds / max(1, len(lines)))
    for idx, line in enumerate(lines, start=1):
        start = (idx - 1) * seconds_per_line
        end = idx * seconds_per_line
        if duration_seconds is not None and idx == len(lines):
            end = max(end, duration_seconds)
        start_ts = _format_timestamp(start)
        end_ts = _format_timestamp(end)
        blocks.append(
            f"{idx}\n"
            f"{start_ts} --> {end_ts}\n"
            f"{line}\n"
        )
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return output_path
