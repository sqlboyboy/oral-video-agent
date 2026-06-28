import struct
import subprocess
import zlib
from pathlib import Path
from textwrap import wrap


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _draw_rect(
    pixels: bytearray,
    width: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int],
) -> None:
    for yy in range(max(0, y), min(y + rect_height, len(pixels) // (width * 3))):
        for xx in range(max(0, x), min(x + rect_width, width)):
            offset = (yy * width + xx) * 3
            pixels[offset : offset + 3] = bytes(color)


def generate_cover_png(title: str, script: str, output_path: Path) -> Path:
    width, height = 720, 1280
    pixels = bytearray(width * height * 3)

    for y in range(height):
        for x in range(width):
            ratio = y / height
            r = int(24 + 20 * ratio)
            g = int(132 + 40 * ratio)
            b = int(145 + 35 * ratio)
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes((r, g, b))

    _draw_rect(pixels, width, 42, 82, 636, 170, (238, 255, 250))
    _draw_rect(pixels, width, 64, 302, 592, 520, (255, 255, 255))
    _draw_rect(pixels, width, 96, 360, 528, 16, (37, 160, 170))

    title_lines = wrap(title or "爆款口播视频", width=12)[:3]
    body_lines = wrap(script.replace("，", " ").replace("。", " "), width=16)[:6]

    # Lightweight bitmap-like text placeholder: bars represent line density.
    for idx, line in enumerate(title_lines):
        _draw_rect(pixels, width, 96, 132 + idx * 42, min(500, 28 * len(line)), 22, (18, 92, 98))
    for idx, line in enumerate(body_lines):
        _draw_rect(pixels, width, 112, 430 + idx * 52, min(476, 18 * len(line)), 18, (55, 72, 78))

    _draw_rect(pixels, width, 96, 910, 528, 120, (20, 105, 118))
    _draw_rect(pixels, width, 180, 952, 360, 26, (240, 255, 252))

    raw = b"".join(b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png)
    return output_path


def extract_first_frame_cover_png(video_path: Path, output_path: Path) -> Path:
    from .renderer import _ffmpeg_executable

    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to extract video cover")
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return output_path
