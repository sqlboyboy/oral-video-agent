import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


COVER_SIZE = (720, 1280)
TITLE_COLOR = "#FFE600"
STROKE_COLOR = "#050505"
ACCENT_COLOR = "#FF4FB8"


def _font_candidates() -> list[Path]:
    return [
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simkai.ttf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_candidates():
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _clean_text(value: str) -> str:
    text = re.sub(r"\s+", "", value or "").strip()
    return text or "爆款口播视频"


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in _clean_text(text):
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
        if len(lines) >= 3:
            break
    if current and len(lines) < 3:
        lines.append(current)
    return lines or ["爆款口播视频"]


def _cover_background(background_image_path: Path | None) -> Image.Image:
    if background_image_path and background_image_path.exists():
        try:
            image = Image.open(background_image_path).convert("RGB")
            image.thumbnail(COVER_SIZE, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", COVER_SIZE, (20, 22, 32))
            x = (COVER_SIZE[0] - image.width) // 2
            y = (COVER_SIZE[1] - image.height) // 2
            canvas.paste(image, (x, y))
            image = canvas.filter(ImageFilter.GaussianBlur(radius=1.0))
            overlay = Image.new("RGBA", COVER_SIZE, (0, 0, 0, 92))
            return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        except Exception:
            pass

    width, height = COVER_SIZE
    image = Image.new("RGB", COVER_SIZE)
    pixels = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(18 + 34 * ratio)
        g = int(22 + 10 * ratio)
        b = int(38 + 38 * ratio)
        for x in range(width):
            glow = max(0, 1 - ((x - width * 0.56) ** 2 + (y - height * 0.22) ** 2) / (width * height * 0.22))
            pixels[x, y] = (
                min(255, int(r + 34 * glow)),
                min(255, int(g + 12 * glow)),
                min(255, int(b + 42 * glow)),
            )
    return image


def generate_cover_png(
    title: str,
    script: str,
    output_path: Path,
    *,
    background_image_path: Path | None = None,
) -> Path:
    image = _cover_background(background_image_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    title_source = _clean_text(title) if title else _clean_text(script)[:32]
    title_font = _load_font(62)
    tag_font = _load_font(25)
    lines = _wrap_text(draw, title_source, title_font, 620)

    total_height = len(lines) * 74
    start_y = 168 if len(lines) <= 2 else 136
    panel_padding_x = 30
    panel_padding_y = 18
    widest = max(_text_width(draw, line, title_font) for line in lines)
    panel_w = min(660, widest + panel_padding_x * 2)
    panel_h = total_height + panel_padding_y * 2
    panel_x = (COVER_SIZE[0] - panel_w) // 2
    panel_y = start_y - panel_padding_y
    draw.rounded_rectangle(
        [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
        radius=30,
        fill=(0, 0, 0, 142),
        outline=(255, 79, 184, 190),
        width=3,
    )

    for index, line in enumerate(lines):
        line_w = _text_width(draw, line, title_font)
        x = (COVER_SIZE[0] - line_w) // 2
        y = start_y + index * 74
        draw.text(
            (x, y),
            line,
            font=title_font,
            fill=TITLE_COLOR,
            stroke_width=7,
            stroke_fill=STROKE_COLOR,
        )

    tag = "口播干货"
    tag_w = _text_width(draw, tag, tag_font) + 42
    tag_x = (COVER_SIZE[0] - tag_w) // 2
    tag_y = panel_y - 58
    draw.rounded_rectangle(
        [tag_x, tag_y, tag_x + tag_w, tag_y + 40],
        radius=20,
        fill=ACCENT_COLOR,
    )
    draw.text(
        (tag_x + 21, tag_y + 6),
        tag,
        font=tag_font,
        fill="white",
        stroke_width=1,
        stroke_fill=STROKE_COLOR,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, "PNG", optimize=True)
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
