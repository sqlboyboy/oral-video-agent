from pathlib import Path
from typing import List

from ..models import SubtitleStyle


def wrap_text(text: str, max_chars: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars or char in "。！？!?":
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    return lines or [text]


def preview_subtitles(script: str, style: SubtitleStyle) -> List[str]:
    return wrap_text(script, style.max_chars_per_line)


def generate_srt(script: str, style: SubtitleStyle, output_path: Path) -> Path:
    lines = preview_subtitles(script, style)
    blocks = []
    for idx, line in enumerate(lines, start=1):
        start = idx - 1
        end = idx
        blocks.append(
            f"{idx}\n"
            f"00:00:{start:02d},000 --> 00:00:{end:02d},000\n"
            f"{line}\n"
        )
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return output_path
