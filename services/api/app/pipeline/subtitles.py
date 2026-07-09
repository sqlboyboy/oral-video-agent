from pathlib import Path
from typing import List

from ..models import SubtitleStyle
from ..text_normalization import to_simplified_chinese


_SUBTITLE_BREAK_CHARS = "。！？!?；;"
_LINES_PER_CAPTION = 2


def _sentence_units(paragraph: str) -> List[str]:
    units: List[str] = []
    current = ""
    for char in paragraph:
        current += char
        if char in _SUBTITLE_BREAK_CHARS:
            units.append(current.strip())
            current = ""
    if current.strip():
        units.append(current.strip())
    return units


def _split_unit(unit: str, max_chars: int) -> List[str]:
    chunks: List[str] = []
    current = ""
    for char in unit:
        current += char
        if len(current) >= max_chars:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _group_caption_lines(lines: List[str]) -> List[str]:
    captions: List[str] = []
    for index in range(0, len(lines), _LINES_PER_CAPTION):
        captions.append("\n".join(lines[index:index + _LINES_PER_CAPTION]))
    return captions


def wrap_text(text: str, max_chars: int) -> List[str]:
    max_chars = max(1, int(max_chars or 12))
    captions: List[str] = []
    text = to_simplified_chinese(text)
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    for paragraph in paragraphs:
        for unit in _sentence_units(paragraph):
            captions.extend(_group_caption_lines(_split_unit(unit, max_chars)))
    return captions or [text]


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


def subtitle_time_range_for_text(
    script: str,
    style: SubtitleStyle,
    query: str,
    duration_seconds: float | None = None,
) -> tuple[float, float] | None:
    needle = "".join(query.split())
    if not needle:
        return None
    lines = preview_subtitles(script, style)
    if duration_seconds is None or duration_seconds <= 0:
        seconds_per_line = 1.0
    else:
        seconds_per_line = max(0.8, duration_seconds / max(1, len(lines)))
    for idx, line in enumerate(lines):
        compact_line = "".join(line.split())
        if needle in compact_line or compact_line in needle:
            start = idx * seconds_per_line
            end = (idx + 1) * seconds_per_line
            if duration_seconds is not None:
                end = min(max(end, start + 0.8), duration_seconds)
            return start, end
    return None
