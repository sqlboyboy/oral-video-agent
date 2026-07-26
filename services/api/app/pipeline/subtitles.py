from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Sequence
import unicodedata

from ..models import SubtitleStyle
from ..text_normalization import to_simplified_chinese
from .speech_timing import TimedSpeechToken


_SOFT_BREAK_WORDS = (
    "但是",
    "所以",
    "如果",
    "然后",
    "另外",
    "最后",
    "同时",
    "而且",
    "因为",
    "其实",
    "记住",
    "一定",
    "不要",
    "可以",
    "第一",
    "第二",
    "第三",
    "第四",
    "第五",
)


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def _is_punctuation(char: str) -> bool:
    return bool(char) and unicodedata.category(char).startswith("P")


def clean_subtitle_text(text: str) -> str:
    """Remove display punctuation while preserving every spoken character."""

    simplified = to_simplified_chinese(text or "")
    cleaned = "".join(char for char in simplified if not _is_punctuation(char))
    return re.sub(r"\s+", " ", cleaned).strip()


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", clean_subtitle_text(text))


def subtitle_sentences(text: str) -> List[str]:
    """Split on spoken phrase boundaries and omit punctuation from display."""

    simplified = to_simplified_chinese(text or "")
    units: List[str] = []
    current: list[str] = []
    for char in simplified:
        if char in "\r\n" or _is_punctuation(char):
            unit = clean_subtitle_text("".join(current))
            if unit:
                units.append(unit)
            current = []
            continue
        current.append(char)
    tail = clean_subtitle_text("".join(current))
    if tail:
        units.append(tail)
    if units:
        return units
    cleaned = clean_subtitle_text(simplified)
    return [cleaned] if cleaned else []


def _soft_break_positions(text: str) -> set[int]:
    positions = {index + 1 for index, char in enumerate(text) if char.isspace()}
    for word in _SOFT_BREAK_WORDS:
        start = 0
        while True:
            index = text.find(word, start)
            if index < 0:
                break
            if index > 0:
                positions.add(index)
            start = index + len(word)
    return positions


def _best_break(text: str, low: int, high: int, preferred: int) -> int:
    low = max(1, low)
    high = min(len(text) - 1, high)
    if low > high:
        return min(max(1, preferred), max(1, len(text) - 1))
    candidates = [
        position
        for position in _soft_break_positions(text)
        if low <= position <= high
    ]
    if candidates:
        return min(candidates, key=lambda position: abs(position - preferred))
    return min(max(preferred, low), high)


def _split_long_unit(unit: str, caption_capacity: int) -> List[str]:
    chunks: List[str] = []
    remaining = unit.strip()
    while len(remaining) > caption_capacity:
        cut = _best_break(
            remaining,
            max(1, int(caption_capacity * 0.55)),
            caption_capacity,
            caption_capacity,
        )
        chunk = remaining[:cut].strip()
        if not chunk:
            chunk = remaining[:caption_capacity]
            cut = caption_capacity
        chunks.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _balanced_caption_lines(text: str, line_capacity: int) -> List[str]:
    text = text.strip()
    if len(text) <= line_capacity:
        return [text]
    cut = _best_break(
        text,
        max(1, len(text) - line_capacity),
        min(line_capacity, len(text) - 1),
        len(text) // 2,
    )
    first = text[:cut].strip()
    second = text[cut:].strip()
    return [line for line in (first, second) if line]


def wrap_text(text: str, max_chars: int) -> List[str]:
    """Create semantic, balanced captions with limited adaptive line length."""

    max_chars = max(1, int(max_chars or 12))
    # A phrase may use a few extra characters instead of producing a rigid
    # one- or two-character orphan line. ASS rendering shrinks only that cue.
    adaptive_line_capacity = max_chars + max(1, round(max_chars * 0.33))
    caption_capacity = adaptive_line_capacity * 2
    captions: List[str] = []
    for unit in subtitle_sentences(text):
        for chunk in _split_long_unit(unit, caption_capacity):
            captions.append(
                "\n".join(
                    _balanced_caption_lines(chunk, adaptive_line_capacity)
                )
            )
    cleaned = clean_subtitle_text(text)
    return captions or ([cleaned] if cleaned else [])


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
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _adaptive_font_size(caption: str, style: SubtitleStyle) -> int:
    longest_line = max((len(line) for line in caption.splitlines()), default=1)
    base_size = max(8, int(style.font_size))
    target_chars = max(1, int(style.max_chars_per_line))
    if longest_line <= target_chars:
        return base_size
    scaled = round(base_size * target_chars / longest_line)
    minimum = min(base_size, max(8, round(base_size * 0.72)))
    return max(minimum, min(base_size, scaled))


def _ass_caption_text(caption: str, style: SubtitleStyle) -> str:
    lines = [_escape_ass_text(line) for line in caption.splitlines()]
    keyword = (style.keyword_color or "").strip()
    if len(lines) > 1 and re.fullmatch(r"#[0-9A-Fa-f]{6}", keyword):
        lines[-1] = f"{{\\c{_ass_color(keyword, style.color)}&}}{lines[-1]}"
    text = r"\N".join(lines)
    overrides: list[str] = []
    font_size = _adaptive_font_size(caption, style)
    if font_size != style.font_size:
        overrides.append(f"\\fs{font_size}")
    if (style.position or "").strip().lower() == "custom":
        x = round(max(0.0, min(1.0, style.position_x)) * 1080)
        y = round(max(0.0, min(1.0, style.position_y)) * 1920)
        overrides.extend((r"\an8", f"\\pos({x},{y})"))
    if overrides:
        text = "{" + "".join(overrides) + "}" + text
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


def _caption_weight(caption: str) -> int:
    return max(1, len(_compact_text(caption)))


def _usable_timed_tokens(
    timed_tokens: Sequence[TimedSpeechToken] | None,
    duration_seconds: float | None,
) -> list[tuple[float, float, int]]:
    usable: list[tuple[float, float, int]] = []
    for token in timed_tokens or ():
        text = _compact_text(token.text)
        if not text:
            continue
        start = max(0.0, float(token.start))
        end = max(start, float(token.end))
        if duration_seconds is not None and duration_seconds > 0:
            start = min(start, duration_seconds)
            end = min(end, duration_seconds)
        if end <= start:
            continue
        usable.append((start, end, len(text)))
    usable.sort(key=lambda item: (item[0], item[1]))
    return usable


def _timed_boundary(
    tokens: list[tuple[float, float, int]],
    target_weight: float,
    *,
    start_side: bool,
) -> float:
    if target_weight <= 0:
        return tokens[0][0]
    total_weight = sum(item[2] for item in tokens)
    if target_weight >= total_weight:
        return tokens[-1][1]
    elapsed = 0.0
    for index, (start, end, weight) in enumerate(tokens):
        next_elapsed = elapsed + weight
        if target_weight < next_elapsed:
            ratio = (target_weight - elapsed) / max(1, weight)
            return start + (end - start) * ratio
        if abs(target_weight - next_elapsed) < 1e-6:
            if start_side and index + 1 < len(tokens):
                return tokens[index + 1][0]
            return end
        elapsed = next_elapsed
    return tokens[-1][1]


def build_subtitle_cues(
    script: str,
    style: SubtitleStyle,
    duration_seconds: float | None = None,
    timed_tokens: Sequence[TimedSpeechToken] | None = None,
) -> List[SubtitleCue]:
    captions = preview_subtitles(script, style)
    if not captions:
        return []

    caption_weights = [_caption_weight(caption) for caption in captions]
    total_caption_weight = sum(caption_weights)
    timed = _usable_timed_tokens(timed_tokens, duration_seconds)
    cues: List[SubtitleCue] = []

    if timed:
        total_token_weight = sum(item[2] for item in timed)
        consumed = 0
        for index, (caption, weight) in enumerate(
            zip(captions, caption_weights, strict=True)
        ):
            start_target = consumed / total_caption_weight * total_token_weight
            consumed += weight
            end_target = consumed / total_caption_weight * total_token_weight
            start = _timed_boundary(timed, start_target, start_side=True)
            end = _timed_boundary(timed, end_target, start_side=False)
            if index == 0:
                start = timed[0][0]
            if index == len(captions) - 1:
                end = timed[-1][1]
            cues.append(SubtitleCue(start, max(start + 0.05, end), caption))
        return cues

    if duration_seconds is None or duration_seconds <= 0:
        duration_seconds = max(1.0, total_caption_weight / 4.0)
    consumed = 0
    for caption, weight in zip(captions, caption_weights, strict=True):
        start = duration_seconds * consumed / total_caption_weight
        consumed += weight
        end = duration_seconds * consumed / total_caption_weight
        cues.append(SubtitleCue(start, max(start + 0.05, end), caption))
    return cues


def generate_srt(
    script: str,
    style: SubtitleStyle,
    output_path: Path,
    duration_seconds: float | None = None,
    timed_tokens: Sequence[TimedSpeechToken] | None = None,
) -> Path:
    cues = build_subtitle_cues(
        script,
        style,
        duration_seconds=duration_seconds,
        timed_tokens=timed_tokens,
    )
    blocks = []
    for index, cue in enumerate(cues, start=1):
        rendered_line = _apply_keyword_color(cue.text, style)
        blocks.append(
            f"{index}\n"
            f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}\n"
            f"{rendered_line}\n"
        )
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return output_path


def generate_ass(
    script: str,
    style: SubtitleStyle,
    output_path: Path,
    duration_seconds: float | None = None,
    timed_tokens: Sequence[TimedSpeechToken] | None = None,
) -> Path:
    cues = build_subtitle_cues(
        script,
        style,
        duration_seconds=duration_seconds,
        timed_tokens=timed_tokens,
    )
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
    dialogues = [
        "Dialogue: 0,"
        f"{_format_ass_timestamp(cue.start)},{_format_ass_timestamp(cue.end)},"
        f"Default,,0,0,0,,{_ass_caption_text(cue.text, style)}"
        for cue in cues
    ]
    output_path.write_text(header + "\n".join(dialogues) + "\n", encoding="utf-8")
    return output_path


def subtitle_time_range_for_text(
    script: str,
    style: SubtitleStyle,
    query: str,
    duration_seconds: float | None = None,
    timed_tokens: Sequence[TimedSpeechToken] | None = None,
) -> tuple[float, float] | None:
    needle = _compact_text(query)
    if not needle:
        return None
    cues = build_subtitle_cues(
        script,
        style,
        duration_seconds=duration_seconds,
        timed_tokens=timed_tokens,
    )
    compact_parts = [_compact_text(cue.text) for cue in cues]
    full_text = "".join(compact_parts)
    match_start = full_text.find(needle)
    if match_start >= 0:
        match_end = match_start + len(needle)
        cursor = 0
        first_index: int | None = None
        last_index: int | None = None
        for index, part in enumerate(compact_parts):
            part_start = cursor
            part_end = cursor + len(part)
            if first_index is None and part_end > match_start:
                first_index = index
            if part_start < match_end:
                last_index = index
            cursor = part_end
        if first_index is not None and last_index is not None:
            return cues[first_index].start, cues[last_index].end

    for cue, compact in zip(cues, compact_parts, strict=True):
        if needle in compact or compact in needle:
            return cue.start, cue.end
    return None
