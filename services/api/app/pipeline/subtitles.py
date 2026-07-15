from pathlib import Path
import re
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


def _format_ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours = centiseconds // 360_000
    centiseconds %= 360_000
    minutes = centiseconds // 6_000
    centiseconds %= 6_000
    secs = centiseconds // 100
    cents = centiseconds % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def _ass_color(value: str, fallback: str) -> str:
    normalized = (value or fallback).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", normalized):
        normalized = fallback.strip().lstrip("#")
    red, green, blue = normalized[0:2], normalized[2:4], normalized[4:6]
    return f"&H00{blue.upper()}{green.upper()}{red.upper()}"


def _escape_ass_text(value: str) -> str:
    return (
        value.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _ass_caption_text(caption: str, style: SubtitleStyle) -> str:
    lines = [_escape_ass_text(line) for line in caption.splitlines()]
    keyword = (style.keyword_color or "").strip()
    if len(lines) > 1 and re.fullmatch(r"#[0-9A-Fa-f]{6}", keyword):
        lines[-1] = f"{{\\c{_ass_color(keyword, style.color)}&}}{lines[-1]}"
    text = r"\N".join(lines)
    if (style.position or "").strip().lower() == "custom":
        x = round(max(0.0, min(1.0, style.position_x)) * 1080)
        y = round(max(0.0, min(1.0, style.position_y)) * 1920)
        text = f"{{\\an8\\pos({x},{y})}}{text}"
    return text


def _apply_keyword_color(caption: str, style: SubtitleStyle) -> str:
    color = (style.keyword_color or "").strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        return caption
    lines = caption.splitlines()
    if len(lines) < 2:
        return caption
    lines[-1] = f'<font color="{color.upper()}">{lines[-1]}</font>'
    return "\n".join(lines)


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
        rendered_line = _apply_keyword_color(line, style)
        blocks.append(
            f"{idx}\n"
            f"{start_ts} --> {end_ts}\n"
            f"{rendered_line}\n"
        )
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return output_path


def generate_ass(
    script: str,
    style: SubtitleStyle,
    output_path: Path,
    duration_seconds: float | None = None,
) -> Path:
    captions = preview_subtitles(script, style)
    if duration_seconds is None or duration_seconds <= 0:
        seconds_per_caption = 1.0
    else:
        seconds_per_caption = max(0.8, duration_seconds / max(1, len(captions)))

    position = (style.position or "bottom").strip().lower()
    alignment = (
        8
        if position in {"top", "custom"}
        else 5
        if position in {"middle", "center", "centre"}
        else 2
    )
    margin_v = 0 if position == "custom" else max(0, style.margin_v)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font_family},{style.font_size},"
        f"{_ass_color(style.color, '#FFFFFF')},"
        f"{_ass_color(style.keyword_color or style.color, style.color)},"
        f"{_ass_color(style.outline_color, '#111111')},"
        "&H00000000,-1,0,0,0,100,100,0,0,1,"
        f"{style.outline_width},0,{alignment},0,0,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    dialogues: list[str] = []
    for index, caption in enumerate(captions):
        start = index * seconds_per_caption
        end = (index + 1) * seconds_per_caption
        if duration_seconds is not None and index == len(captions) - 1:
            end = max(end, duration_seconds)
        dialogues.append(
            "Dialogue: 0,"
            f"{_format_ass_timestamp(start)},{_format_ass_timestamp(end)},"
            f"Default,,0,0,0,,{_ass_caption_text(caption, style)}"
        )
    output_path.write_text(header + "\n".join(dialogues) + "\n", encoding="utf-8")
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
